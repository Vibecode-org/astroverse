"""Production manager + isolated HTTP provider + real Chrome/WebGL.

Start docker-compose.sectors-test.yml, then python3 tests/browser_sectors_mcp.py.
No fetch mocks or direct layer.update calls. Camera/clock controls drive requests.
"""
import argparse
import json
from pathlib import Path
import time
import tempfile
from browser_mcp import MCP
from browser_physical_mcp import PROBE

CAPTURE = """()=>{
 const el=document.querySelector('.viewport');const key=Object.keys(el).find(k=>k.startsWith('__reactFiber'));
 let f=el[key];while(f&&!f.memoizedProps?.sceneRef)f=f.return;
 window.__sectorStage=f.memoizedProps.sceneRef.current;
 while(f){let h=f.memoizedState;while(h){if(h.memoizedState?.current?.load&&h.memoizedState.current.inspect)window.__sectorManager=h.memoizedState.current;h=h.next;}f=f.return;}
 if(!window.__sectorManager)throw new Error('Production manager hook not found');
 window.__requestCaptureStart=window.__sectorManager.inspect().requests;
 window.__requestEvents=[];
 window.__sectorManager.onRequest=event=>{if(window.__requestEvents.length>=512)throw new Error('trace overflow');window.__requestEvents.push(event);};
 return true;
}"""


def run(base='http://localhost:5174'):
    report = {'synthetic':True,'checks':[]}
    def passed(name):
        report['checks'].append(name);print('PASS',name,flush=True)
    with MCP(slow=True) as m:
        m.call('navigate_page',url=base+'/',timeout=45000,
               initScript="window.__sectorErrors=[];addEventListener('error',e=>window.__sectorErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__sectorErrors.push(String(e.reason)));")
        assert m.evaluate("async()=>(await fetch('/api/health')).json()") == {'status':'ok','objects':0,'synthetic':True}
        m.wait("document.querySelector('.physicalApp canvas') && document.querySelector('.objectRow')")
        m.click('Пауза')
        # Native pointer interaction also guards against metadata pushing the
        # list out of the viewport. Subsequent stress controls use DOM clicks.
        m.call('click',uid=m.uid('Synthetic 000'));m.evaluate(CAPTURE)
        m.wait('('+PROBE+')()?.rows.length===63')
        first=m.evaluate(PROBE);assert first['rows'][0]['id']=='synthetic-000'
        # Overview requests all four real HTTP sectors concurrently, in jitter order.
        start=time.monotonic();m.click('Обзор системы');m.wait('('+PROBE+')()?.rows.length===252')
        all_rows=m.evaluate(PROBE);report['all_load_ms']=round((time.monotonic()-start)*1000,3)
        assert len({r['sector_id'] for r in all_rows['hierarchy']['addresses']})==4
        assert m.evaluate('()=>window.__sectorManager.inspect().residentObjects')==256
        passed('four reordered HTTP sectors publish one coherent hierarchy; nulls stay unknown')
        report['gpu_before']={k:all_rows[k] for k in ['geometries','textures','calls','canvasCount']}

        def pan(x):
            m.evaluate('''()=>{const s=window.__sectorStage;s.camera.position.set(%s,8,12);s.controls.target.set(%s,0,0);s.controls.update();return true;}''' % (x,x))

        # Camera -> manifest -> sector load -> eviction -> return, repeated.
        for _ in range(8):
            for x,expected in [(0,'synthetic-000'),(60,'synthetic-064'),(120,'synthetic-128'),(180,'synthetic-192'),(1000,None),(0,'synthetic-000')]:
                pan(x)
                condition='('+PROBE+')()?.rows.length===0 && window.__sectorManager.inspect().active===0' if expected is None else '('+PROBE+')()?.rows[0]?.id==='+json.dumps(expected)
                m.wait(condition)
                s=m.evaluate(PROBE)
                assert s['canvasCount']==1 and (s['geometries'],s['textures'])==(1,0),s
                assert m.evaluate('()=>window.__sectorStage.renderer.domElement===document.querySelector("canvas")')
                assert m.evaluate('()=>window.__sectorManager.inspect().residentObjects')==(0 if expected is None else 64)
        returned=m.evaluate(PROBE);assert returned['rows']==first['rows']
        passed('48 camera moves through HTTP load/eviction/empty/return preserve centers and GPU resources')

        # LOD is exercised by camera + RAF, over the accepted native HTTP frame.
        lod=[]
        for z in [19,23,27,29,23,19]*3:
            m.evaluate('()=>{const s=window.__sectorStage;s.camera.position.set(0,0,'+str(z)+');s.controls.target.set(0,0,0);s.controls.update();return true;}')
            m.evaluate('async()=>{await new Promise(r=>setTimeout(r,1100));return true;}')
            sample=m.evaluate('()=>window.__sectorStage.layer.stats()')
            assert sample['detailed']<=32 and sample['visited']<=128
            assert m.evaluate(PROBE)['rows']==first['rows']
            lod.append(sample)
        assert lod[0]['detailed']>1 and lod[3]['detailed']==1
        assert lod[4]['detailed']==1 and lod[5]['detailed']>1
        report['lod']=lod
        passed('HTTP camera zoom L0/L1 hysteresis and repeated cycles preserve canonical centers')

        def control(**values):
            return m.evaluate("async()=>(await fetch('/api/_test/control',{method:'POST',headers:{'Content-Type':'application/json'},body:"+json.dumps(json.dumps(values))+"})).json()")

        def date(value):
            m.evaluate("()=>{const el=document.querySelector('[aria-label=\"Дата UTC\"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,"+json.dumps(value)+");el.dispatchEvent(new Event('input',{bubbles:true}));return true;}")

        control(delay=350);date('2020-04-05T12:00:00');date('2021-05-06T01:02:03')
        m.wait('('+PROBE+')()?.hierarchy?.binding.evaluated_at.startsWith("2021-05-06T01:02:03")')
        settled=m.evaluate(PROBE);at=settled['hierarchy']['binding']['evaluated_at']
        wire=m.evaluate("async()=>(await fetch('/api/positions/v1/sectors/synthetic:0?at='+encodeURIComponent("+json.dumps(at)+")+'&revision='+encodeURIComponent("+json.dumps(settled['hierarchy']['binding']['revision'])+"))).json()")
        assert all(row['position']==wire['objects'][i]['position'] for i,row in enumerate(settled['rows']))
        passed('manual date changes discard old generations; exact UTC/JD and Float64 match HTTP')

        # Force one conflict during an in-flight sector response. Full retry only.
        control(conflict=1);date('2022-02-03T04:05:06')
        m.wait('('+PROBE+')()?.hierarchy?.binding.evaluated_at.startsWith("2022-02-03T04:05:06")')
        assert m.evaluate('()=>window.__sectorManager.inspect().conflicts')>=1
        passed('HTTP 409 rediscovers the entire selection once and accepts the new revision')

        # All four requested; failure in one must never publish the others.
        control(fail='synthetic:2');m.click('Окрестность тела');m.click('Обзор системы')
        m.wait("document.querySelector('[role=status] [role=alert]')?.textContent.includes('partial failure')")
        assert m.evaluate(PROBE)['rows']==[]
        assert m.evaluate('()=>window.__sectorManager.inspect().pending')==0
        assert m.evaluate('()=>window.__sectorManager.inspect().residentObjects')==0
        passed('permanent partial HTTP failure cancels siblings and clears the whole scene')
        control(fail='');date('2022-02-04T04:05:06')
        m.wait('('+PROBE+')()?.rows.length===252')
        control(mixed='synthetic:1');date('2022-02-05T04:05:06')
        m.wait("document.querySelector('[role=status] [role=alert]')")
        assert m.evaluate(PROBE)['rows']==[]
        control(mixed='');date('2022-02-06T04:05:06')
        m.wait('('+PROBE+')()?.rows.length===252')
        passed('incompatible time cannot be merged; recovery keeps the renderer')

        # Actual hung HTTP request: terminal 10s timeout, no partial publication.
        control(hang='synthetic:0');date('2022-02-07T04:05:06')
        m.wait("document.querySelector('[role=status] [role=alert]')?.textContent.includes('Timeout')")
        assert m.evaluate(PROBE)['rows']==[]
        control(hang='');date('2022-02-08T04:05:06')
        m.wait('('+PROBE+')()?.rows.length===252')
        passed('hung HTTP sector times out at 10s and a fresh selection recovers')

        def motion(label, reverse=False):
            observations=m.evaluate('''async()=>{const out=[];for(let i=0;i<40;i++){
              await new Promise(resolve=>setTimeout(resolve,100));const s=(PROBE)();
              out.push({rows:s?.rows.length||0,at:s?.hierarchy?.binding.evaluated_at,
                status:document.querySelector('[role=status]').textContent});}return out;}'''.replace('PROBE',PROBE))
            steady=observations[15:];dates=[s['at'] for s in steady if s.get('at')]
            assert len(dates)>=20 and len(set(dates))>=2,observations
            assert all(s['rows']==252 and 'Кадр UTC: '+s['at'] in s['status'] for s in steady if s.get('at'))
            stamps=m.evaluate('()=>'+json.dumps(dates)+'.map(x=>Date.parse(x))')
            assert all((a>=b if reverse else a<=b) for a,b in zip(stamps,stamps[1:])),dates
            return {'mode':label,'nonempty':len(dates),'samples':len(steady),'frames':len(set(dates))}

        m.click('Сейчас');report['motion']=[motion('Now')]
        m.click('Пауза');m.wait("document.querySelector('[role=status]').textContent.includes('Положения вычислены на этот момент')")
        assert m.evaluate('''()=>Date.parse(document.querySelector('[role=status] div').textContent.split(' · ')[0])===Date.parse((PROBE)().hierarchy.binding.evaluated_at)'''.replace('PROBE',PROBE))
        date('2020-04-05T12:00:00');m.wait('('+PROBE+')()?.hierarchy?.binding.evaluated_at.startsWith("2020-04-05T12:00:00")')
        m.evaluate("()=>{const rate=document.querySelector('#time-rate');rate.value='86400';rate.dispatchEvent(new Event('change',{bubbles:true}));return true;}")
        m.click('Продолжить');report['motion'].append(motion('86400x'))
        m.click('⟲');report['motion'].append(motion('-86400x',True))
        m.click('Пауза');m.wait("document.querySelector('[role=status]').textContent.includes('Положения вычислены на этот момент')")
        passed('multisector HTTP jitter 350–550ms: Now, exact pause, acceleration and reverse do not starve')
        control(fail='synthetic:2');m.click('Сейчас')
        m.wait("document.querySelector('[role=status] [role=alert]')?.textContent.includes('partial failure')")
        frozen=m.evaluate('()=>window.__sectorManager.inspect().requests')
        after=m.evaluate('async()=>{await new Promise(resolve=>setTimeout(resolve,1200));return window.__sectorManager.inspect().requests;}')
        assert after==frozen and m.evaluate(PROBE)['rows']==[]
        control(fail='');m.click('Сейчас');m.wait('('+PROBE+')()?.rows.length===252')
        m.click('Пауза');m.wait("document.querySelector('[role=status]').textContent.includes('Положения вычислены на этот момент')")
        passed('permanent HTTP error stops clock retries; explicit Now starts a recoverable context')
        final=m.evaluate(PROBE);report['gpu_after']={k:final[k] for k in ['geometries','textures','calls','canvasCount']}
        assert report['gpu_after']==report['gpu_before']
        assert m.evaluate('()=>window.__sectorErrors')==[]
        report['lod_final']=m.evaluate('()=>window.__sectorStage.layer.stats()')
        report['manager']=m.evaluate('()=>window.__sectorManager.inspect()')
        assert report['manager']['peakActive']<=4 and report['manager']['peakQueue']<=128
        assert report['manager']['peakObjects']<=4096 and report['manager']['peakSerialized']<=4*1024*1024 and report['manager']['peakDecoded']<=16*1024*1024
        report['provider']=m.evaluate("async()=>(await fetch('/api/_test/metrics')).json()")
        report['events']=m.evaluate('()=>({start:window.__requestCaptureStart,requests:window.__requestEvents})')
        client=report['manager']['clientId'];start=report['events']['start']
        requests={event['request']:event for event in report['events']['requests'] if int(event['request'].rsplit('.',1)[1])>start}
        expected={client+'.'+str(n) for n in range(start+1,report['manager']['requests']+1)}
        assert set(requests)==expected,(len(requests),len(expected))
        own=[row for row in report['provider']['traces'] if row['client']==client and row['request'] in expected]
        seen=[row['request'] for row in own]
        assert len(seen)==len(set(seen)), 'duplicate request ID reached provider'
        missing=expected-set(seen)
        assert all(requests[key]['outcome']=='cancelled' for key in missing),missing
        report['reconciliation']={'captured':len(expected),'reached_provider':len(seen),
          'cancelled_before_provider':len(missing),'duplicates':0,
          'outside_capture_requests':len(report['provider']['traces'])-len(own)}
        report['http_responses']=m.evaluate("()=>performance.getEntriesByType('resource').filter(e=>e.name.includes('/api/positions/')).map(e=>({bytes:e.decodedBodySize,ms:e.duration}))")
        report['screenshot']=str((Path(tempfile.gettempdir())/'astroverse-http-sectors.png').resolve())
        m.call('take_screenshot',filePath=report['screenshot'])
        return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path)
    parser.add_argument('--url',default='http://localhost:5174');args=parser.parse_args()
    result=run(args.url.rstrip('/'))
    if args.report:args.report.write_text(json.dumps(result,indent=2)+'\n')
    summary={key:value for key,value in result.items() if key not in ['events','http_responses']}
    summary['provider']={key:value for key,value in result['provider'].items() if key!='traces'}
    print(json.dumps(summary,indent=2))
