"""Real WebGL depth/picking and OrbitControls pole handoff regressions.

Synthetic marker pairs exist only in this isolated test page. readPixels checks
visibility; no mocks of shaders/renderer. Exact pole is a controlled edge fixture,
then mode handoff and orbit dragging use actual UI/native input.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
from browser_navigation_mcp import browser, READ
from browser_sectors_mcp import CAPTURE


DEPTH = r"""()=>{
 const s=window.__sectorStage,c=s.camera,r=s.renderer,gl=r.getContext(),results=[];
 const ref={position:[0,0,0],path:null,offset:[0,0,0],cameraOffset:[0,0,0]};
 for(const distance of [1e7,1e9,1e12])for(const reversed of [false,true])for(const detail of [false,true]){
  const objects=[{id:'synthetic-depth-near',status:'computed',position:[0,distance,0]},
    {id:'synthetic-depth-far',status:'computed',position:[0,2*distance,0]}];
  if(reversed)objects.reverse();
  const frame={...s.props.frame,hierarchy:undefined,objects,
    coordinates:{...s.props.frame.coordinates,source:'Synthetic depth test, not NASA'}};
  const before=JSON.stringify(objects);
  s.layer.update(frame,'missing',true,null,[{id:'synthetic-depth-near',color:'#ff0000'},
    {id:'synthetic-depth-far',color:'#0000ff'}],detail?'synthetic-depth-near':null,ref);
  c.position.set(0,0,0);c.quaternion.identity();c.up.set(0,1,0);c.updateMatrixWorld();s.layer.tick(c);
  r.render(s.scene,c);const pixel=new Uint8Array(4);
  gl.readPixels(Math.floor(gl.drawingBufferWidth/2),Math.floor(gl.drawingBufferHeight/2),1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);
  const rect=r.domElement.getBoundingClientRect();
  results.push({distance_km:distance,reversed,detail,pixel:[...pixel],
    picked:s.layer.pick(c,rect.width/2,rect.height/2,rect.width,rect.height),centers_unchanged:JSON.stringify(objects)===before});
 }
 return {results,logarithmic_depth:r.capabilities.logarithmicDepthBuffer,depth_bits:gl.getParameter(gl.DEPTH_BITS),
   near:c.near,far:c.far,gl_error:gl.getError(),renderer:gl.getParameter(gl.getExtension('WEBGL_debug_renderer_info').UNMASKED_RENDERER_WEBGL)};
}"""


def run():
    report={'complete':False,'checks':[],'tolerances':{'handoff_eye_km':1e-6,'handoff_quaternion_components':1e-12}}
    with browser() as (m,debug):
        def load():
            m.call('navigate_page',url='http://localhost:5173/',timeout=45000,
                   initScript="window.__depthErrors=[];addEventListener('error',e=>window.__depthErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__depthErrors.push(String(e.reason)));")
            assert m.evaluate("async()=>(await fetch('/api/health')).json()")['objects']==3471
            m.wait("document.querySelector('canvas') && document.querySelector('.objectRow')")
            m.click('Пауза');m.evaluate(CAPTURE)
            m.wait('window.__sectorStage.props.frame?.objects.length>0')
        load();report['depth']=m.evaluate(DEPTH)
        assert report['depth']['logarithmic_depth'] and report['depth']['gl_error']==0
        for result in report['depth']['results']:
            assert result['pixel']==[255,0,0,255],result
            assert result['picked']=='synthetic-depth-near',result
            assert result['centers_unchanged']
        assert m.evaluate('()=>window.__depthErrors')==[]
        report['checks'].append('12 WebGL pixel + picking cases: both orders, L0/L1, 1e7/1e9/1e12 km')
        print('PASS',report['checks'][-1],flush=True)
        load();m.click('Земля');m.wait('window.__sectorStage.props.frame?.objects.length>0')
        report['handoff']=[]
        for sign in [1,-1]:
            m.click('Свободный полёт')
            # Deliberate exact pole; native key duration cannot reliably land on
            # pi/2 at a discrete RAF. Position is never assigned in this test.
            m.evaluate('()=>{const c=window.__sectorStage.camera;c.quaternion.setFromAxisAngle(c.position.clone().set(1,0,0),'+str(sign*math.pi/2)+');return true;}')
            before=m.evaluate(READ);m.click('Завершить полёт')
            m.evaluate('async()=>{await new Promise(r=>setTimeout(r,1000));return true;}')
            after=m.evaluate(READ)
            eye_error=math.dist(before['eye'],after['eye'])
            quaternion_error=max(abs(a-b) for a,b in zip(before['quaternion'],after['quaternion']))
            assert eye_error<=1e-6 and quaternion_error<=1e-12,(before,after)
            assert before['layer']['rows']==after['layer']['rows']
            m.call('click',uid=m.uid('Проверенные геометрические центры','main'))
            m.evaluate('async()=>{await new Promise(r=>setTimeout(r,200));return true;}')
            assert math.dist(before['eye'],m.evaluate(READ)['eye'])<=1e-6
            point=m.evaluate('()=>{const r=document.querySelector(".viewport").getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];}')
            subprocess.run(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,'Drag',json.dumps(point)],check=True,timeout=10,capture_output=True,text=True)
            moved=m.evaluate(READ);assert moved['quaternion']!=after['quaternion']
            assert moved['renderer'] and moved['controls']
            report['handoff'].append({'pole':sign,'eye_error_km':eye_error,'quaternion_component_error':quaternion_error,'native_orbit_resumed':True})
        assert m.evaluate('()=>window.__depthErrors')==[]
        report['checks'].append('both exact poles preserve physical eye/orientation through exit/idle; native drag resumes orbit')
        print('PASS',report['checks'][-1],flush=True)
        report['complete']=True
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    result=run();args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
