import base64
import hashlib
import html
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
import yt_dlp
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
except Exception:
    ImpersonateTarget = None


app = Flask(__name__, static_folder='public', static_url_path='')

CACHE_TTL = 600
FAIL_CACHE_TTL = 45
ITEM_TTL = 1800
MAX_MEDIA_BYTES = 90 * 1024 * 1024
MAX_SUBTITLE_CHARS = 40000

_cache = {}
_fail_cache = {}
_items = {}
_text_cache = {}
_cache_lock = threading.RLock()
_extract_lock = threading.Lock()

URL_RE = re.compile(r'https?://[^\s<>\"\']+', re.I)
VIDEO_PATH_RE = re.compile(r'/video/(\d+)', re.I)
NOTE_PATH_RE = re.compile(r'/note/(\d+)', re.I)
ENV_COOKIE_FILE = '/tmp/douyin-env-cookies.txt'

OPENAI_API_KEY = (os.getenv('OPENAI_API_KEY') or '').strip()
OPENAI_ANALYSIS_MODEL = (os.getenv('OPENAI_ANALYSIS_MODEL') or 'gpt-5-mini').strip()
OPENAI_TRANSCRIBE_MODEL = (os.getenv('OPENAI_TRANSCRIBE_MODEL') or 'gpt-4o-mini-transcribe').strip()


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


def _compact_subtitles(info):
    tracks = {}
    for group_name in ('subtitles', 'automatic_captions'):
        group = info.get(group_name)
        if not isinstance(group, dict):
            continue
        for lang, items in group.items():
            if not isinstance(items, list):
                continue
            cleaned = []
            for item in items[-5:]:
                if not isinstance(item, dict):
                    continue
                u = item.get('url')
                ext = item.get('ext') or ''
                if isinstance(u, str) and u.startswith(('http://', 'https://')):
                    cleaned.append({'url': u, 'ext': ext})
            if cleaned:
                tracks.setdefault(lang, []).extend(cleaned)
    return tracks


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
        'writesubtitles': False,
        'writeautomaticsub': False,
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
        'description': info.get('description') or info.get('title') or '',
        'author': info.get('uploader') or info.get('creator') or info.get('channel') or '',
        'cover': info.get('thumbnail') or '',
        'url': video_url,
        'webpage_url': info.get('webpage_url') or url,
        'id': info.get('id') or '',
        'duration': info.get('duration') or 0,
        '_subtitles': _compact_subtitles(info),
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
        return '检测到的是抖音图文/笔记作品（/note/），不是标准视频作品。', 'content_not_video'
    if '403' in lower or 'forbidden' in lower:
        return '抖音拒绝了当前请求（403/风控）。请换一份新鲜 Cookie 后再试。', 'blocked'
    return message, 'extract_failed'


def _cache_key(url: str, raw_cookie: str) -> str:
    cookie_tag = hashlib.sha256((raw_cookie or '').encode('utf-8')).hexdigest()[:12] if raw_cookie else ('env' if ENV_COOKIE_CONFIGURED else 'none')
    return f'{url}|{cookie_tag}'


def _cleanup_items():
    cutoff = time.time() - ITEM_TTL
    stale = [k for k, v in _items.items() if v.get('created', 0) < cutoff]
    for key in stale:
        _items.pop(key, None)
        _text_cache.pop(key, None)


def _store_item(result: dict, user_agent: str):
    token = secrets.token_urlsafe(18)
    stored = dict(result)
    stored['created'] = time.time()
    stored['user_agent'] = user_agent or ENV_USER_AGENT or 'Mozilla/5.0'
    with _cache_lock:
        _cleanup_items()
        _items[token] = stored
    return token


def _get_item(token: str):
    with _cache_lock:
        _cleanup_items()
        item = _items.get(token)
        if not item:
            return None
        return dict(item)


def _public_result(result: dict):
    return {k: v for k, v in result.items() if not k.startswith('_') and k not in ('created', 'user_agent')}


def _choose_subtitle_track(tracks: dict):
    if not isinstance(tracks, dict):
        return None
    preferred = ['zh-Hans', 'zh-CN', 'zh', 'zh-Hant', 'en', 'en-US']
    langs = preferred + [k for k in tracks.keys() if k not in preferred]
    ext_order = {'json3': 0, 'vtt': 1, 'srt': 2, 'ttml': 3}
    for lang in langs:
        items = tracks.get(lang)
        if not items:
            continue
        ranked = sorted(items, key=lambda x: ext_order.get((x.get('ext') or '').lower(), 9))
        for item in ranked:
            if item.get('url'):
                return lang, item
    return None


def _clean_caption_payload(text: str, ext: str):
    ext = (ext or '').lower()
    if ext == 'json3':
        try:
            payload = json.loads(text)
            parts = []
            for event in payload.get('events') or []:
                for seg in event.get('segs') or []:
                    value = seg.get('utf8')
                    if value and value.strip():
                        parts.append(value.strip())
            return '\n'.join(parts)[:MAX_SUBTITLE_CHARS]
        except Exception:
            return ''

    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith(('WEBVTT', 'NOTE', 'STYLE', 'REGION')):
            continue
        if '-->' in line:
            continue
        if re.fullmatch(r'\d+', line):
            continue
        line = re.sub(r'^\d\d:\d\d:\d\d[.,]\d+\s*', '', line)
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return '\n'.join(lines)[:MAX_SUBTITLE_CHARS]


def _fetch_subtitle_text(item: dict):
    chosen = _choose_subtitle_track(item.get('_subtitles') or {})
    if not chosen:
        return '', ''
    lang, track = chosen
    headers = {
        'User-Agent': item.get('user_agent') or 'Mozilla/5.0',
        'Referer': item.get('webpage_url') or 'https://www.douyin.com/',
    }
    try:
        r = requests.get(track['url'], headers=headers, timeout=15)
        r.raise_for_status()
        text = _clean_caption_payload(r.text, track.get('ext') or '')
        return text, f'字幕（{lang}）'
    except Exception:
        return '', ''


def _base_text(item: dict):
    title = (item.get('title') or '').strip()
    description = (item.get('description') or '').strip()
    if title and description and title == description:
        return title
    return '\n\n'.join(x for x in (title, description) if x)


def _download_media_to_file(item: dict, destination: str, max_bytes: int = MAX_MEDIA_BYTES):
    media_url = item.get('url') or ''
    if not media_url.startswith(('http://', 'https://')):
        raise RuntimeError('视频直链无效，请重新解析后再试。')

    headers = {
        'User-Agent': item.get('user_agent') or 'Mozilla/5.0',
        'Referer': item.get('webpage_url') or 'https://www.douyin.com/',
    }
    with requests.get(media_url, headers=headers, stream=True, timeout=(10, 45), allow_redirects=True) as r:
        r.raise_for_status()
        length = int(r.headers.get('Content-Length') or 0)
        if length and length > max_bytes:
            raise RuntimeError('视频文件过大，当前免费服务器不适合做 AI 转写/分析；下载功能仍可直接使用。')

        total = 0
        with open(destination, 'wb') as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError('视频文件过大，已停止 AI 处理以保护服务器资源。')
                f.write(chunk)
    return total


def _extract_audio(video_path: str, audio_path: str):
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error', '-i', video_path,
        '-vn', '-ac', '1', '-ar', '16000', '-b:a', '48k', audio_path
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not os.path.exists(audio_path):
        raise RuntimeError('音频提取失败：' + (proc.stderr[-300:] if proc.stderr else 'ffmpeg error'))


def _transcribe_with_openai(item: dict):
    if not OPENAI_API_KEY or OpenAI is None:
        return ''

    tmp_dir = tempfile.mkdtemp(prefix='douyin-ai-')
    video_path = os.path.join(tmp_dir, 'video.mp4')
    audio_path = os.path.join(tmp_dir, 'audio.mp3')
    try:
        _download_media_to_file(item, video_path)
        _extract_audio(video_path, audio_path)
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(audio_path, 'rb') as audio_file:
            result = client.audio.transcriptions.create(
                model=OPENAI_TRANSCRIBE_MODEL,
                file=audio_file,
            )
        text = getattr(result, 'text', '') or ''
        return text.strip()
    finally:
        for p in (video_path, audio_path):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def _get_text_for_item(token: str, allow_ai: bool = True):
    with _cache_lock:
        cached = _text_cache.get(token)
    if cached:
        return dict(cached)

    item = _get_item(token)
    if not item:
        raise KeyError('解析结果已过期，请重新解析视频。')

    subtitle_text, subtitle_source = _fetch_subtitle_text(item)
    base = _base_text(item)

    if subtitle_text:
        text = '\n\n'.join(x for x in (base, subtitle_text) if x)
        result = {'text': text, 'source': subtitle_source, 'ai_used': False}
    elif allow_ai and OPENAI_API_KEY:
        transcript = _transcribe_with_openai(item)
        text = '\n\n'.join(x for x in (base, transcript) if x)
        result = {'text': text or base, 'source': 'AI 语音转写' if transcript else '作品标题/文案', 'ai_used': bool(transcript)}
    else:
        result = {'text': base, 'source': '作品标题/文案', 'ai_used': False}

    with _cache_lock:
        _text_cache[token] = dict(result)
    return result


def _sample_frames(video_path: str, duration):
    frame_dir = tempfile.mkdtemp(prefix='douyin-frames-')
    paths = []
    try:
        duration = float(duration or 0)
    except Exception:
        duration = 0

    if duration > 4:
        points = [duration * x for x in (0.08, 0.32, 0.58, 0.84)]
    else:
        points = [0, 1, 2, 3]

    for index, sec in enumerate(points, 1):
        path = os.path.join(frame_dir, f'frame-{index}.jpg')
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-ss', f'{max(0, sec):.2f}', '-i', video_path,
            '-frames:v', '1', '-vf', 'scale=640:-2', '-q:v', '4', path
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
            if proc.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
                paths.append(path)
        except Exception:
            continue
    return frame_dir, paths


def _analyze_with_openai(item: dict, transcript: str):
    if not OPENAI_API_KEY or OpenAI is None:
        raise RuntimeError('AI 分析尚未配置。请在 Render Environment 中添加 OPENAI_API_KEY。')

    tmp_dir = tempfile.mkdtemp(prefix='douyin-analyze-')
    video_path = os.path.join(tmp_dir, 'video.mp4')
    frame_dir = None
    try:
        _download_media_to_file(item, video_path)
        frame_dir, frame_paths = _sample_frames(video_path, item.get('duration'))

        content = [{
            'type': 'input_text',
            'text': (
                '你是一名短视频导演、编剧和内容策划。请分析这个抖音视频。'
                '只能根据提供的作品文字和关键帧下结论；不确定的地方明确写“无法判断”。\n\n'
                '请按以下结构输出中文分析：\n'
                '1. 一句话主题\n2. 内容摘要\n3. 开头3秒钩子\n4. 内容结构拆解\n'
                '5. 人物/情绪/表演分析\n6. 镜头与画面节奏\n7. 爆点与传播点\n'
                '8. 可复用创作公式\n9. 具体优化建议\n10. 建议标题与标签\n\n'
                f'作品标题：{item.get("title") or ""}\n'
                f'作者：{item.get("author") or ""}\n'
                f'时长：{item.get("duration") or 0} 秒\n\n'
                f'提取文字/转写：\n{(transcript or "")[:16000]}'
            ),
        }]

        for frame_path in frame_paths[:4]:
            with open(frame_path, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('ascii')
            content.append({
                'type': 'input_image',
                'image_url': f'data:image/jpeg;base64,{encoded}',
                'detail': 'low',
            })

        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.responses.create(
            model=OPENAI_ANALYSIS_MODEL,
            input=[{'role': 'user', 'content': content}],
        )
        text = getattr(response, 'output_text', '') or ''
        if not text.strip():
            raise RuntimeError('AI 没有返回分析结果。')
        return text.strip(), len(frame_paths)
    finally:
        try:
            os.remove(video_path)
        except OSError:
            pass
        if frame_dir:
            for p in Path(frame_dir).glob('*'):
                try:
                    p.unlink()
                except OSError:
                    pass
            try:
                os.rmdir(frame_dir)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


@app.get('/')
def home():
    return send_from_directory('public', 'index.html')


@app.get('/api/health')
def health():
    return jsonify(
        ok=True,
        service='douyin-online-web',
        version='4.0.0',
        engine='flask-yt-dlp',
        cookie_configured=ENV_COOKIE_CONFIGURED,
        request_cookie_supported=True,
        share_link_resolution=True,
        content_type_detection=True,
        download_supported=True,
        text_extract_supported=True,
        ai_analysis_supported=True,
        ai_configured=bool(OPENAI_API_KEY and OpenAI is not None),
        analysis_model=OPENAI_ANALYSIS_MODEL if OPENAI_API_KEY else '',
        transcribe_model=OPENAI_TRANSCRIBE_MODEL if OPENAI_API_KEY else '',
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

        if content_type == 'note' or (content_type == 'unknown' and '/note/' in resolved_url):
            return jsonify(
                ok=False,
                error='检测到的是抖音图文/笔记作品，不是标准视频作品。当前下载、转写和视频分析功能只处理 /video/ 类型。',
                error_code='content_not_video',
                content_type='note',
                content_id=content_id,
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
                token = _store_item(result, user_agent)
                public = _public_result(result)
                public['token'] = token
                return jsonify(public)

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

        token = _store_item(result, user_agent)
        public = _public_result(result)
        public['token'] = token
        return jsonify(public)

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


@app.get('/api/download/<token>')
def download_video(token):
    item = _get_item(token)
    if not item:
        return jsonify(ok=False, error='下载链接已过期，请重新解析视频。'), 410

    media_url = item.get('url') or ''
    if not media_url.startswith(('http://', 'https://')):
        return jsonify(ok=False, error='视频地址无效，请重新解析。'), 422

    headers = {
        'User-Agent': item.get('user_agent') or 'Mozilla/5.0',
        'Referer': item.get('webpage_url') or 'https://www.douyin.com/',
    }
    range_header = request.headers.get('Range')
    if range_header:
        headers['Range'] = range_header

    try:
        upstream = requests.get(media_url, headers=headers, stream=True, timeout=(10, 45), allow_redirects=True)
        upstream.raise_for_status()
    except Exception as exc:
        return jsonify(ok=False, error=f'下载源地址已失效，请重新解析：{exc}'), 502

    title = re.sub(r'[\\/:*?"<>|\r\n]+', '_', (item.get('title') or item.get('id') or 'douyin-video')).strip(' ._')
    title = title[:80] or 'douyin-video'
    filename = quote(title + '.mp4')

    response_headers = {
        'Content-Type': upstream.headers.get('Content-Type', 'video/mp4'),
        'Content-Disposition': f"attachment; filename*=UTF-8''{filename}",
        'Accept-Ranges': upstream.headers.get('Accept-Ranges', 'bytes'),
        'Cache-Control': 'no-store',
    }
    for key in ('Content-Length', 'Content-Range'):
        if upstream.headers.get(key):
            response_headers[key] = upstream.headers[key]

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=256 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    status = 206 if upstream.status_code == 206 else 200
    return Response(stream_with_context(generate()), status=status, headers=response_headers)


@app.get('/api/text/<token>')
def extract_text(token):
    started = time.perf_counter()
    item = _get_item(token)
    if not item:
        return jsonify(ok=False, error='解析结果已过期，请重新解析视频。'), 410

    try:
        result = _get_text_for_item(token, allow_ai=True)
        return jsonify(
            ok=True,
            text=result.get('text') or '',
            source=result.get('source') or '',
            ai_used=result.get('ai_used', False),
            ai_configured=bool(OPENAI_API_KEY),
            elapsed=round(time.perf_counter() - started, 2),
        )
    except Exception as exc:
        return jsonify(ok=False, error=str(exc), elapsed=round(time.perf_counter() - started, 2)), 422


@app.get('/api/analyze/<token>')
def analyze_video(token):
    started = time.perf_counter()
    item = _get_item(token)
    if not item:
        return jsonify(ok=False, error='解析结果已过期，请重新解析视频。', error_code='expired'), 410
    if not OPENAI_API_KEY or OpenAI is None:
        return jsonify(
            ok=False,
            error='AI 内容分析尚未启用。请在 Render → Environment 添加 OPENAI_API_KEY 后重新部署。',
            error_code='ai_not_configured',
        ), 503

    try:
        text_result = _get_text_for_item(token, allow_ai=True)
        analysis, frame_count = _analyze_with_openai(item, text_result.get('text') or '')
        return jsonify(
            ok=True,
            analysis=analysis,
            transcript_source=text_result.get('source') or '',
            frame_count=frame_count,
            model=OPENAI_ANALYSIS_MODEL,
            elapsed=round(time.perf_counter() - started, 2),
        )
    except Exception as exc:
        return jsonify(ok=False, error=str(exc), error_code='analysis_failed', elapsed=round(time.perf_counter() - started, 2)), 422


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith('/api/'):
        return jsonify(ok=False, error='API 路径不存在'), 404
    return send_from_directory('public', 'index.html')
