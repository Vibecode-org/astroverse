"""Negative-path regression using installed Chrome DevTools MCP.

Only the isolated browser's fetch responses/state are controlled. Real vectors
are never changed. Expected HTTP 409 resource errors are intentional here;
uncaught JavaScript errors and GPU resource growth remain failures.
"""
import argparse
import json
from pathlib import Path
from browser_mcp import MCP
from browser_physical_mcp import PROBE

CONTROL = """
window.__recoveryMode='off';window.__recoveryManifests=0;window.__recoveryTrace=[];window.__recoveryErrors=[];
addEventListener('error',e=>window.__recoveryErrors.push(e.message));
addEventListener('unhandledrejection',e=>window.__recoveryErrors.push(String(e.reason)));
const realFetch=window.fetch.bind(window);
window.fetch=async(...args)=>{
 const response=await realFetch(...args);
 const url=new URL(typeof args[0]==='string'?args[0]:args[0].url,location.href);
 if(!url.pathname.startsWith('/api/positions/v1/'))return response;
 const isManifest=url.pathname.endsWith('/nearby'),isSector=url.pathname.includes('/sectors/');
 if(!isManifest&&!isSector)return response;
 window.__recoveryTrace.push({kind:isManifest?'manifest':'sector',status:response.status,pin:url.searchParams.get('revision')});
 if(!response.ok)return response;
 const body=await response.clone().json();let changed=false;
 if(isManifest){
  window.__recoveryManifests++;
  if(window.__recoveryMode==='repeat'||(window.__recoveryMode==='once'&&window.__recoveryManifests===1)){
   body.revision='audit-previous-'+body.revision;body.coordinates.revision=body.revision;
   body.sectors.forEach(sector=>sector.revision=body.revision);changed=true;
  }
 }
 if(isSector&&window.__recoveryMode==='flat-utc'){
  delete body.hierarchy;body.coordinates.time_scale='UTC';changed=true;
 }
 if(!changed)return response;
 const headers=new Headers(response.headers);headers.delete('content-encoding');headers.delete('content-length');
 return new Response(JSON.stringify(body),{status:200,headers});
};
"""
PROPS = """()=>{
 const el=document.querySelector('.viewport'),key=Object.keys(el).find(k=>k.startsWith('__reactFiber'));
 let fiber=el[key];while(fiber&&!fiber.memoizedProps?.sceneRef)fiber=fiber.return;
 return fiber.memoizedProps;
}"""
READY = "document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')"


def run(catalog):
    report={'catalog':catalog,'checks':[]}
    def passed(label):
        report['checks'].append(label);print('PASS',label,flush=True)
    with MCP() as mcp:
        mcp.call('navigate_page',url='http://localhost:5173/',timeout=45000,initScript=CONTROL)
        assert mcp.evaluate("async()=>(await fetch('/api/health')).json()")['objects']==catalog
        mcp.wait(READY);mcp.click('Пауза');mcp.wait(READY)
        initial=mcp.evaluate(PROBE)
        mcp.evaluate("()=>{window.__recoveryOriginalRenderer=("+PROPS+")().sceneRef.current.renderer;return true;}")
        def advance(mode):
            mcp.evaluate("()=>{window.__recoveryMode="+json.dumps(mode)+";window.__recoveryManifests=0;window.__recoveryTrace=[];}")
            date=mcp.evaluate("()=>document.querySelector('[role=status] div').textContent")
            mcp.click('+1 день')
            mcp.wait("document.querySelector('[role=status] div').textContent!=="+json.dumps(date))
        def trace():
            return mcp.evaluate('()=>window.__recoveryTrace')
        advance('once');mcp.wait(READY)
        raced=trace();report['race']=raced
        assert sum(e['kind']=='manifest' for e in raced)==2,raced
        sectors=[e for e in raced if e['kind']=='sector']
        assert [e['status'] for e in sectors]==[409,200] and all(e['pin'] for e in sectors),raced
        passed('revision race: pinned 409 restarts discovery once and recovers')
        advance('repeat');mcp.wait("document.querySelector('[role=alert]')?.textContent.includes('Ревизия')")
        repeated=trace();report['repeat']=repeated
        assert len(repeated)==4 and sum(e['status']==409 for e in repeated)==2,repeated
        assert mcp.evaluate(PROBE)['rows']==[]
        passed('repeated conflict: bounded retry, visible error and no stale positions')
        advance('off');mcp.wait(READY)
        assert not mcp.evaluate("()=>Boolean(document.querySelector('[role=alert]'))")
        passed('next valid request restores positions after conflict')
        advance('flat-utc');mcp.wait("document.querySelector('[role=alert]')?.textContent.includes('контракт')")
        assert mcp.evaluate(PROBE)['rows']==[]
        passed('flat positions/1 with UTC model scale is rejected')
        advance('off');mcp.wait(READY)
        mcp.evaluate("""()=>{
          const props=(PROPS)(),state=props.sceneRef.current;
          window.__recoveryUpdate=state.layer.update;
          const failedAt=Date.parse(state.layer.inspect().hierarchy.binding.evaluated_at);
          state.layer.update=(frame,...args)=>{
            if(frame&&Date.parse(frame.evaluated_at)===failedAt)throw new Error('AUDIT transient frame error');
            return window.__recoveryUpdate(frame,...args);
          };
          props.onError('AUDIT transient frame error','frame');return true;
        }""".replace('PROPS',PROPS))
        mcp.wait("document.querySelector('[role=alert]')?.textContent.includes('AUDIT transient')")
        advance('off');mcp.wait(READY)
        assert not mcp.evaluate("()=>Boolean(document.querySelector('[role=alert]'))")
        mcp.evaluate("()=>{("+PROPS+")().sceneRef.current.layer.update=window.__recoveryUpdate;return true;}")
        passed('successful frame clears transient scene error')
        mcp.evaluate("()=>{("+PROPS+")().onError('AUDIT initialization error','initialization');return true;}")
        before=mcp.evaluate(PROBE)['hierarchy']['binding']['jd_tdb']
        advance('off')
        mcp.wait('('+PROBE+')()?.hierarchy?.binding.jd_tdb > '+str(before))
        assert mcp.evaluate("()=>document.querySelector('[role=alert]')?.textContent")== 'AUDIT initialization error'
        mcp.evaluate("()=>{("+PROPS+")().onError(null,'initialization');return true;}");mcp.wait(READY)
        passed('frame recovery cannot hide initialization failure')
        final=mcp.evaluate(PROBE)
        assert (final['geometries'],final['textures'],final['canvasCount'])==(initial['geometries'],initial['textures'],1)
        assert mcp.evaluate("()=>window.__recoveryOriginalRenderer===("+PROPS+")().sceneRef.current.renderer")
        assert mcp.evaluate('()=>window.__recoveryErrors')==[]
        report['resources']={'geometries':final['geometries'],'textures':final['textures'],'same_renderer':True}
        passed('no renderer rebuild, GPU resource growth or uncaught JavaScript errors')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--catalog',type=int,required=True)
    parser.add_argument('--report',type=Path);args=parser.parse_args()
    result=run(args.catalog)
    if args.report:args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
