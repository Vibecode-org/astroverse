"""6DoF acceptance: Chrome MCP UI + trusted CDP held keys + HTTP + WebGL.

Reads private React state for numeric evidence only. Never assigns camera state.
Camera/LOD/apply budgets and tolerances declared before measurement, see NAVIGATION.
"""
import argparse
from contextlib import contextmanager
import json
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import time
from browser_mcp import MCP
from browser_physical_mcp import PROBE
from browser_sectors_mcp import CAPTURE, LISTENERS


@contextmanager
def browser(window_size='1440,1000', software=True):
    chrome=shutil.which('google-chrome') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    with tempfile.TemporaryDirectory(prefix='astroverse-flight-') as profile, tempfile.TemporaryFile() as logs:
        process=subprocess.Popen([chrome,'--headless=new','--remote-debugging-port=0','--user-data-dir='+profile,
                                  '--window-size='+window_size,*(['--use-angle=swiftshader','--enable-unsafe-swiftshader'] if software else []),
                                  '--no-first-run','--no-default-browser-check','about:blank'],stdout=logs,stderr=logs)
        try:
            portfile=Path(profile)/'DevToolsActivePort'
            deadline=time.monotonic()+20
            while not portfile.exists():
                if time.monotonic()>deadline:raise TimeoutError('Chrome DevTools port missing')
                time.sleep(.1)
            base='http://127.0.0.1:'+portfile.read_text().splitlines()[0]
            with MCP(browser_url=base) as m:
                yield m,base
        finally:
            process.terminate();process.wait(timeout=10)


READ="""()=>{const s=window.__sectorStage,f=s.flight.inspect(),c=s.camera.position;
 const o=s.reference?s.reference.position.map((v,a)=>v+s.reference.offset[a]):s.layer.inspect().origin;
 return {eye:[o[0]+c.x*1e5,o[1]-c.z*1e5,o[2]+c.y*1e5],quaternion:s.camera.quaternion.toArray(),
   up:s.camera.up.toArray(),flight:f,controls:s.controls.enabled,rebases:s.rebases,
   origin:o,local:c.toArray(),listeners:window.__listenerCount,renderer:s.renderer===window.__originalRenderer,
   layer:s.layer.inspect(),stats:s.layer.stats(),memory:s.renderer.info.memory,frames:s.frames};}"""


def distribution(values):
    values=sorted(values)
    assert values
    return {'n':len(values),'mean':sum(values)/len(values),'p95':values[math.ceil(.95*len(values))-1],'max':values[-1]}


def run(url,synthetic=False,screenshot=None):
    report={'complete':False,'synthetic':synthetic,'checks':[],
            'budgets_ms':{'camera':[1,8],'apply':[16,50],'lod':[1,8]},
            'tolerances':{'cpu_roundoff_km':1e-6,'gpu_relative':1e-7,'gpu_absolute_render':1e-6,'rebase_screen_css_px':.05},
            'environment':{'os':platform.platform(),'renderer':'SwiftShader (functional, not hardware fps)'}}
    def passed(label):
        report['checks'].append(label);print('PASS',label,flush=True)
    with browser() as (m,debug):
        m.call('navigate_page',url=url+'/',timeout=45000,initScript=LISTENERS+"window.__navErrors=[];addEventListener('error',e=>window.__navErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__navErrors.push(String(e.reason)));")
        health=m.evaluate("async()=>(await fetch('/api/health')).json()")
        assert health['objects']==(0 if synthetic else 3471),health
        m.wait("document.querySelector('.objectRow') && document.querySelector('canvas')")
        m.click('Пауза')
        name='Synthetic 000' if synthetic else 'Земля'
        m.click(name);m.evaluate(CAPTURE)
        m.wait('('+PROBE+')()?.rows.length>0')
        def hold(code,seconds):
            subprocess.run(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,code,str(seconds*1000)],check=True,timeout=seconds+10,capture_output=True,text=True)
        def read():return m.evaluate(READ)
        def settle():m.evaluate('async()=>{await new Promise(r=>setTimeout(r,1100));return true;}')
        def focus_scene():
            # Native MCP click focuses the flight viewport; selection is harmless.
            m.call('click',uid=m.uid('Проверенные геометрические центры','main'))
        def date(value):
            m.call('fill',uid=m.uid('Дата UTC','DateTime'),value=value)
        m.evaluate('''()=>{const s=window.__sectorStage;window.__navTiming={camera:[],apply:[],lod:[]};
          window.__rebasePixels=[];let observed=0;
          const project=(layer,camera)=>{camera.updateMatrixWorld();const result=new Map();
            layer.rows.forEach((row,i)=>{const p=camera.position.clone().fromArray(layer.render,i*3).project(camera);
              if(Math.abs(p.x)<=1&&Math.abs(p.y)<=1&&Math.abs(p.z)<=1)result.set(row.id,[p.x,p.y]);});return result;};
          s.onCameraTiming=t=>{if(window.__navTiming.camera.length<100000)window.__navTiming.camera.push(t);};
          for(const [method,kind] of [['update','apply'],['tick','lod']]){const fn=s.layer[method];s.layer[method]=(...args)=>{
            let previous=null;
            if(kind==='apply'&&s.reference&&s.rebases>observed){observed=s.rebases;const old=s.layer.inspect(),c=s.camera.clone();
              const origin=s.reference.position.map((v,a)=>v+s.reference.offset[a]),d=origin.map((v,a)=>v-old.origin[a]);
              c.position.x+=d[0]/1e5;c.position.y+=d[2]/1e5;c.position.z-=d[1]/1e5;previous=project(old,c);}
            const t=performance.now(),r=fn(...args);window.__navTiming[kind].push(performance.now()-t);
            if(previous){const next=project(s.layer.inspect(),s.camera),rect=s.renderer.domElement.getBoundingClientRect();let max=0,n=0;
              for(const [id,p] of previous){const q=next.get(id);if(q){n++;max=Math.max(max,Math.hypot((p[0]-q[0])*rect.width/2,(p[1]-q[1])*rect.height/2));}}
              window.__rebasePixels.push({n,max_css_px:max});}
            return r;};}
          return true;}''')
        m.click('Обзор системы');m.wait('('+PROBE+')()?.rows.length==='+str(2016 if synthetic else 5))
        full=read();frozen=full['layer']['rows'];report['numeric_centers']=len(frozen)
        for i,row in enumerate(frozen):
            d=[v-o for v,o in zip(row['position'],full['layer']['origin'])];expected=[d[0]/1e5,d[2]/1e5,-d[1]/1e5]
            for actual,value in zip(full['layer']['render'][i*3:i*3+3],expected):assert abs(actual-value)<=max(1e-6,abs(value)*1e-7)
        m.click('Свободный полёт');settle();initial=read()
        assert initial['flight']['enabled'] and not initial['controls'] and initial['rebases']>=1,initial
        # CPU physical camera/centers are independent of floating representation.
        assert math.dist(initial['eye'],full['eye'])<1e-6
        passed('overview → flight transfers controls and rebases without a physical camera jump')
        # Refocus before nearby tests, to obtain ordinary local scale.
        m.click('Наблюдать '+name);settle();m.click('Свободный полёт');settle()
        stable=read();baseline=stable['layer']['rows']
        hold('ArrowLeft',.35);hold('ArrowUp',.25);hold('KeyQ',.3)
        start=read();hold('KeyW',.45);end=read()
        assert math.dist(start['eye'],end['eye'])>1000,(start,end)
        # The camera looks along rotated local -Z, including roll. Compare direction.
        x,y,z,w=start['quaternion'];forward=[-2*(x*z+w*y),-2*(y*z-w*x),-(1-2*(x*x+y*y))]
        expected=[forward[0],-forward[2],forward[1]]
        delta=[b-a for a,b in zip(start['eye'],end['eye'])];norm=math.hypot(*delta)
        assert math.dist([v/norm for v in delta],expected)<1e-6
        assert end['layer']['rows']==baseline
        report['local_forward_error']=math.dist([v/norm for v in delta],expected)
        passed('trusted held keys rotate yaw/pitch/roll and move along local forward; frozen centers unchanged')
        start=read();selected=m.evaluate('()=>document.querySelector(".infoPanel h1").textContent')
        point=m.evaluate('()=>{const r=document.querySelector(".viewport").getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];}')
        subprocess.run(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,'Drag',json.dumps(point)],check=True,timeout=10,capture_output=True,text=True)
        dragged=read();assert dragged['quaternion']!=start['quaternion']
        assert math.dist(dragged['eye'],start['eye'])<1e-6
        assert m.evaluate('()=>document.querySelector(".infoPanel h1").textContent')==selected
        passed('trusted mouse drag rotates flight without selection or OrbitControls movement')
        before=read();m.call('fill',uid=m.uid('Поиск по всему каталогу','textbox'),value='moon' if not synthetic else 'Synthetic 000')
        hold('KeyW',.3);assert math.dist(read()['eye'],before['eye'])<1e-6
        # Select via search while flying: card only, no recentering.
        m.wait("document.querySelector('.objectRow')")
        m.click('Synthetic 000' if synthetic else 'Луна');after=read()
        assert math.dist(after['eye'],before['eye'])<1e-6
        passed('search typing is isolated; selecting a body opens its card without teleporting')
        m.click('Наблюдать '+('Synthetic 000' if synthetic else 'Луна'));settle();assert not read()['flight']['enabled']
        m.click('Свободный полёт');settle()
        before=read();hold('KeyD',.3);assert math.dist(read()['eye'],before['eye'])>1000
        # Stop, blur, time controls and a genuine date input.
        m.call('press_key',key='Space');stop=read();settle();assert math.dist(read()['eye'],stop['eye'])<1e-6
        date('2020-04-05T12:00:00');m.wait('window.__sectorStage.displayedAt?.startsWith("2020-04-05T12:00:00")')
        assert math.dist(read()['eye'],stop['eye'])<1e-6
        for label in ['Сейчас','Пауза']:
            m.click(label);settle();assert math.dist(read()['eye'],stop['eye'])<1e-6
        for _ in range(3):m.click('Ускорить')
        m.click('Продолжить')
        report['time_modes']=[]
        for reverse in [False,True]:
            if reverse:m.click('⟲')
            focus_scene();a=read();hold('KeyR',.35);b=read()
            distance=math.dist(a['eye'],b['eye']);assert 15000<distance<60000,distance
            assert b['flight']['speed']==100000
            report['time_modes'].append({'reverse':reverse,'multiplier':-86400 if reverse else 86400,'distance_km':distance,'hold_seconds':.35})
        m.click('Сейчас');m.click('Пауза');settle()
        passed('explicit refocus restores observation; stop/manual date/Now/pause leave free camera fixed')
        focus_scene()
        held=subprocess.Popen(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,'KeyW','4000'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            time.sleep(.2);m.call('new_page',url='about:blank',background=False)
            # MCP evaluate brings its page to front. Read the background target
            # via CDP to preserve the genuine hidden-tab condition.
            def background_state():
                result=subprocess.run(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,'Read','0'],check=True,capture_output=True,text=True,timeout=10)
                return json.loads(result.stdout)
            # Focus emulation belongs to MCP's own CDP session. Disconnect it
            # during the actual background interval, keeping Chrome and native
            # input alive, then reconnect to the same target.
            m.__exit__(None,None,None)
            try:
                hidden=background_state();assert hidden['hidden'],hidden
                held.communicate(timeout=10);assert held.returncode==0
                background=background_state();assert background['held']==0
                assert math.dist(background['eye'],hidden['eye'])<1e-6
            finally:m.__enter__()
            pages=m.call('list_pages');m.page_id=int(re.search(r'(?m)^(\d+):.*http://localhost:',pages)[1])
            blank=int(re.search(r'(?m)^(\d+): about:blank',pages)[1]);m.call('close_page',pageId=blank)
            m.call('select_page',pageId=m.page_id,bringToFront=True);settle()
            assert math.dist(read()['eye'],hidden['eye'])<1e-6
        finally:
            if held.poll() is None:held.kill();held.communicate()
        passed('native tab switch during held flight clears keys; hidden/resume has no camera catch-up')
        # Transport/eviction from real key motion, without assigning final camera.
        if synthetic:
            m.click('Наблюдать Synthetic 000');settle();m.click('Свободный полёт');settle()
            # Clear search through MCP fill; keep body identity from existing registry.
            for _ in range(6):m.call('press_key',key='=')
            assert read()['flight']['speed']==6400000
            hold('KeyD',1.0);settle();away=read()
            assert away['layer']['rows'] and away['layer']['rows'][0]['id']!='synthetic-000',away
            assert m.evaluate('()=>window.__sectorManager.inspect().residentObjects')<=128
            m.click('Наблюдать Synthetic 000');settle();assert read()['layer']['rows'][0]['id']=='synthetic-000'
            m.evaluate("async()=>(await fetch('/api/_test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fail:'synthetic:1'})})).json()")
            m.click('Свободный полёт');settle();hold('KeyD',1);settle()
            m.wait("document.querySelector('[role=status] [role=alert]')")
            assert read()['layer']['rows']==[]
            m.evaluate("async()=>(await fetch('/api/_test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fail:''})})).json()")
            m.click('Наблюдать Synthetic 000');settle();assert read()['layer']['rows']
            passed('native flight loads/evicts HTTP sectors; explicit return and transport failure recover atomically')
        # Repeated control handoffs/refocus must retain renderer/listeners/GPU.
        selected='Synthetic 000' if synthetic else 'Луна'
        warm=read();report['resources_warm']={k:warm[k] for k in ['listeners','memory']}
        for _ in range(12):
            if read()['flight']['enabled']:m.click('Завершить полёт')
            m.click('Свободный полёт');hold('KeyR',.08);m.click('Наблюдать '+selected)
        final=read();assert final['renderer'] and final['listeners']==warm['listeners']
        assert final['memory']==warm['memory'];assert m.evaluate('()=>document.querySelectorAll("canvas").length')==1
        report['resource_cycles']=12;report['resources_final']={k:final[k] for k in ['listeners','memory']}
        passed('12 flight/exit/refocus cycles retain renderer, canvas, GPU resources and listener count')
        report['timing_ms']={k:distribution(v) for k,v in m.evaluate('()=>window.__navTiming').items()}
        report['rebase_projection']=m.evaluate('()=>window.__rebasePixels')
        assert sum(r['n'] for r in report['rebase_projection'])>0
        assert all(r['max_css_px']<=.05 for r in report['rebase_projection'])
        report['budget_passed']={key:report['timing_ms'][key]['p95']<=budget[0] and report['timing_ms'][key]['max']<=budget[1]
                                 for key,budget in report['budgets_ms'].items()}
        report['environment'].update(m.evaluate('()=>({userAgent:navigator.userAgent,cores:navigator.hardwareConcurrency,width:innerWidth,height:innerHeight,dpr:devicePixelRatio})'))
        assert m.evaluate('()=>window.__navErrors')==[]
        if screenshot:
            if not read()['flight']['enabled']:m.click('Свободный полёт')
            m.wait('window.__sectorStage.displayedAt!==null')
            m.call('take_screenshot',filePath=str(screenshot))
        report['complete']=True
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://localhost:5173');p.add_argument('--synthetic',action='store_true');p.add_argument('--report',type=Path,required=True);p.add_argument('--screenshot',type=Path);a=p.parse_args()
    result=run(a.url,a.synthetic,a.screenshot);a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
    if not all(result['budget_passed'].values()):raise SystemExit('Navigation CPU budget exceeded; evidence saved')
