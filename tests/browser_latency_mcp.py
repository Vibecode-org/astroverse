"""Clock/HTTP starvation regression. Delays only isolated browser responses."""
import argparse
import json
from pathlib import Path
from browser_mcp import MCP
from browser_physical_mcp import PROBE

CONTROL="""const original=fetch.bind(window);let index=0;
window.__latencyCount=0;window.__latencyErrors=[];
addEventListener('error',e=>window.__latencyErrors.push(e.message));
addEventListener('unhandledrejection',e=>window.__latencyErrors.push(String(e.reason)));
window.fetch=async(...args)=>{
 const response=await original(...args);
 if(String(args[0]).includes('/api/positions/v1/')){
  window.__latencyCount++;
  await new Promise(resolve=>setTimeout(resolve,[250,400,200,300][index++%4]));
 }
 return response;
};"""


def run(catalog):
    with MCP() as m:
        m.call('navigate_page',url='http://localhost:5173/',timeout=45000,initScript=CONTROL)
        assert m.evaluate("async()=>(await fetch('/api/health')).json()")['objects']==catalog
        m.wait("document.querySelector('.physicalApp canvas')")
        samples=m.evaluate("""async()=>{
          const samples=[];
          for(let i=0;i<35;i++){
            await new Promise(resolve=>setTimeout(resolve,100));
            const state=(PROBE)();
            samples.push({rows:state?.rows.length||0,at:state?.hierarchy?.binding.evaluated_at||null,
             status:document.querySelector('[role=status]').textContent});
          }
          return samples;
        }""".replace('PROBE',PROBE))
        steady=samples[15:]
        assert sum(s['rows']>0 for s in steady)>=15,samples
        dates={s['at'] for s in steady if s['at']}
        assert len(dates)>=2,samples
        assert all('Кадр UTC: '+s['at'] in s['status'] and 'отставание' in s['status'] for s in steady if s['at'])
        m.click('Пауза');m.wait("document.querySelector('[role=status]')?.textContent.includes('Положения вычислены на этот момент')")
        paused=m.evaluate(PROBE)
        selected=m.evaluate("()=>document.querySelector('[role=status] div').textContent.split(' · ')[0]")
        assert m.evaluate("()=>Date.parse("+json.dumps(selected)+")")==m.evaluate("()=>Date.parse("+json.dumps(paused['hierarchy']['binding']['evaluated_at'])+")")
        m.click('+1 день');m.wait('('+PROBE+')()?.hierarchy?.binding.jd_tdb > '+str(paused['hierarchy']['binding']['jd_tdb']))
        final=m.evaluate(PROBE)
        assert (final['geometries'],final['textures'],final['canvasCount'])==(1,0,1)
        # Accelerated and reverse clocks still finish delayed selections. Use a
        # date away from interval boundaries, then restore real wall-clock Now.
        m.evaluate("""()=>{const el=document.querySelector('[aria-label="Дата UTC"]');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'2020-04-05T12:00:00');
          el.dispatchEvent(new Event('input',{bubbles:true}));
          const rate=document.querySelector('#time-rate');rate.value='86400';rate.dispatchEvent(new Event('change',{bubbles:true}));}
        """)
        m.click('Продолжить')
        directions=[]
        for reverse in [False,True]:
            if reverse:m.click('⟲')
            observations=m.evaluate("""async()=>{const out=[];for(let i=0;i<40;i++){
              await new Promise(resolve=>setTimeout(resolve,100));const s=(PROBE)();
              out.push({at:s?.hierarchy?.binding.evaluated_at,status:document.querySelector('[role=status]').textContent});
            }return out;}""".replace('PROBE',PROBE))
            steady_motion=observations[15:]
            dates_motion=[s['at'] for s in steady_motion if s.get('at')]
            assert len(dates_motion)>=20 and len(set(dates_motion))>=2,observations
            assert all(('Кадр UTC: '+s['at']) in s['status'] for s in steady_motion if s.get('at'))
            timestamps=m.evaluate('()=>'+json.dumps(dates_motion)+'.map(x=>Date.parse(x))')
            assert all((a>=b if reverse else a<=b) for a,b in zip(timestamps,timestamps[1:])),dates_motion
            directions.append({'reverse':reverse,'samples':len(dates_motion),'frames':len(set(dates_motion))})
        m.click('Сейчас');m.wait("document.querySelector('[role=status]')?.textContent.includes('Кадр UTC:')")
        assert m.evaluate("()=>document.querySelector('[role=status]').textContent.includes('Сейчас')")
        assert m.evaluate('()=>window.__latencyErrors')==[]
        return {'catalog':catalog,'steady_nonempty':sum(s['rows']>0 for s in steady),'steady_samples':len(steady),
                'distinct_frames':len(dates),'pause_exact':True,'manual_jump':True,
                'directions':directions,'requests':m.evaluate('()=>window.__latencyCount'),'resources':{'geometries':1,'textures':0}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--catalog',type=int,required=True);p.add_argument('--report',type=Path)
    args=p.parse_args();result=run(args.catalog)
    if args.report:args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
