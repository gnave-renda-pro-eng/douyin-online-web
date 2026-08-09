import hashlib
import os
import re
import tempfile
import time
import threading
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory
import yt_dlp

try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

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
VIDEO_PATH_RE = re.compile(r'/video/(\d+)', re.I)
NOTE_PATH_RE = re.compile(r'/note/(\d+)', re.I)
ENV_COOKIE_FILE = '/tmp/douyin-env-cookies.txt'


def _normalize_cookie(raw_cookie: str) -> str:
    raw = (raw_cookie or '').strip()
    if raw.lower().startswith('cookie:'):
        raw = raw.split(':', 1)[1].strip()
    return raw.replace('\r', '').replace('\n', '')


def _write_cookie_file(raw_cookie: str, path: str) -> bool:
    raw = _normalize_cookie(raw_cookie)
    if not raw:
        return False

    rows = ['# Netscape HTTP Cookie File', '# Generated in request scope for Douyin extraction']
    count = 0
    for part in raw.split(';'):
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

    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(rows) + '\n')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


def _prepare_env_cookie_file() -> bool:
    raw = (os.getenv('DOUYIN_COOKIE') or '').strip()
    if not raw:
        try:
            os.remove(ENV_COOKIE_FILE)
        except FileNotFoundError:
            pass
        return False
    return _write_cookie_file(raw, ENV_COOKIE_FILE)


ENV_COOKIE_CONFIGURED = _prepare_env_cookie_file()
ENV_USER_AGENT = (os.getenv('DOUYIN_USER_AGENT') or '').strip()


def _is_douyin_host(host: str) -> bool:
    host = (host or '').lower().split(':', 1)[0]
    return host == 'douyin.com' or host.endswith('.douyin.com')


def _clean_url(text: str) -> str:
    match = URL_RE.search(text or '')
    if not match:
        raise ValueError('未识别到抖音链接，请粘贴完整分享文案或链接。')
    url = match.group(0).rstrip('，。！？、；：)）]}')
    host = urlparse(url).hostname or ''
    if not _is_douyin_host(host):
        raise ValueError('当前仅支持 douyin.com 的公开分享链接。')
    return url


def _classify_url(url: str):
    parsed = urlparse(url)
    video_match = VIDEO_PATH_RE.search(parsed.path)
    if video_match:
        return 'video', video_match.group(1)
    note_match = NOTE_PATH_RE.search(parsed.path)
    if note_match:
        return 'note', note_match.group(1)
    return 'unknown', ''


def _resolve_url(url: str, raw_cookie: str, user_agent: str):
    """Resolve v.douyin.com share links before invoking yt-dlp.

    This avoids sending /note/ URLs to an extractor that only accepts /video/ URLs.
    Redirects are accepted only when they remain under douyin.com.
    """
    kind, content_id = _classify_url(url)
    if kind != 'unknown':
        return url, kind, content_id

    if curl_requests is None:
        return url, 'unknown', ''

    headers = {
        'User-Agent': user_agent or ENV_USER_AGENT or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36',
        'Referer': 'https://www.douyin.com/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    normalized_cookie = _normalize_cookie(raw_cookie)
    if normalized_cookie:
        headers['Cookie'] = normalized_cookie

    try:
        response = curl_requests.get(
            url,
            headers=headers,
            allow_redirects=True,
            timeout=8,
            impersonate='chrome',
        )
        final_url = str(response.url or url)
    except Exception:
        return url, 'unknown', ''

    final_host = urlparse(final_url).hostname or ''
    if not _is_douyin_host(final_host):
        raise ValueError('抖音短链跳转到了非 douyin.com 地址，已停止解析。')

    kind, content_id = _classify_url(final_url)
    return final_url, kind, content_id


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


def _extract_once(url: str, impersonate: bool, cookie_file: str | None, user_agent: str):
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

    if cookie_file:
        opts['cookiefile'] = cookie_file
    if user_agent:
        opts['http_headers'] = {
            'User-Agent': user_agent,
            'Referer': 'https://www.douyin.com/',
        }
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
        'content_type': 'video',
        'title': info.get('title') or info.get('description') or '',
        'author': info.get('uploader') or info.get('creator') or info.get('channel') or '',
        'cover': info.get('thumbnail') or '',
        'url': video_url,
        'webpage_url': info.get('webpage_url') or url,
        'id': info.get('id') or '',
    }


def _extract_fast(url: str, cookie_file: str | None, user_agent: str):
    attempts = [True, False] if ImpersonateTarget is not None else [False]
    errors = []
    with _extract_lock:
        for use_impersonation in attempts:
            try:
                result = _extract_once(url, use_impersonation, cookie_file, user_agent)
                return result, ('browser' if use_impersonation else 'plain')
            except Exception as exc:
                errors.append(str(exc).strip())
    raise RuntimeError(next((e for e in reversed(errors) if e), '解析失败'))


def _friendly_error(message: str, has_cookie: bool):
    lower = message.lower()
    if 'fresh cookies' in lower:
        if has_cookie:
            return '当前 Cookie 已过期或被抖音风控，请重新获取一份新鲜 Cookie 后再试。', 'cookie_expired'
        return '抖音当前要求新鲜 Cookie。展开“Cookie 设置”，粘贴浏览器里的 Cookie 后再试。', 'cookie_required'
    if 'unsupported url' in lower and '/note/' in lower:
        return '检测到的是抖音图文/笔记作品（/note/），不是标准视频作品，当前视频提取器不处理此类型。', 'content_not_video'
    if '403' in lower or 'forbidden' in lower:
        return '抖音拒绝了当前请求（403/风控）。请换一份新鲜 Cookie 后再试。', 'blocked'
    return message, 'extract_failed'


def _cache_key(url: str, raw_cookie: str) -> str:
    cookie_tag = hashlib.sha256((raw_cookie or '').encode('utf-8')).hexdigest()[:12] if raw_cookie else ('env' if ENV_COOKIE_CONFIGURED else 'none')
    return f'{url}|{cookie_tag}'


@app.get('/')
def home():
    return send_from_directory('public', 'index.html')


@app.get('/api/health')
def health():
    return jsonify(
        ok=True,
        service='douyin-online-web',
        version='3.7.0',
        engine='flask-yt-dlp',
        cookie_configured=ENV_COOKIE_CONFIGURED,
        request_cookie_supported=True,
        share_link_resolution=True,
        content_type_detection=True,
        user_agent_configured=bool(ENV_USER_AGENT),
        ytdlp_version=getattr(yt_dlp.version, '__version__', 'unknown'),
    )


@app.post('/api/parse')
def parse_video():
    started = time.perf_counter()
    temp_cookie_file = None
    try:
        payload = request.get_json(silent=True) or {}
        input_url = _clean_url(str(payload.get('text') or ''))
        request_cookie = str(payload.get('cookie') or '').strip()
        request_user_agent = str(payload.get('user_agent') or '').strip()
        user_agent = request_user_agent or ENV_USER_AGENT

        resolved_url, content_type, content_id = _resolve_url(input_url, request_cookie, user_agent)

        if content_type == 'note':
            return jsonify(
                ok=False,
                error='检测到的是抖音图文/笔记作品，不是标准视频作品。当前“视频在线提取”只支持 /video/ 类型。',
                error_code='content_not_video',
                content_type='note',
                content_id=content_id,
                webpage_url=resolved_url,
                elapsed=round(time.perf_counter() - started, 2),
            ), 422

        if content_type == 'unknown' and '/note/' in resolved_url:
            return jsonify(
                ok=False,
                error='检测到的是抖音图文/笔记作品，当前视频提取器不支持此类型。',
                error_code='content_not_video',
                content_type='note',
                webpage_url=resolved_url,
                elapsed=round(time.perf_counter() - started, 2),
            ), 422

        cookie_file = ENV_COOKIE_FILE if ENV_COOKIE_CONFIGURED else None
        if request_cookie:
            tmp = tempfile.NamedTemporaryFile(prefix='douyin-', suffix='.txt', delete=False)
            temp_cookie_file = tmp.name
            tmp.close()
            if not _write_cookie_file(request_cookie, temp_cookie_file):
                raise ValueError('Cookie 格式无效，请复制浏览器 Request Headers 里的完整 Cookie 值。')
            cookie_file = temp_cookie_file

        has_cookie = bool(cookie_file)
        key = _cache_key(resolved_url, request_cookie)
        now = time.time()

        with _cache_lock:
            cached = _cache.get(key)
            if cached and now - cached['time'] < CACHE_TTL:
                result = dict(cached['data'])
                result['cached'] = True
                result['elapsed'] = round(time.perf_counter() - started, 2)
                return jsonify(result)

            failed = _fail_cache.get(key)
            if failed and now - failed['time'] < FAIL_CACHE_TTL:
                return jsonify(
                    ok=False,
                    error=failed['error'],
                    error_code=failed.get('error_code', 'extract_failed'),
                    cached=True,
                    elapsed=round(time.perf_counter() - started, 2),
                ), 422

        result, mode = _extract_fast(resolved_url, cookie_file, user_agent)
        result['mode'] = mode
        result['cached'] = False
        result['cookie_used'] = has_cookie
        result['resolved_url'] = resolved_url
        result['elapsed'] = round(time.perf_counter() - started, 2)

        with _cache_lock:
            _cache[key] = {'time': time.time(), 'data': dict(result)}
            _fail_cache.pop(key, None)
            if len(_cache) > 100:
                oldest = sorted(_cache.items(), key=lambda kv: kv[1]['time'])[:20]
                for old_key, _ in oldest:
                    _cache.pop(old_key, None)

        return jsonify(result)

    except ValueError as exc:
        return jsonify(ok=False, error=str(exc), error_code='invalid_input', elapsed=round(time.perf_counter() - started, 2)), 400
    except Exception as exc:
        original = str(exc).strip() or '解析失败'
        try:
            payload = request.get_json(silent=True) or {}
            request_cookie = str(payload.get('cookie') or '').strip()
            has_cookie = bool(request_cookie or ENV_COOKIE_CONFIGURED)
            url = _clean_url(str(payload.get('text') or ''))
            key = _cache_key(url, request_cookie)
        except Exception:
            request_cookie = ''
            has_cookie = ENV_COOKIE_CONFIGURED
            key = None

        message, error_code = _friendly_error(original, has_cookie)
        if key:
            with _cache_lock:
                _fail_cache[key] = {'time': time.time(), 'error': message, 'error_code': error_code}

        return jsonify(
            ok=False,
            error=message,
            error_code=error_code,
            cookie_used=has_cookie,
            elapsed=round(time.perf_counter() - started, 2),
        ), 422
    finally:
        if temp_cookie_file:
            try:
                os.remove(temp_cookie_file)
            except OSError:
                pass


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith('/api/'):
        return jsonify(ok=False, error='API 路径不存在'), 404
    return send_from_directory('public', 'index.html')
