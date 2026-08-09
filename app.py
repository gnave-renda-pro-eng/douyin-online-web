import os
import re
import time
import threading
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory
import yt_dlp

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
except Exception:
    ImpersonateTarget = None

app = Flask(__name__, static_folder='public', static_url_path='')

CACHE_TTL = 600
FAIL_CACHE_TTL = 45
_cache = {}
_fail_cache = {}
_cache_lock = threading.Lock()
_extract_lock = threading.Lock()

URL_RE = re.compile(r'https?://[^\s<>\"\']+', re.I)
COOKIE_FILE = '/tmp/douyin-cookies.txt'


def _prepare_cookie_file():
    """Convert a browser Cookie request header stored in Render env into Netscape format.

    The secret is never returned to the browser or written into the repository.
    """
    raw = (os.getenv('DOUYIN_COOKIE') or '').strip()
    if not raw:
        try:
            os.remove(COOKIE_FILE)
        except FileNotFoundError:
            pass
        return False

    if raw.lower().startswith('cookie:'):
        raw = raw.split(':', 1)[1].strip()

    rows = ['# Netscape HTTP Cookie File', '# Generated at container startup from DOUYIN_COOKIE']
    count = 0
    for part in raw.replace('\r', '').replace('\n', '').split(';'):
        part = part.strip()
        if not part or '=' not in part:
            continue
        name, value = part.split('=', 1)
        name = name.strip()
        value = value.strip().replace('\t', '')
        if not name:
            continue
        rows.append(f'.douyin.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}')
        count += 1

    if not count:
        return False

    with open(COOKIE_FILE, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(rows) + '\n')
    try:
        os.chmod(COOKIE_FILE, 0o600)
    except OSError:
        pass
    return True


COOKIE_CONFIGURED = _prepare_cookie_file()
DOUYIN_USER_AGENT = (os.getenv('DOUYIN_USER_AGENT') or '').strip()


def _clean_url(text: str) -> str:
    match = URL_RE.search(text or '')
    if not match:
        raise ValueError('未识别到抖音链接，请粘贴完整分享文案或链接。')
    url = match.group(0).rstrip('，。！？、；：)）]}')
    host = (urlparse(url).hostname or '').lower()
    if not (host == 'douyin.com' or host.endswith('.douyin.com')):
        raise ValueError('当前仅支持 douyin.com 的公开分享链接。')
    return url


def _pick_video_url(info):
    if not isinstance(info, dict):
        return ''

    direct = info.get('url')
    if isinstance(direct, str) and direct.startswith(('http://', 'https://')):
        return direct

    for key in ('requested_downloads', 'requested_formats'):
        items = info.get(key)
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                u = item.get('url')
                if isinstance(u, str) and u.startswith(('http://', 'https://')):
                    return u

    formats = info.get('formats')
    if isinstance(formats, list):
        for item in reversed(formats):
            if not isinstance(item, dict):
                continue
            u = item.get('url')
            if not isinstance(u, str) or not u.startswith(('http://', 'https://')):
                continue
            if item.get('vcodec') not in (None, 'none'):
                return u
        for item in reversed(formats):
            if isinstance(item, dict):
                u = item.get('url')
                if isinstance(u, str) and u.startswith(('http://', 'https://')):
                    return u
    return ''


def _extract_once(url: str, impersonate: bool):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
        'socket_timeout': 7,
        'retries': 0,
        'fragment_retries': 0,
        'extractor_retries': 0,
        'check_formats': False,
        'format': 'best[ext=mp4]/best',
        'cachedir': False,
    }

    if COOKIE_CONFIGURED:
        opts['cookiefile'] = COOKIE_FILE
    if DOUYIN_USER_AGENT:
        opts['http_headers'] = {'User-Agent': DOUYIN_USER_AGENT, 'Referer': 'https://www.douyin.com/'}
    if impersonate and ImpersonateTarget is not None:
        opts['impersonate'] = ImpersonateTarget(client='chrome')

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise RuntimeError('解析器未返回有效的视频信息。')

    video_url = _pick_video_url(info)
    if not video_url:
        raise RuntimeError('已读取视频信息，但没有获得可访问的视频地址。')

    return {
        'ok': True,
        'title': info.get('title') or info.get('description') or '',
        'author': info.get('uploader') or info.get('creator') or info.get('channel') or '',
        'cover': info.get('thumbnail') or '',
        'url': video_url,
        'webpage_url': info.get('webpage_url') or url,
        'id': info.get('id') or '',
    }


def _extract_fast(url: str):
    attempts = [True, False] if ImpersonateTarget is not None else [False]
    errors = []
    with _extract_lock:
        for use_impersonation in attempts:
            try:
                result = _extract_once(url, impersonate=use_impersonation)
                return result, ('browser' if use_impersonation else 'plain')
            except Exception as exc:
                errors.append(str(exc).strip())
    raise RuntimeError(next((e for e in reversed(errors) if e), '解析失败'))


def _friendly_error(message: str):
    lower = message.lower()
    if 'fresh cookies' in lower:
        if COOKIE_CONFIGURED:
            return (
                '服务器里的抖音 Cookie 已失效或被风控，请在 Render 的 Environment 中更新 '
                'DOUYIN_COOKIE；更新后重新部署。'
            ), 'cookie_expired'
        return (
            '抖音当前要求新鲜 Cookie。请在 Render 的 Environment 中添加 DOUYIN_COOKIE '
            '后重新部署；网站不会把 Cookie 写入 GitHub。'
        ), 'cookie_required'
    if '403' in lower or 'forbidden' in lower:
        return '抖音拒绝了当前服务器请求（403/风控）。请更新 Cookie 后再试。', 'blocked'
    return message, 'extract_failed'


@app.get('/')
def home():
    return send_from_directory('public', 'index.html')


@app.get('/api/health')
def health():
    return jsonify(
        ok=True,
        service='douyin-online-web',
        version='3.5.0',
        engine='flask-yt-dlp',
        cookie_configured=COOKIE_CONFIGURED,
        user_agent_configured=bool(DOUYIN_USER_AGENT),
        ytdlp_version=getattr(yt_dlp.version, '__version__', 'unknown'),
    )


@app.post('/api/parse')
def parse_video():
    started = time.perf_counter()
    try:
        payload = request.get_json(silent=True) or {}
        url = _clean_url(str(payload.get('text') or ''))
        now = time.time()

        with _cache_lock:
            cached = _cache.get(url)
            if cached and now - cached['time'] < CACHE_TTL:
                result = dict(cached['data'])
                result['cached'] = True
                result['elapsed'] = round(time.perf_counter() - started, 2)
                return jsonify(result)

            failed = _fail_cache.get(url)
            if failed and now - failed['time'] < FAIL_CACHE_TTL:
                return jsonify(
                    ok=False,
                    error=failed['error'],
                    error_code=failed.get('error_code', 'extract_failed'),
                    cached=True,
                    elapsed=round(time.perf_counter() - started, 2),
                ), 422

        result, mode = _extract_fast(url)
        result['mode'] = mode
        result['cached'] = False
        result['elapsed'] = round(time.perf_counter() - started, 2)

        with _cache_lock:
            _cache[url] = {'time': time.time(), 'data': dict(result)}
            _fail_cache.pop(url, None)
            if len(_cache) > 100:
                oldest = sorted(_cache.items(), key=lambda kv: kv[1]['time'])[:20]
                for key, _ in oldest:
                    _cache.pop(key, None)

        return jsonify(result)

    except ValueError as exc:
        return jsonify(ok=False, error=str(exc), error_code='invalid_url', elapsed=round(time.perf_counter() - started, 2)), 400
    except Exception as exc:
        original = str(exc).strip() or '解析失败'
        message, error_code = _friendly_error(original)
        try:
            url = _clean_url(str((request.get_json(silent=True) or {}).get('text') or ''))
            with _cache_lock:
                _fail_cache[url] = {'time': time.time(), 'error': message, 'error_code': error_code}
        except Exception:
            pass
        return jsonify(
            ok=False,
            error=message,
            error_code=error_code,
            cookie_configured=COOKIE_CONFIGURED,
            elapsed=round(time.perf_counter() - started, 2),
        ), 422


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith('/api/'):
        return jsonify(ok=False, error='API 路径不存在'), 404
    return send_from_directory('public', 'index.html')
