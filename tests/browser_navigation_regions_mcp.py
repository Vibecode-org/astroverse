"""Real UI regressions: distant resident centers and zoomed Mercury flight handoff."""
import argparse
import json
import math
from pathlib import Path
import subprocess

from browser_navigation_mcp import browser, READ
from browser_sectors_mcp import CAPTURE, LISTENERS


def run(url):
    report = {'complete': False, 'checks': [], 'cycles': [], 'tolerance_km': 1e-6,
              'environment': 'Chrome / SwiftShader; functional, no fps claim'}
    with browser() as (m, debug):
        m.call('navigate_page', url=url+'/', timeout=45000, initScript=LISTENERS)
        assert m.evaluate("async()=>(await fetch('/api/health')).json()")['objects'] == 3471
        m.wait("document.querySelector('.objectRow') && document.querySelector('canvas')")
        m.click('Пауза'); m.click('Земля'); m.evaluate(CAPTURE)
        m.wait('window.__sectorStage.layer.inspect().rows.length===5 && window.__sectorStage.displayedAt')
        def read(): return m.evaluate(READ)
        def settle(): m.evaluate('async()=>{await new Promise(r=>setTimeout(r,800));return true;}')
        def native(code, value):
            subprocess.run(['node',str(Path(__file__).with_name('chrome_hold.mjs')),debug,code,str(value)],
                           check=True, timeout=15, capture_output=True, text=True)
        earth = read()
        expected = m.evaluate("async()=>{const at=window.__sectorStage.displayedAt;return (await (await fetch('/api/positions/v1/sectors/solar:verified?at='+encodeURIComponent(at))).json()).objects;}")
        positions = {r['id']:r['position'] for r in expected if r['position']}
        assert {r['id']:r['position'] for r in earth['layer']['rows']} == positions
        assert m.evaluate('()=>window.__sectorStage.renderer.info.render.points') == 5
        report['earth'] = {'submitted':5,'resident_ids':list(positions)}
        report['checks'].append('Earth local view submits all five computed centers with exact HTTP vectors')
        for cycle in range(3):
            m.click('Меркурий');settle()
            m.wait('window.__sectorStage.displayedAt && window.__sectorStage.layer.inspect().rows.length===5')
            # Trusted wheel events through OrbitControls, no camera assignment.
            point=m.evaluate('()=>{const r=document.querySelector(".viewport").getBoundingClientRect();return [r.left+r.width*.6,r.top+r.height*.5];}')
            wheels=0
            while m.evaluate('()=>window.__sectorStage.camera.position.distanceTo(window.__sectorStage.controls.target)*1e5') < 2e8:
                native('Wheel',json.dumps(point));wheels+=1;settle()
                assert wheels<=20
            before=read()
            radius=m.evaluate('()=>window.__sectorStage.neighborhood.radius')
            m.click('Свободный полёт');settle()
            after=read()
            assert after['flight']['enabled'] and not after['controls']
            assert math.dist(before['eye'],after['eye'])<=1e-6
            assert {r['id']:r['position'] for r in after['layer']['rows']} == positions
            assert m.evaluate('()=>window.__sectorStage.neighborhood.radius')>=radius
            assert 'Положение не загружено' not in m.evaluate('()=>document.querySelector(".infoPanel").textContent')
            native('ArrowLeft',250);native('ArrowUp',200);native('KeyQ',200)
            a=read();native('KeyW',350);b=read()
            assert math.dist(a['eye'],b['eye'])>1000
            assert b['layer']['rows']==after['layer']['rows']
            m.click('Завершить полёт');settle();end=read()
            assert math.dist(b['eye'],end['eye'])<=1e-6
            m.click('Свободный полёт');settle()
            assert math.dist(end['eye'],read()['eye'])<=1e-6
            m.click('Наблюдать Меркурий');settle();focused=read()
            assert not focused['flight']['enabled']
            assert focused['layer']['origin']==positions['mercury']
            assert focused['layer']['rows']==earth['layer']['rows']
            assert focused['renderer'] and focused['memory']==earth['memory']
            assert focused['listeners']==earth['listeners']
            report['cycles'].append({'wheels':wheels,'handoff_radius_km':radius,
                'handoff_jump_km':math.dist(before['eye'],after['eye']),
                'travel_km':math.dist(a['eye'],b['eye']),'rebases':b['rebases']})
        report['checks'].append('Three trusted Mercury zoom/flight/rotation/motion/exit/reentry/refocus cycles preserve centers and resources')
        report['complete']=True
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://localhost:5173');p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    result=run(a.url);a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
