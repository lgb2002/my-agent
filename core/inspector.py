"""Static-only ZIP inspection; untrusted code is NEVER extracted or executed."""
import hashlib
import io
import pathlib
import re
import stat
import zipfile

MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_UNCOMPRESSED = 12 * 1024 * 1024
MAX_MEMBERS = 150
MAX_SINGLE_FILE = 1024 * 1024
TEXT_SUFFIXES = {'.py', '.js', '.ts', '.tsx', '.json', '.md', '.txt', '.toml', '.ini', '.yml', '.yaml', '.env', '.sample', '.example'}
DANGEROUS_EXTENSIONS = {'.exe', '.bat', '.cmd', '.ps1', '.dll', '.so', '.pkl', '.pickle'}
SENSITIVE_FILES = {'.env', 'id_rsa', 'id_ed25519', 'credentials.json', 'service-account.json', '.npmrc', '.pypirc'}
SECRET_MARKERS = [re.compile(r'(?i)(?:api_key|secret_key|access_token|password)\s*[:=]\s*[\'\"][^\'\"]{8,}[\'\"]'),
                  re.compile(r'AKIA[0-9A-Z]{16}')]
ENV_RE = re.compile(r'(?:os\.(?:getenv|environ\.get)\s*\(\s*[\'\"]([A-Z][A-Z0-9_]+)[\'\"]|os\.environ\s*\[\s*[\'\"]([A-Z][A-Z0-9_]+)[\'\"])')


class UnsafeArchive(ValueError):
    pass


def inspect_zip(raw):
    """All evidence is file path, check type and line number; no secret content returned."""
    if not raw or len(raw) > MAX_ARCHIVE_BYTES:
        raise UnsafeArchive('ZIP 용량 제한(4MB) 위반')
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise UnsafeArchive('유효한 ZIP 파일이 아닙니다.')
    digest = hashlib.sha256(raw).hexdigest()
    findings = []
    evidence = []
    names = set()
    texts = {}

    def add(severity, title, status, reference, recommendation):
        fid = 'ZIP-{:03d}'.format(len(findings) + 1)
        findings.append({'finding_id': fid, 'severity': severity, 'title': title,
                         'status': status, 'evidence_refs': [reference],
                         'recommendation': recommendation})
        evidence.append(reference)

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise UnsafeArchive('ZIP 파일 개수 상한 초과')
        total = 0
        for info in infos:
            name = info.filename.replace('\\', '/')
            path = pathlib.PurePosixPath(name)
            if name.startswith('/') or '..' in path.parts or ':' in path.parts[0] or '\x00' in name:
                raise UnsafeArchive('경로 순회/절대 경로 차단')
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UnsafeArchive('심볼릭 링크가 포함된 ZIP은 검사하지 않습니다.')
            if info.is_dir():
                continue
            if info.file_size > MAX_SINGLE_FILE:
                raise UnsafeArchive('ZIP 내부 단일 파일 크기 제한 초과')
            total += info.file_size
            if total > MAX_UNCOMPRESSED or (info.compress_size > 0 and info.file_size / info.compress_size > 150):
                raise UnsafeArchive('압축 폭탄 의심 ZIP 차단')
            if name.lower() in names:
                raise UnsafeArchive('중복 파일명 충돌')
            names.add(name.lower())
            basename = path.name.lower()
            suffix = path.suffix.lower()
            loc = 'zip://{}#file'.format(name)
            if basename in SENSITIVE_FILES or basename.startswith('.env.') and not basename.endswith(('.example', '.sample')):
                add('HIGH', '민감 파일 이름 감지: {}'.format(name), 'OBSERVED', loc,
                    '비밀번호·인증 관련 자료 제거 후 재제출 필요. 실제 내용은 표시하지 않습니다.')
            if suffix in DANGEROUS_EXTENSIONS:
                add('MEDIUM', '실행 가능/역직렬화 위험 파일 포함: {}'.format(name), 'OBSERVED', loc,
                    '수동 검토 전 파일을 실행하지 마세요.')
            if suffix in TEXT_SUFFIXES or basename in ('requirements.txt', 'dockerfile', 'readme'):
                content = archive.read(info)
                # Read UTF-8 only; cannot assume arbitrary binary files are safe or text.
                try:
                    texts[name] = content.decode('utf-8')
                except UnicodeDecodeError:
                    add('LOW', 'UTF-8 텍스트 판독 불가: {}'.format(name), 'UNKNOWN', loc, '문자 인코딩 확인 필요')
    env_used = set()
    documented = set()
    for name, value in texts.items():
        lowered = name.lower()
        if ('readme' in lowered or '.env.example' in lowered or '.env.sample' in lowered):
            documented.add(name)
        for ln, line in enumerate(value.splitlines(), 1):
            ref = 'zip://{}#L{}'.format(name, ln)
            if any(pattern.search(line) for pattern in SECRET_MARKERS):
                add('HIGH', '코드 내 자격증명 의심 항목: {}:{} (값 비공개)'.format(name, ln),
                    'OBSERVED', ref, '자격증명 무효화/교체 및 원본 제거 필요; 오탐 가능')
            for match in ENV_RE.finditer(line):
                env_used.add(match.group(1) or match.group(2))
    has_example = any(name.lower().endswith(('.env.example', '.env.sample')) for name in texts)
    if env_used and not has_example:
        add('MEDIUM', '환경변수 사용은 확인되지만 .env.example/.env.sample 파일 없음 (' +
            ', '.join(sorted(env_used)[:8]) + ')', 'OBSERVED', 'zip://metadata#env_doc',
            '필요 변수명(비밀 값 제외)·설정 절차를 문서화하세요.')
    if not any('readme' in n.lower() for n in texts):
        add('LOW', 'README 문서 미발견', 'OBSERVED', 'zip://metadata#readme',
            '새 환경에서 설치·실행 방법을 문서화하세요.')
    if not findings:
        add('INFO', '설정한 정적 규칙에서 명시적 이상 미발견', 'OBSERVED', 'zip://metadata#checks',
            '이는 안전성 또는 실제 구동 성공을 보장하지 않습니다.')
    high = any(f['severity'] in ('HIGH', 'CRITICAL') for f in findings)
    return {'report_type': 'STATIC', 'verdict': 'FAIL' if high else 'PARTIAL',
            'source_version_sha256': digest, 'findings': findings, 'evidence_refs': evidence,
            'files_scanned': len(names), 'dynamic_execution': 'NOT_TESTED',
            'rights_status': 'UNVERIFIED', 'coverage': 'ZIP 구조/텍스트 정적 규칙 한정', 'is_demo': True}


def sample_zip():
    """Generate locally the synthetic, purposely incomplete source archive."""
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w') as z:
        z.writestr('app.py', 'import os\n\ndef demo_reply():\n    token = os.getenv("AI_API_KEY")\n    return "Demo only" if token else "missing configuration"\n')
        z.writestr('README.md', '# DEMO 일정관리 샘플\n이 소스는 API 설정 절차가 빠져 있습니다. 실행하지 마세요.\n')
        z.writestr('requirements.txt', 'fastapi==0.95.2\n')
    return mem.getvalue()
