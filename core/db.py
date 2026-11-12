"""Local durable agent job DB, independent from the marketplace database."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from .config import AGENT_DB

_LOCK = threading.RLock()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def connect():
    conn = sqlite3.connect(AGENT_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
    return conn


def init_db():
    with _LOCK:
        with connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, task_type TEXT NOT NULL,
                listing_id TEXT, status TEXT NOT NULL, request_json TEXT NOT NULL,
                result_json TEXT, error_message TEXT, request_key TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE (owner_id, request_key))''')
            con.execute('''CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                phase TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL,
                created_at TEXT NOT NULL)''')
            # A process restart cannot silently claim that an interrupted run succeeded.
            con.execute("UPDATE jobs SET status='PARTIAL', error_message='서버가 재시작되어 완료 확인 불가; 재시도 필요', updated_at=? WHERE status='RUNNING'", (utcnow(),))


def new_job(job_id, owner, key, task_type, listing_id, request):
    with _LOCK:
        with connect() as con:
            existing = con.execute('SELECT id,task_type,listing_id,request_json FROM jobs WHERE owner_id=? AND request_key=?', (owner, key)).fetchone()
            if existing:
                if (existing['task_type'] != task_type or existing['listing_id'] != listing_id or
                        json.loads(existing['request_json']) != request):
                    raise ValueError('Idempotency-Key와 다른 내용의 중복 요청입니다.')
                return existing['id'], False
            con.execute('''INSERT INTO jobs(id,owner_id,task_type,listing_id,status,request_json,request_key,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)''', (job_id, owner, task_type, listing_id, 'QUEUED',
                json.dumps(request, ensure_ascii=False), key, utcnow(), utcnow()))
            return job_id, True


def add_step(job_id, phase, status, summary):
    with _LOCK:
        with connect() as con:
            con.execute('INSERT INTO steps(job_id,phase,status,summary,created_at) VALUES(?,?,?,?,?)',
                        (job_id, phase, status, str(summary)[:1000], utcnow()))


def set_status(job_id, status, result=None, error=None):
    with _LOCK:
        with connect() as con:
            con.execute('UPDATE jobs SET status=?, result_json=?,error_message=?,updated_at=? WHERE id=?',
                        (status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                         str(error)[:500] if error else None, utcnow(), job_id))


def job_owner(job_id):
    with connect() as con:
        row = con.execute('SELECT owner_id FROM jobs WHERE id=?', (job_id,)).fetchone()
        return row['owner_id'] if row else None


def get_job(job_id, owner):
    with connect() as con:
        row = con.execute('SELECT * FROM jobs WHERE id=? AND owner_id=?', (job_id, owner)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record['request'] = json.loads(record.pop('request_json'))
        record['result'] = json.loads(record.pop('result_json')) if record.get('result_json') else None
        record.pop('result_json', None)
        record['steps'] = [dict(r) for r in con.execute('SELECT phase,status,summary,created_at FROM steps WHERE job_id=? ORDER BY id', (job_id,))]
        return record


def list_jobs(owner, limit=25):
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT id,task_type,listing_id,status,created_at,updated_at FROM jobs WHERE owner_id=? ORDER BY created_at DESC LIMIT ?', (owner, limit))]
