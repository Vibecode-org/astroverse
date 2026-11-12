"""Assess raw or consolidated clean-window reports without modifying evidence."""
import json
from pathlib import Path


FRAME_P95_MS = 16.8  # User-approved 2026-11-12; original evidence remains unchanged.
FLOAT_MS_EPSILON = 1e-6  # Only IEEE subtraction noise, not a timing allowance.

def assess(report):
    bounds={'camera_cpu':(1,8),'lod_cpu':(1,8),'preparation_slice_cpu':(4,16),
            'merge_slice_cpu':(4,16),'validation_cpu':(4,16),'prepare_prelude_cpu':(4,16),
            'commit_cpu':(16,50),'picking_cpu':(16,50),'frame':(FRAME_P95_MS,33.334)}
    result={}
    for key,(p95,maximum) in bounds.items():
        values=[(name,w['metrics'][key]) for name,w in report['windows'].items() if key in w['metrics']]
        result[key]={'p95_budget_ms':p95,'max_budget_ms':maximum,'windows':{name:{'n':v['n'],'p95':v['p95'],'max':v['max'],
          'passed':v['p95']<=p95+(FLOAT_MS_EPSILON if key=='frame' else 0) and (v['p99']<=maximum if key=='frame' else v['max']<=maximum)} for name,v in values}}
        result[key]['passed']=all(v['passed'] for v in result[key]['windows'].values()) if values else None
    result['cold']={'ms':report['cold_interactive_ms'],'budget_ms':15000,'passed':report['cold_interactive_ms']<=15000}
    result['draw_calls']={'maximum_observed':max(w['bounded_counters']['calls'] for w in report['windows'].values()),'budget':1}
    result['draw_calls']['passed']=result['draw_calls']['maximum_observed']<=1
    return result

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path,help='Raw runner report or consolidated s100k_report.json')
    parser.add_argument('--run',default='stress',help='Run in a consolidated report (default: stress)')
    parser.add_argument('--output',type=Path,help='Write assessment here; source report stays unchanged')
    args=parser.parse_args()
    source=json.loads(args.report.read_text())
    report=source['runs'][args.run] if 'runs' in source else source
    checks=assess(report)
    complete=report.get('complete') is True and not report.get('errors')
    pauses=sum(w['metrics']['frame'].get('over50ms',0) for w in report['windows'].values())
    result={'complete':complete,'checks':checks,'long_pauses':pauses,
            'passed':complete and pauses==0 and all(v['passed'] is True for v in checks.values())}
    encoded=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.write_text(encoded)
    else:print(encoded,end='')
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
