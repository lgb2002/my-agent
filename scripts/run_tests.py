"""Run no-server offline test suite and save results instead of console noise."""
import json
import platform
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'), pattern='test_*.py', top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(stream=open(Path(ROOT/'docs'/'test_run.log'), 'w', encoding='utf8'), verbosity=2).run(suite)
    report={'timestamp_utc':datetime.now(timezone.utc).isoformat(),
            'python':platform.python_version(), 'os':platform.platform(),
            'test_count':result.testsRun,'passed':result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped),
            'failed':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
            'scope':'동일 Python 프로세스 내부 기능 검증. Streamlit UI 실기동/Windows Python3.12/실Replit/OpenAI API 호출은 미검증',
            'failures':[{'test':str(test), 'reason':message[-500:]} for test,message in result.failures+result.errors]}
    (ROOT/'docs'/'test_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('Tests: {} passed / {} failed / {} errors / {} skipped'.format(report['passed'],report['failed'],report['errors'],report['skipped']))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    sys.exit(main())
