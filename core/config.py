"""Single-process Streamlit application config. Secrets remain on local machine."""
import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=False)
DATA_DIR = Path(os.environ.get('AGENT_DATA_DIR', str(ROOT / 'data'))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
AGENT_DB = str(DATA_DIR / 'agent_jobs.sqlite3')
MOCK_DB = str(DATA_DIR / 'mock_marketplace.sqlite3')
FIXTURE_PATH = ROOT / 'fixtures' / 'demo_contract.json'
DEMO_BUYER_TOKEN = 'demo-buyer-token'
DEMO_SELLER_TOKEN = 'demo-seller-token'

AGENT_MODE = os.environ.get('AGENT_MODE', 'mock').strip().lower()
MARKETPLACE_BASE_URL = os.environ.get('MARKETPLACE_API_URL', os.environ.get('MARKETPLACE_BASE_URL', '')).strip().rstrip('/')
MARKETPLACE_API_KEY = os.environ.get('MARKETPLACE_API_KEY', '').strip()
MARKETPLACE_AUTH_SCHEME = os.environ.get('MARKETPLACE_AUTH_SCHEME', 'bearer').strip().lower()
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4.1-mini').strip()
ENABLE_OPENAI_CHAT = os.environ.get('ENABLE_OPENAI_CHAT', 'false').strip().lower() in ('1','true','yes')
MAX_MODEL_CALLS_PER_JOB = 0
MAX_COST_KRW_PER_JOB = 0
RULE_VERSION = 'static-rules-v0.1'

def writes_enabled():
    return AGENT_MODE == 'mock'

def marketplace_config_error():
    if AGENT_MODE == 'mock':
        return None
    if AGENT_MODE != 'live':
        return 'AGENT_MODE는 mock 또는 live만 허용됩니다.'
    if not MARKETPLACE_BASE_URL or not MARKETPLACE_API_KEY:
        return '실플랫폼 URL과 발급된 인증키가 필요합니다.'
    if MARKETPLACE_AUTH_SCHEME not in ('bearer', 'x-api-key'):
        return '인증 헤더 방식은 bearer 또는 x-api-key여야 합니다.'
    parsed = urlparse(MARKETPLACE_BASE_URL)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return '실플랫폼 API는 자격 정보 없는 https:// URL이어야 합니다.'
    if parsed.hostname in ('localhost','127.0.0.1','::1'):
        return '실플랫폼에는 외부 HTTPS 주소를 입력하세요.'
    return None

def openai_chat_status():
    return 'disabled' if not ENABLE_OPENAI_CHAT else ('ready' if OPENAI_API_KEY else 'missing_key')
