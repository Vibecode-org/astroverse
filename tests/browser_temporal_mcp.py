"""Real Chrome/WebGL acceptance for the opt-in temporal test profile."""
import argparse
import json
from pathlib import Path
import time
from browser_mcp import MCP


def run(base, count, seconds):
    with MCP() as mcp:
        mcp.call('navigate_page', url=base+'/api/_test/temporal', timeout=45000)
        mcp.wait("typeof window.startTemporalBenchmark === 'function'")
        environment = mcp.evaluate("()=>({agent:navigator.userAgent,hardwareConcurrency:navigator.hardwareConcurrency,deviceMemory:navigator.deviceMemory,viewport:[innerWidth,innerHeight],pixelRatio:devicePixelRatio})")
        mcp.evaluate('()=>window.startTemporalBenchmark('+json.dumps(dict(count=count, seconds=seconds, cycles=3))+')')
        deadline = time.monotonic()+seconds+180
        while time.monotonic() < deadline:
            status = mcp.evaluate('()=>window.temporalBenchmarkStatus')
            print(json.dumps(status), flush=True)
            if not status['running']:
                break
            time.sleep(5)
        else:
            raise RuntimeError('temporal Chrome acceptance deadline')
        result = mcp.evaluate('()=>window.temporalBenchmarkResult')
        result['environment'] = environment
        result['console'] = mcp.call('list_console_messages', types=['error','warn'])
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://localhost:5174')
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.base, args.count, args.seconds)
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    assert result['complete'] and not result['error'], result.get('error')
    assert result['after_disposal']['geometries'] == result['after_disposal']['textures'] == 0
    print('PASS temporal Chrome: numeric oracle, bounded streaming, churn, resources', flush=True)
