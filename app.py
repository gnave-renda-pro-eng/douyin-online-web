import base64
import hashlib
import html
import json
import os
import re
import secrets
import shutil
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
FAIL_CACHE_TTL = 30
ITEM_TTL = 1800
MAX_MEDIA_BYTES = 90 * 1024 * 1024
MAX_SUBTITLE_CHARS = 50000

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
ENV_USER_AGENT = (os.getenv('DOUYIN_USER_AGENT') or '').strip()


def _normalize_cookie(raw_cookie: str) -> str:
    raw = (raw_cookie or '').strip()
    if raw.lower().startswith('cookie:'):
        raw = raw.split(':', 1)[1].strip()
    return raw.replace('\r', '').replace('\n', '')


def _write_cookie_file(raw_cookie: str, path: str) -> bool:
    raw = _normalize_cookie(raw_cookie)
    if not raw:
        return False
    rows = ['# Netscape HTTP Cookie File', '# Generated for temporary Douyin request']
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
ENV_COOKIE_RAW = _normalize_cookie(os.getenv('DOUYIN_COOKIE') or '')


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
    m = VIDEO_PATH_RE.search(parsed.path)
    if m:
        return 'video', m.group(1)
    m = NOTE_PATH_RE.search(parsed.path)
    if m:
        return 'note', m.group(1)
    return 'unknown', ''


def _headers(user_agent: str, webpage_url: str = '', cookie: str = ''):
    h = {
        'User-Agent': user_agent or ENV_USER_AGENT or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36',
        'Referer': webpage_url or 'https://www.douyin.com/',
        'Accept': '*/*',
    }
    cookie = _normalize_cookie(cookie)
    if cookie:
        h['Cookie'] = cookie
    return h


def _resolve_url(url: str, raw_cookie: str, user_agent: str):
    kind, content_id = _classify_url(url)
    if kind != 'unknown':
        return url, kind, content_id
    if curl_requests is None:
        return url, 'unknown', ''
    try:
        r = curl_requests.get(
            url,
            headers=_headers(user_agent, 'https://www.douyin.com/', raw_cookie),
            allow_redirects=True,
            timeout=8,
            impersonate='chrome',
        )
        final_url = str(r.url or url)
    except Exception:
        return url, 'unknown', ''
    host = urlparse(final_url).hostname or ''
    if not _is_douyin_host(host):
        raise ValueError('抖音短链跳转到了非 douyin.com 地址，已停止解析。')
    kind, content_id = _classify_url(final_url)
    return final_url, kind, content_id


def _compact_subtitles(info: dict):
    tracks = {}
    for group_name in ('subtitles', 'automatic_captions'):
        group = info.get(group_name)
        if not isinstance(group, dict):
            continue
        for lang, items in group.items():
            if not isinstance(items, list):
                continue
            cleaned = []
            for item in items[-8:]:
                if not isinstance(item, dict):
                    continue
                u = item.get('url')
                if isinstance(u, str) and u.startswith(('http://', 'https://')):
                    cleaned.append({'url': u, 'ext': item.get('ext') or ''})
            if cleaned:
                tracks.setdefault(lang, []).extend(cleaned)
    return tracks


def _pick_video_url(info: dict):
    if not isinstance(info, dict):
        return ''
    formats = info.get('formats')
    if isinstance(formats, list):
        progressive = []
        for f in formats:
            if not isinstance(f, dict):
                continue
            u = f.get('url')
            if not isinstance(u, str) or not u.startswith(('http://', 'https://')):
                continue
            vcodec, acodec = f.get('vcodec'), f.get('acodec')
            protocol = str(f.get('protocol') or '').lower()
            ext = str(f.get('ext') or '').lower()
            if vcodec not in (None, 'none') and acodec not in (None, 'none') and 'm3u8' not in protocol and ext in ('mp4', 'mov', 'webm'):
                progressive.append(f)
        if progressive:
            progressive.sort(key=lambda x: (x.get('height') or 0, x.get('tbr') or 0))
            return progressive[-1].get('url') or ''
    direct = info.get('url')
    if isinstance(direct, str) and direct.startswith(('http://', 'https://')):
        return direct
    if isinstance(formats, list):
        for f in reversed(formats):
            if isinstance(f, dict):
                u = f.get('url')
                if isinstance(u, str) and u.startswith(('http://', 'https://')):
                    return u
    return ''


def _extract_once(url: str, impersonate: bool, cookie_file: str | None, user_agent: str):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
        'socket_timeout': 8,
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
        opts['http_headers'] = {'User-Agent': user_agent, 'Referer': 'https://www.douyin.com/'}
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
        for impersonate in attempts:
            try:
                return _extract_once(url, impersonate, cookie_file, user_agent), ('browser' if impersonate else 'plain')
            except Exception as exc:
                errors.append(str(exc).strip())
    raise RuntimeError(next((e for e in reversed(errors) if e), '解析失败'))


def _friendly_error(message: str, has_cookie: bool):
    lower = message.lower()
    if 'fresh cookies' in lower:
        if has_cookie:
            return '当前 Cookie 已过期或被抖音风控，请重新获取新鲜 Cookie 后再试。', 'cookie_expired'
        return '抖音当前要求新鲜 Cookie。展开“Cookie 设置”，粘贴浏览器 Request Headers 中的 Cookie 后再试。', 'cookie_required'
    if 'unsupported url' in lower and '/note/' in lower:
        return '检测到的是抖音图文/笔记作品，不是标准视频作品。', 'content_not_video'
    if '403' in lower or 'forbidden' in lower:
        return '抖音拒绝了当前请求（403/风控）。请更新 Cookie 后再试。', 'blocked'
    return message, 'extract_failed'


def _cache_key(url: str, raw_cookie: str):
    tag = hashlib.sha256((raw_cookie or '').encode()).hexdigest()[:12] if raw_cookie else ('env' if ENV_COOKIE_CONFIGURED else 'none')
    return f'{url}|{tag}'


def _cleanup_items():
    cutoff = time.time() - ITEM_TTL
    for key in [k for k, v in _items.items() if v.get('created', 0) < cutoff]:
        _items.pop(key, None)
        _text_cache.pop(key, None)


def _store_item(result: dict, user_agent: str, raw_cookie: str):
    token = secrets.token_urlsafe(18)
    stored = dict(result)
    stored['created'] = time.time()
    stored['user_agent'] = user_agent or ENV_USER_AGENT or 'Mozilla/5.0'
    stored['_cookie'] = _normalize_cookie(raw_cookie) or ENV_COOKIE_RAW
    with _cache_lock:
        _cleanup_items()
        _items[token] = stored
    return token


def _get_item(token: str):
    with _cache_lock:
        _cleanup_items()
        item = _items.get(token)
        return dict(item) if item else None


def _public_result(result: dict):
    return {k: v for k, v in result.items() if not k.startswith('_') and k not in ('created', 'user_agent')}


def _choose_subtitle_track(tracks: dict):
    if not isinstance(tracks, dict):
        return None
    preferred = ['zh-Hans', 'zh-CN', 'zh', 'zh-Hant', 'en', 'en-US']
    langs = preferred + [k for k in tracks if k not in preferred]
    order = {'json3': 0, 'vtt': 1, 'srt': 2, 'ttml': 3}
    for lang in langs:
        items = tracks.get(lang) or []
        for item in sorted(items, key=lambda x: order.get(str(x.get('ext') or '').lower(), 9)):
            if item.get('url'):
                return lang, item
    return None


def _clean_caption_payload(text: str, ext: str):
    ext = (ext or '').lower()
    if ext == 'json3':
        try:
            payload = json.loads(text)
            out = []
            for event in payload.get('events') or []:
                for seg in event.get('segs') or []:
                    t = (seg.get('utf8') or '').strip()
                    if t:
                        out.append(t)
            return '\n'.join(out)[:MAX_SUBTITLE_CHARS]
        except Exception:
            return ''
    text = html.unescape(re.sub(r'<[^>]+>', '', text))
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or '-->' in line or re.fullmatch(r'\d+', line):
            continue
        if line.upper().startswith(('WEBVTT', 'NOTE', 'STYLE', 'REGION')):
            continue
        if not lines or lines[-1] != line:
            lines.append(line)
    return '\n'.join(lines)[:MAX_SUBTITLE_CHARS]


def _fetch_subtitle_text(item: dict):
    chosen = _choose_subtitle_track(item.get('_subtitles') or {})
    if not chosen:
        return '', ''
    lang, track = chosen
    try:
        r = requests.get(
            track['url'],
            headers=_headers(item.get('user_agent') or '', item.get('webpage_url') or '', item.get('_cookie') or ''),
            timeout=15,
        )
        r.raise_for_status()
        return _clean_caption_payload(r.text, track.get('ext') or ''), f'字幕（{lang}）'
    except Exception:
        return '', ''


def _base_text(item: dict):
    title = (item.get('title') or '').strip()
    desc = (item.get('description') or '').strip()
    if title and title == desc:
        return title
    return '\n\n'.join(x for x in (title, desc) if x)


def _temp_cookie_file(cookie: str):
    if not _normalize_cookie(cookie):
        return None
    fd, path = tempfile.mkstemp(prefix='dy-cookie-', suffix='.txt')
    os.close(fd)
    if not _write_cookie_file(cookie, path):
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return path


def _download_via_ytdlp(item: dict, target_dir: str):
    cookie_file = _temp_cookie_file(item.get('_cookie') or '')
    outtmpl = os.path.join(target_dir, 'media.%(ext)s')
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'format': 'bv*+ba/b',
        'merge_output_format': 'mp4',
        'outtmpl': outtmpl,
        'socket_timeout': 15,
        'retries': 1,
        'fragment_retries': 1,
        'cachedir': False,
        'http_headers': {
            'User-Agent': item.get('user_agent') or 'Mozilla/5.0',
            'Referer': 'https://www.douyin.com/',
        },
    }
    if cookie_file:
        opts['cookiefile'] = cookie_file
    if ImpersonateTarget is not None:
        opts['impersonate'] = ImpersonateTarget(client='chrome')
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([item.get('webpage_url') or item.get('resolved_url') or ''])
        files = [p for p in Path(target_dir).glob('media.*') if p.is_file()]
        if not files:
            raise RuntimeError('yt-dlp 未生成视频文件。')
        files.sort(key=lambda p: p.stat().st_size, reverse=True)
        return str(files[0])
    finally:
        if cookie_file:
            try:
                os.remove(cookie_file)
            except OSError:
                pass


def _download_media_to_file(item: dict, destination: str, max_bytes: int = MAX_MEDIA_BYTES):
    media_url = item.get('url') or ''
    direct_error = None
    if media_url.startswith(('http://', 'https://')):
        try:
            with requests.get(
                media_url,
                headers=_headers(item.get('user_agent') or '', item.get('webpage_url') or '', item.get('_cookie') or ''),
                stream=True,
                timeout=(10, 45),
                allow_redirects=True,
            ) as r:
                r.raise_for_status()
                ctype = (r.headers.get('Content-Type') or '').lower()
                if 'mpegurl' in ctype or 'text/html' in ctype or media_url.lower().split('?', 1)[0].endswith('.m3u8'):
                    raise RuntimeError('直链是播放清单，需要使用 yt-dlp 下载。')
                length = int(r.headers.get('Content-Length') or 0)
                if length and length > max_bytes:
                    raise RuntimeError('视频文件过大，已停止 AI 处理以保护免费服务器资源。')
                total = 0
                with open(destination, 'wb') as f:
                    for chunk in r.iter_content(256 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            raise RuntimeError('视频文件过大，已停止 AI 处理以保护免费服务器资源。')
                        f.write(chunk)
                if total > 1024:
                    return total
        except Exception as exc:
            direct_error = exc
    temp_dir = tempfile.mkdtemp(prefix='dy-ytdlp-')
    try:
        source = _download_via_ytdlp(item, temp_dir)
        size = os.path.getsize(source)
        if size > max_bytes:
            raise RuntimeError('视频文件过大，已停止 AI 处理以保护免费服务器资源。')
        shutil.copyfile(source, destination)
        return size
    except Exception as exc:
        if direct_error:
            raise RuntimeError(f'视频下载失败：{exc}') from exc
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _extract_audio(video_path: str, audio_path: str):
    proc = subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-i', video_path, '-vn', '-ac', '1', '-ar', '16000', '-b:a', '40k', audio_path],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not os.path.exists(audio_path):
        raise RuntimeError('音频提取失败：' + (proc.stderr[-300:] if proc.stderr else 'ffmpeg error'))


def _transcribe_with_openai(item: dict):
    if not OPENAI_API_KEY or OpenAI is None:
        return ''
    tmp_dir = tempfile.mkdtemp(prefix='dy-transcribe-')
    video = os.path.join(tmp_dir, 'video.mp4')
    audio = os.path.join(tmp_dir, 'audio.mp3')
    try:
        _download_media_to_file(item, video)
        _extract_audio(video, audio)
        if os.path.getsize(audio) > 24 * 1024 * 1024:
            raise RuntimeError('音频过长，超过当前单次转写大小限制。')
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(audio, 'rb') as f:
            result = client.audio.transcriptions.create(model=OPENAI_TRANSCRIBE_MODEL, file=f)
        return (getattr(result, 'text', '') or '').strip()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _get_text_for_item(token: str, allow_ai: bool = True):
    with _cache_lock:
        cached = _text_cache.get(token)
    if cached:
        return dict(cached)
    item = _get_item(token)
    if not item:
        raise KeyError('解析结果已过期，请重新解析视频。')
    subtitle, source = _fetch_subtitle_text(item)
    base = _base_text(item)
    if subtitle:
        result = {'text': '\n\n'.join(x for x in (base, subtitle) if x), 'source': source, 'ai_used': False}
    elif allow_ai and OPENAI_API_KEY and OpenAI is not None:
        transcript = _transcribe_with_openai(item)
        result = {
            'text': '\n\n'.join(x for x in (base, transcript) if x),
            'source': 'AI 语音转写' if transcript else '作品标题/文案',
            'ai_used': bool(transcript),
        }
    else:
        result = {'text': base, 'source': '作品标题/文案', 'ai_used': False}
    with _cache_lock:
        _text_cache[token] = dict(result)
    return result


def _sample_frames(video_path: str, duration):
    frame_dir = tempfile.mkdtemp(prefix='dy-frames-')
    try:
        duration = float(duration or 0)
    except Exception:
        duration = 0
    points = [duration * x for x in (0.06, 0.28, 0.55, 0.82)] if duration > 5 else [0, 1, 2, 3]
    paths = []
    for idx, sec in enumerate(points, 1):
        p = os.path.join(frame_dir, f'frame-{idx}.jpg')
        try:
            proc = subprocess.run(
                ['ffmpeg', '-y', '-loglevel', 'error', '-ss', f'{max(0, sec):.2f}', '-i', video_path, '-frames:v', '1', '-vf', 'scale=640:-2', '-q:v', '4', p],
                capture_output=True, text=True, timeout=40,
            )
            if proc.returncode == 0 and os.path.exists(p) and os.path.getsize(p) > 0:
                paths.append(p)
        except Exception:
            pass
    return frame_dir, paths


def _analyze_with_openai(item: dict, transcript: str):
    if not OPENAI_API_KEY or OpenAI is None:
        raise RuntimeError('AI 分析尚未配置。请在 Render Environment 添加 OPENAI_API_KEY。')
    tmp_dir = tempfile.mkdtemp(prefix='dy-analyze-')
    video = os.path.join(tmp_dir, 'video.mp4')
    frame_dir = None
    try:
        _download_media_to_file(item, video)
        frame_dir, frame_paths = _sample_frames(video, item.get('duration'))
        content = [{
            'type': 'input_text',
            'text': (
                '你是一名短视频导演、编剧和内容策划。请只根据下面的文字和关键帧分析，不确定的地方明确写“无法判断”。\n\n'
                '输出结构：\n1. 一句话主题\n2. 内容摘要\n3. 开头3秒钩子\n4. 内容结构拆解\n5. 人物/情绪/表演\n'
                '6. 镜头与画面节奏\n7. 爆点与传播点\n8. 可复用创作公式\n9. 具体优化建议\n10. 建议标题与标签\n\n'
                f'标题：{item.get("title") or ""}\n作者：{item.get("author") or ""}\n时长：{item.get("duration") or 0}秒\n\n'
                f'提取文字：\n{(transcript or "")[:16000]}'
            ),
        }]
        for p in frame_paths[:4]:
            with open(p, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('ascii')
            content.append({'type': 'input_image', 'image_url': f'data:image/jpeg;base64,{encoded}', 'detail': 'low'})
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.responses.create(model=OPENAI_ANALYSIS_MODEL, input=[{'role': 'user', 'content': content}])
        text = (getattr(response, 'output_text', '') or '').strip()
        if not text:
            raise RuntimeError('AI 没有返回分析结果。')
        return text, len(frame_paths)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if frame_dir:
            shutil.rmtree(frame_dir, ignore_errors=True)


@app.get('/')
def home():
    return send_from_directory('public', 'index.html')


@app.get('/api/health')
def health():
    return jsonify(
        ok=True,
        service='douyin-online-web',
        version='4.1.0',
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
        ytdlp_version=getattr(getattr(yt_dlp, 'version', None), '__version__', 'unknown'),
    )


@app.post('/api/parse')
def parse_video():
    started = time.perf_counter()
    temp_cookie_file = None
    try:
        payload = request.get_json(silent=True) or {}
        input_url = _clean_url(str(payload.get('text') or ''))
        raw_cookie = str(payload.get('cookie') or '').strip()
        user_agent = str(payload.get('user_agent') or '').strip() or ENV_USER_AGENT
        resolved_url, content_type, content_id = _resolve_url(input_url, raw_cookie, user_agent)
        if content_type == 'note' or (content_type == 'unknown' and '/note/' in resolved_url):
            return jsonify(ok=False, error='检测到的是抖音图文/笔记作品，不是标准视频作品。', error_code='content_not_video', content_type='note', content_id=content_id, webpage_url=resolved_url, elapsed=round(time.perf_counter()-started,2)), 422

        cookie_file = ENV_COOKIE_FILE if ENV_COOKIE_CONFIGURED else None
        if raw_cookie:
            tmp = tempfile.NamedTemporaryFile(prefix='dy-parse-', suffix='.txt', delete=False)
            temp_cookie_file = tmp.name
            tmp.close()
            if not _write_cookie_file(raw_cookie, temp_cookie_file):
                raise ValueError('Cookie 格式无效。')
            cookie_file = temp_cookie_file
        has_cookie = bool(cookie_file)
        key = _cache_key(resolved_url, raw_cookie)
        now = time.time()
        with _cache_lock:
            cached = _cache.get(key)
            if cached and now - cached['time'] < CACHE_TTL:
                result = dict(cached['data'])
                result['cached'] = True
                result['elapsed'] = round(time.perf_counter()-started,2)
                token = _store_item(result, user_agent, raw_cookie)
                public = _public_result(result); public['token'] = token
                return jsonify(public)
            failed = _fail_cache.get(key)
            if failed and now - failed['time'] < FAIL_CACHE_TTL:
                return jsonify(ok=False, error=failed['error'], error_code=failed.get('error_code','extract_failed'), cached=True, elapsed=round(time.perf_counter()-started,2)), 422

        result, mode = _extract_fast(resolved_url, cookie_file, user_agent)
        result.update(mode=mode, cached=False, cookie_used=has_cookie, resolved_url=resolved_url, elapsed=round(time.perf_counter()-started,2))
        with _cache_lock:
            _cache[key] = {'time': time.time(), 'data': dict(result)}
            _fail_cache.pop(key, None)
        token = _store_item(result, user_agent, raw_cookie)
        public = _public_result(result); public['token'] = token
        return jsonify(public)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc), error_code='invalid_input', elapsed=round(time.perf_counter()-started,2)), 400
    except Exception as exc:
        original = str(exc).strip() or '解析失败'
        try:
            payload = request.get_json(silent=True) or {}
            raw_cookie = str(payload.get('cookie') or '').strip()
            has_cookie = bool(raw_cookie or ENV_COOKIE_CONFIGURED)
            url = _clean_url(str(payload.get('text') or ''))
            key = _cache_key(url, raw_cookie)
        except Exception:
            has_cookie, key = ENV_COOKIE_CONFIGURED, None
        message, code = _friendly_error(original, has_cookie)
        if key:
            with _cache_lock:
                _fail_cache[key] = {'time': time.time(), 'error': message, 'error_code': code}
        return jsonify(ok=False, error=message, error_code=code, cookie_used=has_cookie, elapsed=round(time.perf_counter()-started,2)), 422
    finally:
        if temp_cookie_file:
            try: os.remove(temp_cookie_file)
            except OSError: pass


@app.get('/api/download/<token>')
def download_video(token):
    item = _get_item(token)
    if not item:
        return jsonify(ok=False, error='下载链接已过期，请重新解析视频。'), 410
    title = re.sub(r'[\\/:*?"<>|\r\n]+', '_', item.get('title') or item.get('id') or 'douyin-video').strip(' ._')[:80] or 'douyin-video'
    filename = quote(title + '.mp4')
    media_url = item.get('url') or ''
    headers = _headers(item.get('user_agent') or '', item.get('webpage_url') or '', item.get('_cookie') or '')

    if media_url.startswith(('http://','https://')) and not media_url.lower().split('?',1)[0].endswith('.m3u8'):
        try:
            if request.headers.get('Range'):
                headers['Range'] = request.headers['Range']
            upstream = requests.get(media_url, headers=headers, stream=True, timeout=(10,45), allow_redirects=True)
            ctype = (upstream.headers.get('Content-Type') or '').lower()
            if upstream.ok and 'mpegurl' not in ctype and 'text/html' not in ctype:
                resp_headers = {
                    'Content-Type': upstream.headers.get('Content-Type','video/mp4'),
                    'Content-Disposition': f"attachment; filename*=UTF-8''{filename}",
                    'Accept-Ranges': upstream.headers.get('Accept-Ranges','bytes'),
                    'Cache-Control': 'no-store',
                }
                for k in ('Content-Length','Content-Range'):
                    if upstream.headers.get(k): resp_headers[k] = upstream.headers[k]
                def gen():
                    try:
                        for chunk in upstream.iter_content(256*1024):
                            if chunk: yield chunk
                    finally:
                        upstream.close()
                return Response(stream_with_context(gen()), status=206 if upstream.status_code==206 else 200, headers=resp_headers)
            upstream.close()
        except Exception:
            pass

    tmp_dir = tempfile.mkdtemp(prefix='dy-download-')
    try:
        path = _download_via_ytdlp(item, tmp_dir)
        size = os.path.getsize(path)
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify(ok=False, error=f'下载失败，请重新解析后再试：{exc}'), 502

    def file_gen():
        try:
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(256*1024)
                    if not chunk: break
                    yield chunk
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    return Response(stream_with_context(file_gen()), headers={'Content-Type':'video/mp4','Content-Length':str(size),'Content-Disposition':f"attachment; filename*=UTF-8''{filename}",'Cache-Control':'no-store'})


@app.route('/api/text/<token>', methods=['GET','POST'])
def extract_text(token):
    started = time.perf_counter()
    if not _get_item(token):
        return jsonify(ok=False, error='解析结果已过期，请重新解析视频。'), 410
    try:
        result = _get_text_for_item(token, allow_ai=True)
        return jsonify(ok=True, text=result.get('text') or '', source=result.get('source') or '', ai_used=result.get('ai_used',False), ai_configured=bool(OPENAI_API_KEY and OpenAI is not None), elapsed=round(time.perf_counter()-started,2))
    except Exception as exc:
        return jsonify(ok=False, error=str(exc), elapsed=round(time.perf_counter()-started,2)), 422


@app.route('/api/analyze/<token>', methods=['GET','POST'])
def analyze_video(token):
    started = time.perf_counter()
    item = _get_item(token)
    if not item:
        return jsonify(ok=False, error='解析结果已过期，请重新解析视频。', error_code='expired'), 410
    if not OPENAI_API_KEY or OpenAI is None:
        return jsonify(ok=False, error='AI 内容分析尚未启用。请在 Render → Environment 添加 OPENAI_API_KEY 后重新部署。', error_code='ai_not_configured'), 503
    try:
        text_result = _get_text_for_item(token, allow_ai=True)
        analysis, frame_count = _analyze_with_openai(item, text_result.get('text') or '')
        return jsonify(ok=True, analysis=analysis, transcript_source=text_result.get('source') or '', frame_count=frame_count, model=OPENAI_ANALYSIS_MODEL, elapsed=round(time.perf_counter()-started,2))
    except Exception as exc:
        message = str(exc)
        if '401' in message or 'api key' in message.lower():
            message = 'OpenAI API Key 无效或没有权限，请检查 Render 的 OPENAI_API_KEY。'
        return jsonify(ok=False, error=message, error_code='analysis_failed', elapsed=round(time.perf_counter()-started,2)), 422


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith('/api/'):
        return jsonify(ok=False, error='API 路径不存在'), 404
    return send_from_directory('public','index.html')
