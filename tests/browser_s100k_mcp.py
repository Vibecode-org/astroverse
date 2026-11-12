"""Opt-in 100k HTTP -> production manager/layer -> WebGL, real MCP actions.
Read-only probes measure identity/frustum. No camera or frame assignment.
"""
import argparse
from datetime import datetime
import json
import math
import platform
import subprocess
import time
import tempfile
from pathlib import Path
from browser_navigation_mcp import browser
from browser_sectors_mcp import CAPTURE, LISTENERS

SUMMARY = '''()=>{const s=window.__sectorStage, l=s.layer.inspect(), stats=s.layer.timing();
 s.camera.updateMatrixWorld();let inside=0, numeric=0;const pixels=new Set();let overlap=0;
 const canvas=s.renderer.domElement,w=canvas.width,h=canvas.height;
 for(let i=0;i<l.rows.length;i++){
   const row=l.rows[i],n=Number(row.id.split('-')[1]),k=n===50001?50000:n;
   const expected=[(k%400-199.5)*4000,0,(Math.floor(k/400)-124.5)*4000];
   if(row.position.every((v,a)=>v===expected[a]))numeric++;
   const p=s.camera.position.clone().fromArray(l.render,i*3).project(s.camera);
   if(Math.abs(p.x)<=1&&Math.abs(p.y)<=1&&Math.abs(p.z)<=1){inside++;const key=Math.round((p.x+1)*w/2)+','+Math.round((1-p.y)*h/2);if(pixels.has(key))overlap++;pixels.add(key);}
 }
 const gl=s.renderer.getContext(),ext=gl.getExtension('WEBGL_debug_renderer_info');
 return {resident:window.__sectorManager.inspect().residentObjects,computed:l.rows.length,
 submitted:s.renderer.info.render.points,allocated_slots:stats.slots,in_frustum:inside,numeric,identities:new Set(l.rows.map(r=>r.id)).size,
 pixel_center_collisions:overlap,hidden_by_policy:0,raster_occlusion:"marker footprints overlap; centers counted separately",lod0:stats.slots-stats.detailed,lod1:stats.detailed,
 calls:s.renderer.info.render.calls,stats:{...stats,assignments:undefined},
 memory:s.renderer.info.memory,heap:performance.memory?{used:performance.memory.usedJSHeapSize,total:performance.memory.totalJSHeapSize}:null,manager:window.__sectorManager.inspect(),listeners:window.__listenerCount,
 sameRenderer:s.renderer===window.__originalRenderer,framebuffer:[w,h],dpr:s.renderer.getPixelRatio(),
 environment:{userAgent:navigator.userAgent,cores:navigator.hardwareConcurrency,renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}};
}'''

def distribution(values):
    values=sorted(values)
    return {'n':len(values),'p50':values[len(values)//2], 'p95':values[math.ceil(len(values)*.95)-1], 'p99':values[math.ceil(len(values)*.99)-1], 'max':values[-1], 'over50ms':sum(v>50 for v in values),'fraction_60hz':sum(v<=16.667 for v in values)/len(values)} if values else None

def run(url,seconds,hardware=False):
    report={'action_timing_includes_readonly_diagnostics':True,'marker_footprints':'5px L0 / 15px L1 overlap densely; pixel_center_collisions counts centers only, not marker footprint pairs', 'complete':False,'hardware_criterion_passed':False,'checks':[], 'os':platform.platform()}
    with browser(window_size='1920,1167',software=not hardware) as (m,debug):
        m.call('navigate_page',url=url,timeout=45000,initScript=LISTENERS+"window.__errors=[];addEventListener('error',e=>__errors.push(e.message));addEventListener('unhandledrejection',e=>__errors.push(String(e.reason)));")
        m.wait("document.querySelector('.objectRow') && document.querySelector('canvas')")
        m.evaluate(CAPTURE)
        m.wait('window.__sectorStage.layer.timing().slots===100000 && window.__sectorStage.renderer.info.render.points===100000 && window.__sectorStage.displayedAt')
        report['cold_interactive_ms']=m.evaluate('()=>performance.now()')
        m.click('Пауза')
        m.wait('window.__sectorStage.layer.timing().slots===100000')
        report['initial']=m.evaluate(SUMMARY)
        m.call('take_screenshot',filePath=str(Path(tempfile.gettempdir())/'astroverse-s100k.png'))
        assert all(report['initial'][k]==100000 for k in ('resident','computed','submitted','in_frustum','numeric','identities')),report['initial']
        assert report['initial']['calls']==1
        print('checkpoint',len(report['checks']),flush=True);report['checks'].append('100000 identities, known centers, submitted and in frustum via ordinary page load')
        # Warmup, then an isolated steady sample; no builds running during this interval.
        m.evaluate('async()=>{await new Promise(r=>setTimeout(r,3000));return true;}')
        m.evaluate('''()=>{const s=window.__sectorStage;window.__sample={frame:[],camera:[],lod:[],apply:[],pick:[],commit:[],preparation_wall:[],preparation_slice_max:[]};
          let last=null;window.__stopSample=false;
          const tick=t=>{if(last!==null)__sample.frame.push(t-last);last=t;if(!__stopSample)requestAnimationFrame(tick);};requestAnimationFrame(tick);
          s.onCameraTiming=t=>__sample.camera.push(t);
          const prepare=s.layer.prepare;s.layer.prepare=async(...args)=>{const applied=await prepare(...args);if(applied){const t=s.layer.timing();__sample.commit.push(t.applyMs);__sample.preparation_wall.push(t.prepareMs);__sample.preparation_slice_max.push(t.sliceMaxMs);}return applied;};
          for(const [method,key] of [['tick','lod'],['update','apply'],['pick','pick']]){const fn=s.layer[method];s.layer[method]=(...args)=>{const t=performance.now();const r=fn(...args);__sample[key].push(performance.now()-t);return r;};}return true;}''')
        time.sleep(seconds)
        m.evaluate('()=>{window.__stopSample=true;return true;}')
        report['steady']={k:distribution(v) for k,v in m.evaluate('()=>window.__sample').items()}
        m.evaluate('()=>{window.__steadySample=window.__sample;window.__sample={frame:[],camera:[],lod:[],apply:[],pick:[],commit:[],preparation_wall:[],preparation_slice_max:[]};window.__stopSample=false;let last=null;const tick=t=>{if(last!==null)__sample.frame.push(t-last);last=t;if(!__stopSample)requestAnimationFrame(tick);};requestAnimationFrame(tick);return true;}')
        report['steady_seconds']=seconds;report['warmup_seconds']=3
        report['actions_start']=m.evaluate('()=>performance.now()')
        # Trusted click on a projected center; projection reads a copy only.
        point=m.evaluate('''()=>{const s=window.__sectorStage,l=s.layer.inspect(),p=s.camera.position.clone().fromArray(l.render,12345*3).project(s.camera),r=s.renderer.domElement.getBoundingClientRect();return {x:r.left+(p.x+1)*r.width/2,y:r.top+(1-p.y)*r.height/2};}''')
        subprocess.run(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,'Click',json.dumps([point['x'],point['y']])],check=True,capture_output=True)
        for oid in ['synthetic-00000','synthetic-00999','synthetic-01000','synthetic-49999','synthetic-50000','synthetic-50001','synthetic-99999']:
            m.call('fill',uid=m.uid('Поиск по всему каталогу','textbox'),value=oid)
            m.wait("Array.from(document.querySelectorAll('.objectRow')).some(e=>e.textContent.includes("+json.dumps(oid)+"))")
            m.click(oid)
            m.wait('document.querySelector(".infoPanel")')
            m.wait('window.__sectorStage.layer.timing().slots>0')
            assert m.evaluate('()=>document.querySelector(".infoPanel").textContent').find(oid)>=0
        print('checkpoint',len(report['checks']),flush=True);report['checks'].append('search/card selection across sector boundaries and exact overlapping centers')
        m.evaluate('''()=>{const s=window.__sectorStage,fn=s.layer.rebase;window.__rebaseProof=[];
          s.layer.rebase=delta=>{const before=s.layer.inspect(16),c=s.camera.clone();
            c.position.x+=delta[0]/1e5;c.position.y+=delta[2]/1e5;c.position.z-=delta[1]/1e5;c.updateMatrixWorld();
            const old=before.rows.map((_,i)=>c.position.clone().fromArray(before.render,i*3).project(c));
            fn(delta);s.camera.updateMatrixWorld();const after=s.layer.inspect(16);let error=0;
            after.rows.forEach((_,i)=>{const p=s.camera.position.clone().fromArray(after.render,i*3).project(s.camera);
              error=Math.max(error,Math.hypot((p.x-old[i].x)*s.renderer.domElement.clientWidth/2,(p.y-old[i].y)*s.renderer.domElement.clientHeight/2));});
            __rebaseProof.push({max_css_px:error,bitwise_centers:JSON.stringify(before.rows)===JSON.stringify(after.rows)});};return true;}''')
        for cycle in range(3):
            m.click('Свободный полёт')
            if cycle==0:
                for _ in range(7):m.click('Увеличить скорость полёта')
            m.call('click',uid=m.uid('Проверенные геометрические центры','main'))
            for key in ['ArrowRight','ArrowUp','KeyE','KeyW']:
                subprocess.run(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,key,'1000' if key=='KeyW' else '500'],check=True,capture_output=True)
            m.wait('window.__sectorStage.rebases>0 && window.__sectorStage.layer.timing().slots===0')
            m.click('Наблюдать synthetic-99999')
            m.wait('window.__sectorStage.layer.timing().slots>0')
            m.click('Обзор системы')
            m.wait('window.__sectorStage.layer.timing().slots===100000')
            current=m.evaluate(SUMMARY)
            assert current['sameRenderer'] and current['numeric']==100000
            assert current['memory']==report['initial']['memory'] and current['listeners']==report['initial']['listeners'],current
            report.setdefault('cycles',[]).append(current)
        # Manual date and continuous clock modes must publish coherent full sets.
        m.call('fill',uid=m.uid('Дата UTC','DateTime'),value='2020-04-05T12:00:00')
        m.wait("window.__sectorStage.displayedAt?.startsWith('2020-04-05T12:00:00') && window.__sectorStage.layer.timing().slots===100000")
        report['displayed_time_progress']=[]
        for mode in ['Сейчас','Ускорить','⟲']:
            m.click(mode)
            m.wait('window.__sectorStage.displayedAt && window.__sectorStage.renderer.info.render.points===100000 && window.__sectorStage.layer.timing().slots===100000 && window.__sectorManager.inspect().residentObjects===100000')
            at=m.evaluate('()=>window.__sectorStage.displayedAt')
            m.wait('window.__sectorStage.displayedAt && window.__sectorStage.displayedAt!=='+json.dumps(at)+' && window.__sectorStage.renderer.info.render.points===100000')
            later=m.evaluate('()=>window.__sectorStage.displayedAt')
            assert datetime.fromisoformat(later) < datetime.fromisoformat(at) if mode=='⟲' else datetime.fromisoformat(later) > datetime.fromisoformat(at)
            report['displayed_time_progress'].append({'mode':mode,'from':at,'to':later})
            assert m.evaluate(SUMMARY)['numeric']==100000
        m.click('Пауза');m.wait('window.__sectorStage.layer.timing().slots===100000')
        # Permanent partial error clears, never publishes siblings or fallback.
        m.evaluate("async()=>(await fetch('/api/_test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fail:'s100k:50'})})).json()")
        m.call('fill',uid=m.uid('Дата UTC','DateTime'),value='2020-04-06T12:00:00')
        m.wait('window.__sectorStage.layer.timing().slots===0 && window.__sectorManager.inspect().active===0')
        m.evaluate("async()=>(await fetch('/api/_test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fail:'',conflict:1})})).json()")
        m.call('fill',uid=m.uid('Дата UTC','DateTime'),value='2020-04-07T12:00:00')
        m.wait('window.__sectorStage.layer.timing().slots===100000')
        print('checkpoint',len(report['checks']),flush=True);report['checks'].append('manual/Now/acceleration/reverse; permanent partial failure clears; revision conflict retries atomically')
        print('checkpoint',len(report['checks']),flush=True);report['checks'].append('three trusted yaw/pitch/roll/move/refocus/overview cycles, stable renderer/resources/listeners')
        m.evaluate('()=>{window.__stopSample=true;return true;}')
        report['actions']={k:distribution(v) for k,v in m.evaluate('()=>window.__sample').items()}
        report['final']=m.evaluate(SUMMARY)
        report['rebase_proof']=m.evaluate('()=>window.__rebaseProof')
        assert report['rebase_proof'] and all(r['bitwise_centers'] and r['max_css_px']<=.05 for r in report['rebase_proof'])
        report['provider']=m.evaluate("async()=>{const {traces,...metrics}=await (await fetch('/api/_test/metrics')).json();return metrics;}")
        report['errors']=m.evaluate('()=>window.__errors');assert not report['errors'],report['errors']
        renderer=report['initial']['environment']['renderer']
        report['hardware_renderer']=not any(x in renderer.lower() for x in ('swiftshader','software','llvmpipe'))
        report['hardware_criterion_passed']=bool(report['hardware_renderer'] and report['initial']['framebuffer']==[1920,1080] and report['steady']['frame']['p95']<=16.667 and report['steady']['frame']['p99']<=33.334 and report['steady']['frame']['over50ms']==0)
        report['complete']=True
    return report


def rebase_only(url):
    """Nonempty full-set rebase, separately from frame-time measurement."""
    with browser(window_size='1920,1167',software=False) as (m,debug):
        m.call('navigate_page',url=url,timeout=45000)
        m.wait("document.querySelector('.objectRow') && document.querySelector('canvas')")
        m.evaluate(CAPTURE);m.click('Пауза')
        m.wait('window.__sectorStage.renderer.info.render.points===100000 && window.__sectorStage.layer.timing().slots===100000')
        m.evaluate('''()=>{const s=window.__sectorStage,fn=s.layer.rebase;window.__fullRebase=[];
          s.layer.rebase=delta=>{const before=s.layer.inspect(),c=s.camera.clone();
            c.position.x+=delta[0]/1e5;c.position.y+=delta[2]/1e5;c.position.z-=delta[1]/1e5;c.updateMatrixWorld();
            const old=before.rows.slice(0,16).map((_,i)=>c.position.clone().fromArray(before.render,i*3).project(c));
            fn(delta);s.camera.updateMatrixWorld();const after=s.layer.inspect();let error=0;
            old.forEach((v,i)=>{const p=s.camera.position.clone().fromArray(after.render,i*3).project(s.camera);
              error=Math.max(error,Math.hypot((p.x-v.x)*s.renderer.domElement.clientWidth/2,(p.y-v.y)*s.renderer.domElement.clientHeight/2));});
            __fullRebase.push({centers:before.rows.length,screen_samples:old.length,max_css_px:error,
              bitwise_centers:JSON.stringify(before.rows)===JSON.stringify(after.rows)});};return true;}''')
        point=m.evaluate('()=>{const r=window.__sectorStage.renderer.domElement.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];}')
        for _ in range(60):
            subprocess.run(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,'Wheel',json.dumps(point)],check=True,capture_output=True)
            if m.evaluate('()=>window.__sectorStage.camera.position.length()>150'):break
        m.wait('window.__sectorStage.camera.position.length()>100 && window.__sectorStage.renderer.info.render.points===100000 && window.__sectorStage.layer.timing().slots===100000')
        m.click('Свободный полёт')
        m.wait('window.__fullRebase.some(r=>r.centers===100000)')
        proof=m.evaluate('()=>window.__fullRebase')
        assert all(r['bitwise_centers'] and r['max_css_px']<=.05 for r in proof),proof
        return {'complete':True,'kind':'functional nonempty rebase; no FPS claim',
                'checks':['trusted OrbitControls wheel -> flight -> rebase with all100000 centers; canonical bits unchanged'],
                'proof':proof,'tolerance_css_px':.05,'actions':'native MCP Pause/flight; trusted CDP wheel; camera clones for projection only'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://localhost:5174/');p.add_argument('--seconds',type=int,default=20);p.add_argument('--rebase-only',action='store_true');p.add_argument('--hardware',action='store_true');p.add_argument('--report',required=True);a=p.parse_args()
    try:
        result=rebase_only(a.url) if a.rebase_only else run(a.url,a.seconds,a.hardware)
    except Exception as error:
        Path(a.report).write_text(json.dumps({'complete':False,'error':repr(error)},indent=2))
        raise
    Path(a.report).write_text(json.dumps(result,indent=2));print(json.dumps({'complete':result['complete'],'checks':result['checks']}))
