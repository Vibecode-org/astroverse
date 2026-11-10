"""Real UI -> HTTP -> WebGL at the confirmed 2027 UTC boundaries."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from browser_mcp import MCP
from browser_physical_mcp import PROBE


def run(catalog):
    with MCP() as m:
        m.call('navigate_page',url='http://localhost:5173/',timeout=45000,
               initScript="window.__boundsErrors=[];addEventListener('error',e=>window.__boundsErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__boundsErrors.push(String(e.reason)));")
        assert m.evaluate("async()=>(await fetch('/api/health')).json()")['objects']==catalog
        contract=m.evaluate("async()=>(await fetch('/api/positions/v1/contract')).json()")
        assert contract['utc_interval'][1].startswith('2027-06-28')
        m.wait("document.querySelector('[role=status]').textContent.includes('Кадр UTC:')")
        m.click('Пауза')
        def date(value):
            m.evaluate("()=>{const el=document.querySelector('[aria-label=\"Дата UTC\"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,"+json.dumps(value)+");el.dispatchEvent(new Event('input',{bubbles:true}));}")
        stop=datetime.fromisoformat(contract['utc_interval'][1])
        for value in ['2027-01-01T00:00:00',(stop-timedelta(seconds=1)).isoformat()[:19]]:
            date(value)
            m.wait('('+PROBE+')()?.hierarchy?.binding.evaluated_at.startsWith('+json.dumps(value)+')')
            scene=m.evaluate(PROBE)
            wire=m.evaluate("async()=>(await fetch('/api/positions/v1/sectors/solar:verified?at='+encodeURIComponent("+json.dumps(value+'Z')+"))).json()")
            canonical={row['id']:row['position'] for row in wire['objects']}
            assert scene['hierarchy']['binding']['jd_tdb']==wire['jd_tdb']
            assert all(row['position']==canonical[row['id']] for row in scene['rows'])
            assert m.evaluate("()=>document.querySelector('.sidebar').textContent.includes('2027-06-28')")
        date(stop.isoformat()[:19])
        m.wait("document.querySelector('[role=status] [role=alert]')?.textContent.includes('UTC date outside')")
        assert m.evaluate(PROBE)['rows']==[]
        m.click('Сейчас');m.wait('('+PROBE+')()?.rows.length===2')
        final=m.evaluate(PROBE)
        assert (final['canvasCount'],final['geometries'],final['textures'])==(1,1,0)
        assert m.evaluate('()=>window.__boundsErrors')==[]
        return {'catalog':catalog,'checks':['2027-01-01 exact UTC/JD/centers','last supported UTC second',
            'exclusive upper bound clears scene','Now recovers without GPU growth'], 'utc_interval':contract['utc_interval']}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--catalog',type=int,required=True);p.add_argument('--report',type=Path)
    args=p.parse_args();result=run(args.catalog)
    if args.report:args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
