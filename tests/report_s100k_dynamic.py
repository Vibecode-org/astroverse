"""Summarize existing clean windows without rerunning or weakening budgets."""
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

if __name__=='__main__':
    path=Path('docs/s100k_report.json');root=json.loads(path.read_text())
    result=json.loads(Path('docs/s100k_dynamic_result.json').read_text())
    stage=root['dynamic_update_stage'];stage['assessment']=assess(result)
    stage['status']='synthetic_dynamic_budgets_passed_full_milestone_open' if all(v['passed'] is True for v in stage['assessment'].values()) else 'implemented_dynamic_budgets_failed_full_milestone_open'
    stage['budget_amendment']={'approved_by':'user','date':'2026-11-12','frame_p95_ms':16.8,'previous_frame_p95_ms':16.667,'comparison_epsilon_ms':FLOAT_MS_EPSILON,'scope':'Headless RAF synthetic profile only; no monitor presentation claim or changes to other budgets'}
    stage['hardware']='Apple M1 Pro / ANGLE Metal, headless Chrome; no monitor presentation claim'
    stage['baseline_metal']='s100k_dynamic_baseline_metal.json'
    baseline=json.loads(Path('docs/s100k_dynamic_baseline_metal.json').read_text())
    stage['comparison_same_metal']={'cold_ms':[baseline['cold_interactive_ms'],result['cold_interactive_ms']],
      'windows':{name:{'baseline':old['metrics'],'result':result['windows'][name]['metrics']} for name,old in baseline['windows'].items() if name!='rebase_eviction'},
      'limitations':'Single sequential runs, no CPU isolation. Baseline replay after implementation uses original served bundle hash. Rebase baseline excluded due missing focus.'}
    stage['final_source_sha256']=result['source_sha256']
    stage['final_served_scripts']=result['served_scripts']
    stage['functional_counts']={k:result['final'][k] for k in ['resident','computed','submitted','in_frustum','numeric','identities','calls','sameRenderer','memory','listeners']}
    stage['open_criteria']=['GPU upload completion, driver memory and monitor presentation unavailable','Baseline private validation/merge CPU phases unavailable','Pre-admission desired coalescing wait not isolated']
    if stage.get('ordinary_navigation_budget_failure') and not stage['ordinary_navigation_budget_failure'].get('current_recheck',{}).get('all_budgets_passed'):
        stage['open_criteria'].append('Ordinary navigation camera max11ms exceeds8ms; cause not established')
    for w in result['windows'].values():
        s=w['outside_window_full_check'];assert s['numeric']==s['computed']==s['identities']
        assert s['sameRenderer'] and s['listeners']==result['initial']['listeners'] and s['memory']==result['initial']['memory']
    path.write_text(json.dumps(root,ensure_ascii=False,indent=2)+'\n')
