/** Browser-only, isolated temporal fixture benchmark. Bundle with esbuild.
 * Uses the production sector manager, physical layer and a real WebGLRenderer.
 * startTemporalBenchmark returns immediately; poll temporalBenchmarkStatus.
 * Bounded metric reservoirs are aggregate evidence, not browser/GPU RSS.
 */
import * as THREE from '../frontend/node_modules/three/build/three.module.js';
import { PhysicalSectorManager } from '../frontend/src/physical/sectorManager.js';
import { createPhysicalLayer } from '../frontend/src/physical/physicalLayer.js';

const assert=(test,message)=>{if(!test)throw new Error(message);};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const instant=Date.parse('2026-01-01T00:00:00Z');
const SAMPLE_LIMIT=20000;
class Distribution {
  constructor(){this.values=[];this.count=0;this.sum=0;this.max=0;this.over50=0;}
  add(value){if(!Number.isFinite(value))return;this.count++;this.sum+=value;this.max=Math.max(this.max,value);if(value>50)this.over50++;
    if(this.values.length<SAMPLE_LIMIT)this.values.push(value);else this.values[(this.count-1)%SAMPLE_LIMIT]=value;}
  report(){const a=[...this.values].sort((x,y)=>x-y);return {count:this.count,retained:a.length,
    mean:this.count?this.sum/this.count:null,p50:a.length?a[Math.floor((a.length-1)*.5)]:null,
    p95:a.length?a[Math.floor((a.length-1)*.95)]:null,p99:a.length?a[Math.floor((a.length-1)*.99)]:null,
    max:this.max,over50:this.over50};}
}
function heap(){return performance.memory?{used:performance.memory.usedJSHeapSize,total:performance.memory.totalJSHeapSize,limit:performance.memory.jsHeapSizeLimit}:null;}
function resources(renderer){return {geometries:renderer.info.memory.geometries,textures:renderer.info.memory.textures,
  programs:renderer.info.programs?.length??null,calls:renderer.info.render.calls,points:renderer.info.render.points};}

export async function runTemporalBenchmark(options={}) {
  const functionStarted=performance.now();
  const {count=100000,seconds=120,cycles=3,root='/api/positions/v1/'}=options;
  assert(Number.isSafeInteger(count)&&count>0,'Invalid count');
  assert(Number.isFinite(seconds)&&seconds>=0&&seconds<=3600,'Invalid duration');
  assert(Number.isSafeInteger(cycles)&&cycles>=1&&cycles<=20,'Invalid cycles');
  const status=window.temporalBenchmarkStatus={running:true,complete:false,phase:'initializing',accepted:0,seconds:0};
  const result={complete:false,count,seconds_requested:seconds,cycles,checks:{},cases:[],cycles_resources:[],metrics:{},
    method:'Actual production manager/layer + WebGLRenderer. Direct manager stress; React clock coalescing separately unit-tested. RAF is browser scheduling, not monitor/GPU completion. CPU includes explicit oracle validation. All-run metrics preserve startup/disposal outliers; transition_* metrics cover only the sustained phase. Bounded last 20000 samples per metric; no full graph history.',
    memory_scope:'performance.memory is whole-tab JS heap (if available), not component memory or browser RSS; renderer.info counts resources, not driver GPU bytes.',
    heap:{baseline:heap(),peak_used:0,late:null,window_ms:10000,window_limit:360,windows:[]},renderer:null,error:null};
  window.temporalBenchmarkResult=result;
  let sustainedActive=false,sustainedStart=Infinity,sustainedEnd=-Infinity;
  const stats=new Map(),record=(name,value)=>{
    if(!stats.has(name))stats.set(name,new Distribution());stats.get(name).add(value);
    if(sustainedActive&&(name==='frame_cpu_ms'||name==='accepted_frame_ms'))record('transition_'+name,value);
  };
  for(const name of ['transition_raf_interval_ms','transition_frame_cpu_ms','transition_longtask_ms','transition_accepted_frame_ms'])
    stats.set(name,new Distribution());
  let renderer,layer,manager,raf,observer,lastRAF=null,lastHeap=0,stopped=false,currentFrame=null;
  const sampleHeap=()=>{
    const sample=heap();if(!sample)return;
    const elapsed=performance.now()-functionStarted,index=Math.min(359,Math.floor(elapsed/10000));
    let window=result.heap.windows.at(-1);
    if(!window||window.index!==index){window={index,from_s:elapsed/1000,to_s:elapsed/1000,samples:0,
      transition_samples:0,first:sample.used,last:sample.used,min:sample.used,max:sample.used};result.heap.windows.push(window);}
    window.to_s=elapsed/1000;window.samples++;if(sustainedActive)window.transition_samples++;
    window.last=sample.used;window.min=Math.min(window.min,sample.used);window.max=Math.max(window.max,sample.used);
    result.heap.peak_used=Math.max(result.heap.peak_used,sample.used);result.heap.late=sample;
    if(elapsed>=3600000)result.heap.final_window_merges_overflow=true;
  };
  const recordLongTasks=entries=>{for(const entry of entries){
    record('longtask_ms',entry.duration);
    // Observer callbacks may arrive after the phase ended. Classify by the
    // entry's start timestamp, independently of callback timing/status labels.
    if(entry.startTime>=sustainedStart&&entry.startTime<sustainedEnd)record('transition_longtask_ms',entry.duration);
  }};
  const endSustained=()=>{if(sustainedActive){sustainedActive=false;sustainedEnd=performance.now();}};
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(55,960/640,.00001,1e12);
  camera.position.set(0,30,50);camera.lookAt(0,0,0);
  const canvas=document.createElement('canvas');canvas.style.cssText='position:fixed;inset:0;width:960px;height:640px;z-index:999999;background:#02050a';
  document.body.appendChild(canvas);
  const report=()=>{for(const [key,value] of stats)result.metrics[key]=value.report();result.manager=manager?.inspect()??null;
    result.layer=layer?.timing()??null;result.renderer=renderer?resources(renderer):null;result.heap.late=heap();};
  sampleHeap();
  try {
    const health=await (await fetch('/api/health')).json();result.health=health;
    assert(health.synthetic===true&&health.objects===count,'Requires matching isolated temporal synthetic fixture');
    renderer=new THREE.WebGLRenderer({canvas,antialias:false,logarithmicDepthBuffer:true});renderer.setSize(960,640);renderer.setPixelRatio(1);
    const gl=renderer.getContext(),debug=gl.getExtension('WEBGL_debug_renderer_info');
    result.webgl={vendor:debug?gl.getParameter(debug.UNMASKED_VENDOR_WEBGL):null,renderer:debug?gl.getParameter(debug.UNMASKED_RENDERER_WEBGL):null};
    manager=new PhysicalSectorManager({root,onRequest:event=>record('http_elapsed_ms',event.ms)});
    manager.onPhase=event=>record(event.kind+'_ms',event.ms);
    layer=createPhysicalLayer(scene);
    if(globalThis.PerformanceObserver) {
      try {observer=new PerformanceObserver(list=>recordLongTasks(list.getEntries()));observer.observe({type:'longtask',buffered:false});}catch{}
    }
    result.longtask_observer_available=!!observer;
    const animate=now=>{
      if(stopped)return;
      raf=requestAnimationFrame(animate);
      if(lastRAF!==null){record('raf_interval_ms',now-lastRAF);
        if(sustainedActive&&lastRAF>=sustainedStart)record('transition_raf_interval_ms',now-lastRAF);}
      lastRAF=now;
      const begin=performance.now();layer.tick(camera,1,640);record('lod_cpu_ms',performance.now()-begin);
      const renderStart=performance.now();renderer.render(scene,camera);record('render_submission_cpu_ms',performance.now()-renderStart);
      record('frame_cpu_ms',performance.now()-begin);
      if(currentFrame&&result.first_usable_scene_ms===undefined)result.first_usable_scene_ms=performance.now()-functionStarted;
      if(now-lastHeap>500){lastHeap=now;sampleHeap();}
    };
    raf=requestAnimationFrame(animate);

    // Fixture geometry and oracle are specified below after provider agreement.
    const profile=temporalProfile(count);
    const validate=frame=>{
      const begin=performance.now();
      assert(frame.version==='positions/1'&&frame.coordinates.representation==='simulation_position','Mixed coordinate contract');
      assert(frame.revision===frame.coordinates.revision&&frame.registry_revision,'Missing revision binding');
      const ms=Date.parse(frame.evaluated_at);assert(Number.isFinite(ms),'Missing accepted UTC');
      // Independent coarse UTC->TDB sanity bound: TT is UTC+69.184s here,
      // while |TDB-TT| remains below 2ms. Numeric affine oracle uses declared JD.
      assert(Math.abs(frame.jd_tdb-(ms/86400000+2440587.5+69.184/86400))<3e-8,'JD does not match accepted UTC');
      const ids=new Set();
      for(const row of frame.objects){assert(!ids.has(row.id),'Duplicate body');ids.add(row.id);
        const expected=profile.position(row.id,frame.jd_tdb);
        if(expected===null){assert(row.status==='unknown'&&row.position===null,'Unknown body acquired a position');continue;}
        assert(row.status==='computed'&&Array.isArray(row.position)&&row.position.length===3,'Invalid computed fixture row');
        for(let axis=0;axis<3;axis++)assert(Math.abs(row.position[axis]-expected[axis])<=1e-6,'Wrong requested-time center: '+row.id);
      }
      record('oracle_cpu_ms',performance.now()-begin);return ids;
    };
    const apply=frame=>{
      validate(frame);const begin=performance.now();
      layer.update(frame,frame.objects[0]?.id??profile.anchor,true);
      record('apply_cpu_ms',performance.now()-begin);currentFrame=frame;status.accepted++;
      assert(layer.timing().slots===frame.objects.filter(row=>row.status==='computed').length,'Partial scene publication');
      const budget=manager.inspect();
      assert(budget.peakObjects<=4096&&budget.peakActive<=4&&budget.peakQueue<=128,'Manager object/transport budget exceeded');
      assert(budget.peakSerialized<=4*1024*1024&&budget.peakDecoded<=32*1024*1024,'Manager byte budget exceeded');
    };
    const select=async(name,ms=instant,{retainPrevious=false,context='explicit'}={})=>{
      status.phase=name;const begin=performance.now();
      const frame=await manager.load({milliseconds:ms,neighborhood:profile.areas[name],anchor:profile.anchor,context,retainPrevious});
      assert(Date.parse(frame.evaluated_at)===ms,'Accepted frame belongs to wrong selection time');
      const expected=profile.members(name);
      assert(frame.objects.length===expected.size&&frame.objects.every(row=>expected.has(row.id)),'Candidate membership omitted or substituted bodies: '+name);
      record('selection_elapsed_ms',performance.now()-begin);apply(frame);
      record('accepted_frame_ms',performance.now()-begin);return frame;
    };
    const inspect=()=>{
      renderer.render(scene,camera);const snapshot=layer.inspect();camera.updateMatrixWorld();
      const frustum=new THREE.Frustum().setFromProjectionMatrix(new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse));
      const vector=new THREE.Vector3();let inside=0;
      for(let i=0;i<snapshot.rows.length;i++)if(frustum.containsPoint(vector.fromArray(snapshot.render,i*3)))inside++;
      return {resident:manager.inspect().residentObjects,computed:snapshot.rows.length,submitted:renderer.info.render.points,
        in_frustum:inside,layer:layer.timing(),resources:resources(renderer)};
    };
    for(let cycle=0;cycle<cycles;cycle++) {
      const sparse=await select('sparse',instant+cycle*1000);assert(sparse.objects.length===profile.sparseCount,'Sparse membership wrong');
      result.cases.push({cycle,name:'sparse',...inspect()});
      const dense=await select('dense16',instant+cycle*1000);assert(dense.objects.length===2048,'Dense16 membership wrong');
      result.cases.push({cycle,name:'dense16',...inspect()});
      try {await select('overflow');throw new Error('Expected density overflow');}
      catch(error){assert(error.permanent===true&&error.message.includes('413')||error.permanent===true&&/budget|limit|density|плот|бюдж/i.test(error.message),'Unexpected overflow failure: '+error.message);}
      layer.update(null);currentFrame=null;assert(manager.inspect().objects===0,'Failed selection retained old residency');
      const empty=await select('empty');assert(empty.objects.length===0,'Empty region returned bodies');
      result.cases.push({cycle,name:'empty',...inspect()});
      result.checks.sparse_dense_empty_density_budget=true;
    }
    // Abort while nearby or sector reads are pending; only latest context may publish.
    status.phase='rapid_churn';const churn=[];
    for(let i=0;i<12;i++) {
      const name=i%2?'dense16':'sparse';
      const pending=manager.load({milliseconds:instant+(i%2?-1:1)*i*1000,neighborhood:profile.areas[name],anchor:profile.anchor,context:'churn-'+i})
        .then(frame=>({frame}),error=>({error}));
      churn.push(pending);
      if(i%3===0)await wait(1);
    }
    const outcomes=await Promise.all(churn);
    for(const outcome of outcomes.slice(0,-1))if(outcome.error)assert(outcome.error.name==='AbortError','Unexpected churn error');
    assert(outcomes.at(-1).frame,'Latest churn selection did not finish');apply(outcomes.at(-1).frame);
    assert(Date.parse(outcomes.at(-1).frame.evaluated_at)===instant-11000,'Late forward frame replaced reverse selection');
    result.churn={attempts:churn.length,cancelled:outcomes.filter(x=>x.error?.name==='AbortError').length};
    result.checks.rapid_context_replacement=true;

    status.phase='sustained_transitions';const started=performance.now();let iteration=0;
    sustainedStart=started;sustainedEnd=Infinity;sustainedActive=true;
    while(performance.now()-started<seconds*1000) {
      const phase=iteration%8,name=phase<3?'dense16':phase<5?'sparse':phase===5?'empty':'dense16';
      const ms=instant+(phase<4?1:-1)*iteration*10000;
      await select(name,ms,{retainPrevious:phase!==0,context:'phase-'+Math.floor(iteration/8)});
      // Keep deliberate idle time for RAF; no artificial solver pacing claim.
      await wait(150);iteration++;status.seconds=(performance.now()-started)/1000;
      if(iteration%10===0)report();
    }
    endSustained();sampleHeap();
    result.sustained={iterations:iteration,elapsed_seconds:(sustainedEnd-started)/1000,
      from_ms:sustainedStart-functionStarted,to_ms:sustainedEnd-functionStarted,
      classification:'CPU/accepted frames while sustained flag active; RAF intervals wholly inside phase; long tasks whose start timestamp is inside phase. All-run metrics retain every sample.'};
    result.checks.requested_time_oracle_all_accepted=true;
    result.before_disposal=inspect();
    // Recreate only the layer, retaining the one renderer/context throughout.
    for(let cycle=0;cycle<cycles;cycle++) {
      manager.cancel();currentFrame=null;layer.dispose();renderer.render(scene,camera);renderer.renderLists.dispose();
      const disposed=resources(renderer);assert(disposed.geometries===0&&disposed.textures===0,'Disposed layer leaked GPU resources');
      layer=createPhysicalLayer(scene);await select('dense16',instant+cycle*1000);
      const recreated=inspect();assert(recreated.resources.geometries===1&&recreated.resources.textures===0,'Layer recreation accumulated GPU resources');
      result.cycles_resources.push({cycle,disposed,recreated:recreated.resources,buffer_bytes:layer.timing().bufferBytes});
    }
    result.checks.disposal_recreation_resources=true;
    if(observer)recordLongTasks(observer.takeRecords());sampleHeap();report();result.complete=true;status.complete=true;
  } catch(error) {endSustained();result.error=String(error.stack||error);status.error=error.message;report();throw error;}
  finally {
    endSustained();stopped=true;cancelAnimationFrame(raf);
    if(observer)recordLongTasks(observer.takeRecords());observer?.disconnect();manager?.cancel();currentFrame=null;
    layer?.dispose();if(renderer){renderer.render(scene,camera);result.after_disposal=resources(renderer);renderer.dispose();renderer.forceContextLoss();}
    canvas.remove();status.running=false;sampleHeap();
    for(const [key,value] of stats)result.metrics[key]=value.report();
  }
  return result;
}

// Replaced with the explicit affine fixture contract once the data owner lands it.
function temporalProfile(count) {
  const neighborhood=(offset,radius=100000)=>({origin:[0,0,0],offset,radius});
  return {anchor:'synthetic-0000000',sparseCount:Math.min(128,Math.max(0,count-16*128)),
    areas:{sparse:neighborhood([1e6,0,0]),dense16:neighborhood([0,0,0]),
      empty:neighborhood([0,1e9,0]),overflow:neighborhood([0,0,0],1e12)},
    members(name){const start=name==='sparse'?2048:0,end=name==='sparse'?Math.min(count,2176):name==='dense16'?Math.min(count,2048):0;
      return new Set(Array.from({length:Math.max(0,end-start)},(_,i)=>'synthetic-'+String(start+i).padStart(7,'0')));},
    position(id,jd){
      assert(/^synthetic-\d{7}$/.test(id),'Invalid synthetic ID');const n=Number(id.slice(10));
      assert(n>=0&&n<count,'ID outside fixture');const sector=Math.floor(n/128),local=n%128;
      if(local===127)return null;
      const days=jd-2461041.5;
      return [(sector<16?0:(sector-15)*1e6)+(local-63.5)*1000+(sector%2===0?100:-100)*days,
        (sector%3-1)*10*days,(local%8-3.5)*1000];
    }};
}

window.runTemporalBenchmark=runTemporalBenchmark;
window.startTemporalBenchmark=options=>{
  assert(!window.temporalBenchmarkStatus?.running,'Benchmark is already running');
  window.temporalBenchmarkStatus={running:true,complete:false,phase:'starting'};
  runTemporalBenchmark(options).catch(()=>{});
  return {started:true};
};
