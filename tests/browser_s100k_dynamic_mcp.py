"""Clean bounded dynamic windows; full functional probes run only between windows."""
import argparse, hashlib, json, platform, subprocess, time
from urllib.request import urlopen
from pathlib import Path
from browser_navigation_mcp import browser
from browser_sectors_mcp import CAPTURE, LISTENERS
from browser_s100k_mcp import SUMMARY, distribution

INSTALL = '''()=>{const s=window.__sectorStage;window.__bench=null;
 const record=(key,value)=>{const b=window.__bench;if(b&&(b[key]??=[]).length<20000)b[key].push(value);};
 s.onCameraTiming=t=>record('camera_cpu',t);
 s.onTiming=e=>record('ready_to_display_elapsed',e.ms);
 for(const [obj,name,key] of [[s.layer,'tick','lod_cpu'],[s.layer,'pick','picking_cpu'],[s.renderer,'render','render_submission_cpu']]){
 const fn=obj[name];obj[name]=function(...args){const t=performance.now();try{return fn.apply(this,args);}finally{record(key,performance.now()-t);}};}
 const fn=s.layer.prepare;s.layer.prepare=(...args)=>{const t=performance.now();const result=fn(...args);record('prepare_prelude_cpu',performance.now()-t);return result.then(ok=>{if(ok){const m=s.layer.timing();record('commit_cpu',m.applyMs);record('prepare_elapsed',m.prepareMs);record('prepare_slice_max',m.sliceMaxMs);}return ok;});};
 const manager=window.__sectorManager,load=manager.load;manager.load=function(...args){const t=performance.now();return load.apply(this,args).then(f=>{record('selection_elapsed',performance.now()-t);return f;});};
 s.layer.onPhase=e=>record(e.kind,e.ms);
 const observer=new PerformanceObserver(list=>{for(const e of list.getEntries())if(e.name.includes('/api/positions/v1/'))record('http_elapsed',e.responseEnd-e.startTime);});observer.observe({type:'resource',buffered:false});
 const old=manager.onPhase;manager.onPhase=e=>{old?.(e);record(e.kind,e.ms);};
 let last=null;const tick=t=>{if(window.__bench&&last!==null)record('frame',t-last);last=window.__bench?t:null;requestAnimationFrame(tick);};requestAnimationFrame(tick);return true;}'''

def run(url,seconds,hardware,cycles_count=3):
    report={'complete':False,'os':platform.platform(),'hardware_display_acceptance':False,
      'method':'headless RAF timestamps, no monitor presentation or GPU fence; bounded 20000 samples per metric/window; no full probes inside windows',
      'action_profile':{'seconds_after_actions':seconds,'cycles':cycles_count,'trusted_input':True},
      'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('frontend/src/physical').glob('*') if p.is_file()},'windows':{}}
    Path(OUTPUT).write_text(json.dumps(report,indent=2))
    with urlopen(url.rstrip('/')+'/api/health',timeout=10) as response:
        report['fixture_health']=json.load(response)
    assert report['fixture_health'].get('synthetic') is True and report['fixture_health'].get('objects')==100000,report['fixture_health']
    with browser(window_size='1920,1167',software=not hardware) as (m,debug):
        m.call('navigate_page',url=url,timeout=45000,initScript=LISTENERS+"window.__stressErrors=[];addEventListener('error',e=>__stressErrors.push(e.message));addEventListener('unhandledrejection',e=>__stressErrors.push(String(e.reason)));")
        m.wait("document.querySelector('canvas') && document.querySelector('.objectRow')")
        report['served_scripts']=m.evaluate('async()=>Promise.all([...document.scripts].filter(s=>s.src).map(async s=>({url:s.src,sha256:Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await (await fetch(s.src)).arrayBuffer())),x=>x.toString(16).padStart(2,"0")).join("")})))')
        m.evaluate(CAPTURE)
        m.wait('window.__sectorStage.displayedAt && window.__sectorStage.layer.timing().slots===100000')
        report['cold_interactive_ms']=m.evaluate('()=>performance.now()')
        m.click('Пауза');m.wait('window.__sectorStage.layer.timing().slots===100000')
        report['initial']=m.evaluate(SUMMARY)
        assert all(report['initial'][k]==100000 for k in ['resident','computed','submitted','in_frustum','numeric','identities'])
        m.evaluate(INSTALL)
        report['instrumentation_micro_cpu_ms']=m.evaluate('()=>{const a=[];const t=performance.now();for(let i=0;i<10000;i++){const s=performance.now();a.push(performance.now()-s);}return {iterations:10000,total:performance.now()-t};}')
        def hold(key,ms=500):
            subprocess.run(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,key,str(ms)],check=True,capture_output=True)
        def window(name,action=None,warmup=1):
            time.sleep(warmup)
            m.evaluate('()=>{window.__bench={};return true;}')
            start=time.monotonic()
            if action:action()
            time.sleep(seconds)
            raw=m.evaluate('()=>{const b=window.__bench;window.__bench=null;return b;}')
            report['windows'][name]={'duration_s':time.monotonic()-start,'warmup_s':warmup,'metrics':{k:distribution(v) for k,v in raw.items()},
                'pause_durations_ms':[v for v in raw.get('frame',[]) if v>50],
                'bounded_counters':m.evaluate('()=>{const s=window.__sectorStage;return {manager:window.__sectorManager.inspect(),layer:s.layer.timing(),submitted:s.renderer.info.render.points,calls:s.renderer.info.render.calls,memory:s.renderer.info.memory,rebases:s.rebases,displayed:s.displayedAt};}')}
            report['windows'][name]['outside_window_full_check']=m.evaluate(SUMMARY)
            check=report['windows'][name]['outside_window_full_check']
            assert check['numeric']==check['computed']==check['identities']
            assert check['sameRenderer'] and check['memory']==report['initial']['memory'] and check['listeners']==report['initial']['listeners']
            assert check['manager']['peakObjects']<=200000 and check['manager']['peakActive']<=4
            assert check['manager']['peakSerialized']<=64*1024*1024 and check['manager']['peakDecoded']<=512*1024*1024
            Path(OUTPUT).write_text(json.dumps(report,indent=2));print(name,flush=True)
        window('steady',warmup=3)
        point=m.evaluate('()=>{const r=window.__sectorStage.renderer.domElement.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];}')
        def picks():
            for _ in range(20):hold('Click',json.dumps(point))
        window('picking',picks)
        m.click('Свободный полёт');m.call('click',uid=m.uid('Проверенные геометрические центры','main'))
        window('flight',lambda:[hold(k) for k in ['ArrowRight','ArrowUp','KeyE','KeyW']])
        for _ in range(7):m.click('Увеличить скорость полёта')
        m.call('click',uid=m.uid('Проверенные геометрические центры','main'))
        before_rebase=m.evaluate('()=>window.__sectorStage.rebases')
        window('rebase_eviction',lambda:hold('KeyW',1800))
        assert m.evaluate('()=>window.__sectorStage.rebases')>before_rebase
        assert m.evaluate('()=>window.__sectorStage.layer.timing().slots')==0
        m.click('Наблюдать');m.click('Обзор системы');m.wait('window.__sectorStage.layer.timing().slots===100000')
        for mode in ['Сейчас','Ускорить','⟲']:
            window(mode,lambda mode=mode:m.click(mode))
        m.click('Пауза');m.wait('window.__sectorStage.layer.timing().slots===100000')
        def cycle():
            m.call('fill',uid=m.uid('Поиск по всему каталогу','textbox'),value='synthetic-99999')
            m.wait("Array.from(document.querySelectorAll('.objectRow')).some(e=>e.textContent.includes('synthetic-99999'))")
            m.click('synthetic-99999');m.click('Наблюдать synthetic-99999');m.click('Свободный полёт')
            m.call('click',uid=m.uid('Проверенные геометрические центры','main'));hold('KeyW',1800)
            m.click('Наблюдать synthetic-99999');m.click('Обзор системы');m.wait('window.__sectorStage.layer.timing().slots===100000')
        if cycles_count==3:
            window('cycles',lambda:[cycle() for _ in range(3)])
        else:
            for index in range(cycles_count):
                window(f'cycle_{index+1:02d}',cycle)
        report['final']=m.evaluate(SUMMARY)
        assert report['final']['numeric']==100000 and report['final']['sameRenderer']
        report['instrumentation']='performance.now pairs, bounded array pushes, one RAF callback; render_submission includes driver CPU/upload submission, not GPU completion. Instrumentation overhead not independently isolated.'
        report['errors']=m.evaluate('()=>window.__stressErrors');assert not report['errors'],report['errors']
        report['complete']=True
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://localhost:5174/');p.add_argument('--seconds',type=int,default=10);p.add_argument('--hardware',action='store_true');p.add_argument('--cycles',type=int,default=3);p.add_argument('--report',required=True);a=p.parse_args()
    OUTPUT=a.report
    try:
        result=run(a.url,a.seconds,a.hardware,a.cycles)
    except Exception as error:
        result=json.loads(Path(a.report).read_text());result.update(complete=False,error=repr(error))
        Path(a.report).write_text(json.dumps(result,indent=2));raise
    Path(a.report).write_text(json.dumps(result,indent=2))
