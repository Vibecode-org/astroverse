"""Native HTTP + real WebGL marker selection, hysteresis and LOD-only request stability."""
import argparse
import json
from pathlib import Path
from browser_mcp import MCP
from browser_physical_mcp import PROBE
from browser_sectors_mcp import CAPTURE

def run(catalog):
    with MCP() as m:
        m.call('navigate_page',url='http://localhost:5173/',timeout=45000)
        assert m.evaluate("async()=>(await fetch('/api/health')).json()")['objects']==catalog
        m.wait('('+PROBE+')()?.rows.length===5')
        m.click('Пауза');m.evaluate(CAPTURE)
        m.wait("document.querySelector('[role=status]').textContent.includes('Положения вычислены на этот момент')")
        def zoom(z):
            m.evaluate('()=>{const s=window.__sectorStage;s.camera.position.set(0,0,'+str(z)+');s.controls.target.set(0,0,0);s.controls.update();return true;}')
            m.evaluate('async()=>{await new Promise(r=>setTimeout(r,700));return true;}')
            return m.evaluate('()=>window.__sectorStage.layer.stats()')
        near=zoom(19);assert near['detailed']>=1
        far=zoom(35);assert far['detailed']==0
        zoom(25)
        start=m.evaluate('()=>window.__sectorManager.inspect().requests')
        for z in [24.9,25.1]*4:assert zoom(z)['detailed']==0
        assert m.evaluate('()=>window.__sectorManager.inspect().requests')==start
        before=m.evaluate(PROBE)
        def click_center():
            m.evaluate('()=>{const el=document.querySelector(".viewport"),r=el.getBoundingClientRect();el.dispatchEvent(new MouseEvent("click",{bubbles:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}));return true;}')
            m.wait('document.querySelector(".infoPanel h1")?.textContent==="Земля"')
        # Pointer drag followed by browser click must preserve selection/camera.
        m.evaluate('''()=>{const el=document.querySelector('.viewport'),r=el.getBoundingClientRect();
          const x=r.left+r.width/2,y=r.top+r.height/2;
          el.dispatchEvent(new PointerEvent('pointerdown',{clientX:x-30,clientY:y,bubbles:true,isPrimary:true}));
          el.dispatchEvent(new PointerEvent('pointermove',{clientX:x,clientY:y,bubbles:true}));
          el.dispatchEvent(new PointerEvent('pointerup',{clientX:x,clientY:y,bubbles:true}));
          el.dispatchEvent(new MouseEvent('click',{clientX:x,clientY:y,bubbles:true}));return true;}''')
        assert m.evaluate("()=>document.querySelector('.infoPanel')===null")
        # Match Retina framebuffer while keeping CSS picking coordinates.
        m.evaluate('()=>{window.__sectorStage.renderer.setPixelRatio(2);return true;}')
        zoom(25)
        assert m.evaluate('()=>window.__sectorStage.scene.children.find(x=>x.isPoints).material.uniforms.markerPixelRatio.value')==2
        m.evaluate("()=>{const el=document.querySelector('.viewport');el.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,isPrimary:true}));return true;}")
        click_center();m.wait('window.__sectorStage.layer.stats().detailed>=1')
        assert m.evaluate(PROBE)['rows']==before['rows']
        click_center()
        assert m.evaluate('()=>window.__sectorStage.renderer.domElement===document.querySelector("canvas")')
        return {'catalog':catalog,'checks':5,'requests_during_lod_only':0,'near':near,'far':far,'final':m.evaluate('()=>window.__sectorStage.layer.stats()')}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--catalog',type=int,default=3471);p.add_argument('--report',type=Path);a=p.parse_args()
    result=run(a.catalog)
    if a.report:a.report.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
