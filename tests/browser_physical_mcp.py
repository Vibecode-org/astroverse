"""Real Chrome DevTools MCP: verified centers, bounded cards and scene lifetime."""
import argparse
import json
from pathlib import Path
import time
import tempfile

from browser_mcp import MCP

PROBE = """() => {
 const el=document.querySelector('.viewport');
 const key=Object.keys(el||{}).find(k=>k.startsWith('__reactFiber'));
 let fiber=key && el[key];
 while(fiber && !fiber.memoizedProps?.sceneRef) fiber=fiber.return;
 const state=fiber?.memoizedProps?.sceneRef.current;
 if(!state) return null;
 const layer=state.layer.inspect();
 return {frames:state.frames,canvasCount:document.querySelectorAll('canvas').length,
   camera:state.camera.position.toArray(),calls:state.renderer.info.render.calls,
   geometries:state.renderer.info.memory.geometries,textures:state.renderer.info.memory.textures,
   ...layer};
}"""


def run(catalog):
    report={'catalog':catalog,'checks':[]}
    def passed(name):
        report['checks'].append(name);print('PASS',name,flush=True)
    with MCP() as mcp:
        mcp.call('navigate_page',url='http://localhost:5173/',timeout=45000,
                 initScript="window.__physicalErrors=[];addEventListener('error',e=>window.__physicalErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__physicalErrors.push(String(e.reason)));")
        health=mcp.evaluate("async()=> (await fetch('/api/health')).json()")
        assert health['objects']==catalog,health
        mcp.wait("document.querySelector('.physicalApp canvas') && document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
        mcp.click('Пауза')
        mcp.wait("document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
        initial=mcp.evaluate(PROBE)
        assert initial['canvasCount']==1 and initial['frames']>0 and initial['calls']==1,initial
        assert {r['id'] for r in initial['rows']}=={'sun','earth','moon','mercury','venus'},initial
        report['initial']=initial
        passed('physical scene: all five centers near Earth, one draw call, one renderer')

        # Full-precision CPU coordinates agree with an independent HTTP read at
        # exactly the displayed UTC moment; astronomy itself has golden tests.
        consistency=mcp.evaluate("""async()=> {
          const at=document.querySelector('[role=status] div').textContent.split(' · ')[0];
          const response=await fetch('/api/positions/v1/sectors/solar:verified?at='+encodeURIComponent(at));
          return {at,body:await response.json()};
        }""")
        known={o['id']:o['position'] for o in consistency['body']['objects']}
        assert all(r['position']==known[r['id']] for r in initial['rows']),consistency
        passed('displayed UTC and Float64 geometric positions agree')
        mcp.click('Обзор системы')
        mcp.wait("document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
        overview=mcp.evaluate(PROBE)
        assert {r['id'] for r in overview['rows']}=={'sun','earth','moon','mercury','venus'},overview
        drawn={row['id']:overview['render'][i*3:i*3+3] for i,row in enumerate(overview['rows'])}
        assert [v for row in initial['rows'] for v in drawn[row['id']]]==initial['render'],(overview,initial)
        assert overview['frames']>=initial['frames'],overview
        mcp.click('Окрестность тела')
        mcp.wait("document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
        near=mcp.evaluate(PROBE)
        assert near['rows']==initial['rows'] and near['render']==initial['render'],near
        assert (near['geometries'],near['textures'])==(initial['geometries'],initial['textures']),near
        passed('overview/local view preserve all five resident centers and resources')

        mcp.click('Луна')
        mcp.wait("document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
        centered=mcp.evaluate(PROBE)
        assert next(r['position'] for r in centered['rows'] if r['id']=='moon')==known['moon'],centered
        assert centered['origin']==known['moon'],centered
        assert centered['frames']>=initial['frames'],centered
        passed('floating origin follows selected body without modifying physical positions')

        for label, oid in [('Меркурий','mercury'),('Венера','venus')]:
            mcp.click(label)
            mcp.wait("document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
            focused=mcp.evaluate(PROBE)
            assert focused['origin']==known[oid],focused
            assert {row['id'] for row in focused['rows']}==set(known),focused
            assert next(row['position'] for row in focused['rows'] if row['id']==oid)==known[oid],focused
            assert focused['canvasCount']==1 and focused['calls']==1,focused
            assert focused['geometries']==initial['geometries'],focused
            # Wheel input goes through OrbitControls; physical data is read only.
            mcp.evaluate("""()=>{const el=document.querySelector('.viewport canvas'),r=el.getBoundingClientRect();
              el.dispatchEvent(new WheelEvent('wheel',{deltaY:1000,bubbles:true,cancelable:true,
                clientX:r.left+r.width/2,clientY:r.top+r.height/2}));}""")
            mcp.wait("document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
            moved=mcp.evaluate(PROBE)
            assert moved['camera']!=focused['camera'],moved
            assert moved['rows']==focused['rows'] and moved['render']==focused['render'],moved
            mcp.click(label)
            mcp.wait("document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
            reset=mcp.evaluate(PROBE)
            assert reset['camera']==focused['camera'] and reset['rows']==focused['rows'],reset
        passed('Mercury/Venus selection, camera zoom and refocus preserve body centers and renderer')

        query='Звезда 000001' if catalog==100000 else 'proxima'
        mcp.evaluate("""() => { const el=document.querySelector('[aria-label="Поиск по всему каталогу"]');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,%s);
          el.dispatchEvent(new Event('input',{bubbles:true})); }""" % json.dumps(query))
        mcp.wait("Array.from(document.querySelectorAll('.objectRow')).some(x=>x.textContent.toLowerCase().includes("+json.dumps(query.lower())+"))")
        mcp.evaluate("()=>document.querySelector('.objectRow').click()")
        mcp.wait("document.querySelector('.infoPanel')?.textContent.includes('Координаты каталога:')")
        assert mcp.evaluate("()=>document.querySelector('.infoPanel').textContent.includes('Положение на выбранный момент неизвестно')")
        cards=mcp.evaluate("()=>Array.from(performance.getEntriesByType('resource')).filter(e=>e.name.includes('/api/spatial/v1/')).map(e=>({url:e.name,bytes:e.decodedBodySize,ms:e.duration}))")
        assert any('/sectors/' in r['url'] for r in cards),cards
        assert all(r['bytes']<=2*1024*1024 for r in cards),cards
        report['sector_requests']=cards
        passed('server search finds unloaded cards; paged sector read preserves unknown status')
        resources=mcp.evaluate("()=>performance.getEntriesByType('resource').filter(e=>e.name.includes('/api/')).map(e=>e.name)")
        assert not any('/api/objects?' in url or '/api/live-ephemeris' in url for url in resources),resources
        passed('no full JSON/v2 catalog and no legacy live-ephemeris request')

        # Date input is a user action. Invalid-time vectors are hidden by the
        # unit tests; avoid intentional HTTP 422 console errors in this smoke.
        mcp.evaluate("""()=>{const el=document.querySelector('[aria-label="Дата UTC"]');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'2020-04-05T12:00:00');
          el.dispatchEvent(new Event('input',{bubbles:true}));}""")
        mcp.wait("document.querySelector('[role=status]')?.textContent.includes('2020-04-05T12:00:00') && document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
        past=mcp.evaluate(PROBE)
        mcp.click('+1 день');mcp.wait("document.querySelector('[role=status]')?.textContent.includes('2020-04-06') && document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
        mcp.click('−1 день');mcp.wait("document.querySelector('[role=status]')?.textContent.includes('2020-04-05') && document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
        restored=mcp.evaluate(PROBE)
        assert restored['rows']==past['rows'],(restored,past)
        mcp.evaluate("""()=>{const el=document.querySelector('[aria-label="Поиск по всему каталогу"]');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'');
          el.dispatchEvent(new Event('input',{bubbles:true}));}""")
        mcp.wait("Array.from(document.querySelectorAll('.objectRow')).some(x=>x.textContent.includes('Меркурий'))")
        for label,oid in [('Меркурий','mercury'),('Венера','venus')]:
            mcp.click(label)
            mcp.wait("document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
            before=mcp.evaluate(PROBE)
            mcp.click('+1 день')
            mcp.wait("document.querySelector('[role=status]')?.textContent.includes('2020-04-06') && document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
            future=mcp.evaluate(PROBE)
            assert future['rows']!=before['rows'],(before,future)
            mcp.click('−1 день')
            mcp.wait("document.querySelector('[role=status]')?.textContent.includes('2020-04-05') && document.querySelector('[role=status]')?.textContent.includes('Положения вычислены')")
            back=mcp.evaluate(PROBE)
            assert back['rows']==before['rows'] and back['render']==before['render'],(back,before)
        passed('Mercury/Venus change with time and reverse return restores exact vectors')
        passed('date changes and reverse return restore exactly the same centers')
        registry=mcp.evaluate("""async()=>{
          const r=await fetch('/api/sources/v1/objects?limit=2'); const body=await r.json();
          const cached=await fetch('/api/sources/v1/objects?limit=2',{headers:{'If-None-Match':r.headers.get('etag')}});
          const next=await (await fetch('/api/sources/v1/objects?limit=2&offset=2&revision='+body.revision)).json();
          return {body,next,cached:cached.status};
        }""")
        assert registry['body']['version']=='sources/1' and registry['cached']==304,registry
        assert registry['body']['next_offset']==2 and len(registry['next']['objects'])==2,registry
        report['registry_revision']=registry['body']['revision']
        passed('bounded registry pages, model metadata, pinned revision and 304')
        dynamic=mcp.evaluate("""async()=>{
          const el=document.querySelector('.viewport'), key=Object.keys(el).find(k=>k.startsWith('__reactFiber'));
          let fiber=el[key];while(fiber&&!fiber.memoizedProps?.sceneRef)fiber=fiber.return;
          const state=fiber.memoizedProps.sceneRef.current, renderer=state.renderer;
          const at=document.querySelector('[role=status] div').textContent.split(' · ')[0];
          const real=await (await fetch('/api/positions/v1/sectors/solar:verified?at='+encodeURIComponent(at))).json();
          const bodies=(await (await fetch('/api/sources/v1/objects?limit=128')).json()).objects;
          const baseline={...renderer.info.memory};const samples=[];
          // Synthetic test-only CPU vectors. Never registered or published as real bodies.
          for(const count of [9,129,1,129,0,129,1,129,0,129]){
            const objects=Array.from({length:count},(_,i)=>({id:'synthetic-test-'+i,status:'computed',position:[i*1000,0,0]}));
            state.layer.update({...real,revision:'synthetic-test-only',hierarchy:undefined,coordinates:{...real.coordinates,source:'synthetic test data; not NASA',kernel_sha256:null,validation:null},objects},'synthetic-test-0',true);
            renderer.render(state.scene,state.camera);
            samples.push({...renderer.info.memory});
          }
          state.layer.update(real,'venus',false,null,bodies);renderer.render(state.scene,state.camera);
          return {baseline,samples,final:{...renderer.info.memory},sameRenderer:renderer===state.renderer,
            physicalRestored:state.layer.inspect().rows.every(r=>real.objects.some(o=>o.id===r.id&&JSON.stringify(o.position)===JSON.stringify(r.position)))};
        }""")
        assert dynamic['sameRenderer'] and dynamic['physicalRestored'],dynamic
        assert all(v==dynamic['baseline'] for v in dynamic['samples']+[dynamic['final']]),dynamic
        report['dynamic_resources']=dynamic
        passed('synthetic membership beyond five grows/reuses buffers without GPU resource growth')
        fixture=json.loads((Path(__file__).parent/'fixtures/physical_hierarchy_synthetic.json').read_text())
        hierarchy=mcp.evaluate("""async()=>{
          const fixture=FIXTURE;
          const el=document.querySelector('.viewport'),key=Object.keys(el).find(k=>k.startsWith('__reactFiber'));
          let fiber=el[key];while(fiber&&!fiber.memoizedProps?.sceneRef)fiber=fiber.return;
          const state=fiber.memoizedProps.sceneRef.current,renderer=state.renderer,geometry=state.scene.children.find(node=>node.isPoints).geometry;
          const at=document.querySelector('[role=status] div').textContent.split(' · ')[0];
          const real=await (await fetch('/api/positions/v1/sectors/solar:verified?at='+encodeURIComponent(at))).json();
          const bodies=(await (await fetch('/api/sources/v1/objects?limit=128')).json()).objects;
          const initial=structuredClone(fixture.frame),moved=structuredClone(fixture.frame);
          for(const [id,placement] of Object.entries(fixture.repartition))Object.assign(moved.hierarchy.bodies.find(b=>b.id===id),placement);
          state.layer.update(initial,'a',true);renderer.render(state.scene,state.camera);
          const before=state.layer.inspect(),memory={...renderer.info.memory};
          let preserved=true,rejected=false;
          for(let i=0;i<20;i++){
            state.layer.update(i%2?initial:moved,'a',true);renderer.render(state.scene,state.camera);
            const next=state.layer.inspect();
            preserved&&=JSON.stringify(next.rows)===JSON.stringify(before.rows)&&JSON.stringify(next.render)===JSON.stringify(before.render);
          }
          try {state.layer.update({...moved,jd_tdb:moved.jd_tdb+1},'a',true);}catch{rejected=true;}
          const after={...renderer.info.memory};
          state.layer.update(real,'venus',false,null,bodies);renderer.render(state.scene,state.camera);
          return {before,memory,after,preserved,rejected,sameRenderer:renderer===state.renderer,
            sameGeometry:geometry===state.scene.children.find(node=>node.isPoints).geometry,realHierarchy:state.layer.inspect().hierarchy};
        }""".replace('FIXTURE',json.dumps(fixture)))
        assert hierarchy['preserved'] and hierarchy['rejected'] and hierarchy['sameRenderer'] and hierarchy['sameGeometry'],hierarchy
        assert hierarchy['memory']==hierarchy['after'],hierarchy
        assert hierarchy['realHierarchy']['binding']['revision']==consistency['body']['revision'],hierarchy
        report['hierarchy']=hierarchy
        passed('hierarchy cross-sector repartition preserves centers, render positions and GPU resources; stale epoch rejected')
        errors=mcp.evaluate('()=>window.__physicalErrors')
        console=mcp.call('list_console_messages',types=['error','warn'])
        assert not errors,errors
        assert 'type=error' not in console,console
        report['final']=restored
        report['api_resources']=resources
        report['console']=console
        report['screenshot']=str((Path(tempfile.gettempdir()) / f'astroverse-registry-physical-{catalog}.png').resolve())
        mcp.call('take_screenshot', filePath=report['screenshot'])
        passed('no uncaught JavaScript errors or console errors')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--catalog',type=int,required=True)
    parser.add_argument('--report',type=Path);args=parser.parse_args()
    report=run(args.catalog)
    if args.report: args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
