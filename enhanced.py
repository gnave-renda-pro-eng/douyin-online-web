import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from flask import jsonify, request

import app as core

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

app = core.app

FULL_TEXT_CACHE = {}
ANALYSIS_CACHE = {}
CACHE_LOCK = threading.RLock()
FULL_TEXT_TTL = 1800
TRANSCRIBE_CHUNK_SECONDS = 45


def _api_key(payload=None):
    payload = payload or {}
    return str(payload.get('api_key') or '').strip() or str(core.OPENAI_API_KEY or '').strip()


def _key_tag(key: str) -> str:
    if not key:
        return 'none'
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:10]


def _cleanup_cache():
    cutoff = time.time() - FULL_TEXT_TTL
    for cache in (FULL_TEXT_CACHE, ANALYSIS_CACHE):
        stale = [k for k, v in cache.items() if v.get('time', 0) < cutoff]
        for key in stale:
            cache.pop(key, None)


def _dedupe_caption_lines(text: str) -> str:
    """Only remove obvious consecutive rolling-caption duplicates."""
    if not text:
        return ''
    output = []
    for raw in text.replace('\r', '').split('\n'):
        line = ' '.join(raw.strip().split())
        if not line:
            continue
        if output and line == output[-1]:
            continue
        if output and len(output[-1]) >= 8 and line.startswith(output[-1]) and len(line) - len(output[-1]) <= 28:
            output[-1] = line
            continue
        output.append(line)
    return '\n'.join(output).strip()


def _base_sections(item: dict):
    title = (item.get('title') or '').strip()
    desc = (item.get('description') or '').strip()
    parts = []
    if title:
        parts.append(('作品标题', title))
    if desc and desc != title:
        parts.append(('作品文案', desc))
    return parts


def _format_full_text(item: dict, transcript: str, source: str):
    sections = _base_sections(item)
    transcript = _dedupe_caption_lines(transcript)
    if transcript:
        label = '完整语音转写' if 'AI' in source else '完整字幕/语音文字'
        sections.append((label, transcript))
    return '\n\n'.join(f'【{label}】\n{value}' for label, value in sections).strip()


def _probe_duration(path: str) -> float:
    try:
        proc = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', path],
            capture_output=True, text=True, timeout=20,
        )
        if proc.returncode == 0:
            return max(0.0, float((proc.stdout or '0').strip() or 0))
    except Exception:
        pass
    return 0.0


def _split_audio(audio_path: str, work_dir: str):
    duration = _probe_duration(audio_path)
    if duration <= 70:
        return [(0.0, duration or 0.0, audio_path)]

    out_pattern = os.path.join(work_dir, 'chunk-%03d.mp3')
    proc = subprocess.run(
        [
            'ffmpeg', '-y', '-loglevel', 'error', '-i', audio_path,
            '-f', 'segment', '-segment_time', str(TRANSCRIBE_CHUNK_SECONDS),
            '-reset_timestamps', '1', '-c:a', 'libmp3lame', '-b:a', '48k', out_pattern,
        ],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        return [(0.0, duration, audio_path)]

    files = sorted(Path(work_dir).glob('chunk-*.mp3'))
    if not files:
        return [(0.0, duration, audio_path)]

    chunks = []
    for idx, p in enumerate(files):
        start = idx * TRANSCRIBE_CHUNK_SECONDS
        end = min(duration, start + TRANSCRIBE_CHUNK_SECONDS) if duration else start + TRANSCRIBE_CHUNK_SECONDS
        chunks.append((float(start), float(end), str(p)))
    return chunks


def _transcribe_one(client, path: str):
    with open(path, 'rb') as f:
        result = client.audio.transcriptions.create(
            model=core.OPENAI_TRANSCRIBE_MODEL or 'gpt-4o-mini-transcribe',
            file=f,
            language='zh',
        )
    return (getattr(result, 'text', '') or '').strip()


def _transcribe_full(item: dict, api_key: str):
    if not api_key or OpenAI is None:
        raise RuntimeError('AI_KEY_REQUIRED')

    tmp_dir = tempfile.mkdtemp(prefix='dy-fulltext-')
    video_path = os.path.join(tmp_dir, 'video.mp4')
    audio_path = os.path.join(tmp_dir, 'audio.mp3')
    try:
        core._download_media_to_file(item, video_path)
        core._extract_audio(video_path, audio_path)
        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1024:
            raise RuntimeError('没有检测到可转写的音频轨道。')
        if os.path.getsize(audio_path) > 24 * 1024 * 1024:
            raise RuntimeError('音频文件超过当前单次处理限制，请先压缩或截短视频。')

        client = OpenAI(api_key=api_key)
        chunks = _split_audio(audio_path, tmp_dir)
        pieces = []
        for start, end, chunk_path in chunks:
            text = _transcribe_one(client, chunk_path)
            text = _dedupe_caption_lines(text)
            if not text:
                continue
            if len(chunks) > 1:
                sm, ss = divmod(int(start), 60)
                em, es = divmod(int(end), 60)
                pieces.append(f'[{sm:02d}:{ss:02d}-{em:02d}:{es:02d}]\n{text}')
            else:
                pieces.append(text)

        transcript = '\n\n'.join(pieces).strip()
        if not transcript:
            raise RuntimeError('语音转写完成，但没有返回文字。')
        return transcript, len(chunks)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _partial_without_ai(item: dict):
    base = '\n\n'.join(f'【{label}】\n{value}' for label, value in _base_sections(item))
    return {
        'text': base,
        'transcript': '',
        'source': '作品标题/文案',
        'ai_used': False,
        'complete': False,
        'needs_ai': True,
        'chunk_count': 0,
        'title': item.get('title') or '',
        'description': item.get('description') or '',
        'author': item.get('author') or '',
    }


def _full_text(token: str, api_key: str, allow_partial=False):
    item = core._get_item(token)
    if not item:
        raise KeyError('解析结果已过期，请重新解析视频。')

    cache_key = f'{token}|full|{_key_tag(api_key)}'
    with CACHE_LOCK:
        _cleanup_cache()
        cached = FULL_TEXT_CACHE.get(cache_key)
        if cached:
            return dict(cached['data'])

    subtitle, subtitle_source = core._fetch_subtitle_text(item)
    subtitle = _dedupe_caption_lines(subtitle)
    if subtitle:
        result = {
            'text': _format_full_text(item, subtitle, subtitle_source or '视频字幕'),
            'transcript': subtitle,
            'source': subtitle_source or '视频字幕',
            'ai_used': False,
            'complete': True,
            'needs_ai': False,
            'chunk_count': 0,
            'title': item.get('title') or '',
            'description': item.get('description') or '',
            'author': item.get('author') or '',
        }
    elif not api_key:
        if allow_partial:
            return _partial_without_ai(item)
        raise RuntimeError('AI_KEY_REQUIRED')
    else:
        transcript, chunk_count = _transcribe_full(item, api_key)
        result = {
            'text': _format_full_text(item, transcript, 'AI 完整语音转写'),
            'transcript': transcript,
            'source': 'AI 分段完整语音转写' if chunk_count > 1 else 'AI 完整语音转写',
            'ai_used': True,
            'complete': True,
            'needs_ai': False,
            'chunk_count': chunk_count,
            'title': item.get('title') or '',
            'description': item.get('description') or '',
            'author': item.get('author') or '',
        }

    with CACHE_LOCK:
        FULL_TEXT_CACHE[cache_key] = {'time': time.time(), 'data': dict(result)}
    return result


def _sample_more_frames(video_path: str, duration):
    frame_dir = tempfile.mkdtemp(prefix='dy-frames-plus-')
    try:
        duration = max(0.0, float(duration or 0))
    except Exception:
        duration = 0.0
    ratios = (0.03, 0.16, 0.31, 0.47, 0.63, 0.79, 0.94)
    points = [duration * r for r in ratios] if duration > 8 else [0, 1, 2, 3, 4, 5]
    paths = []
    for idx, sec in enumerate(points, 1):
        path = os.path.join(frame_dir, f'frame-{idx}.jpg')
        try:
            proc = subprocess.run(
                ['ffmpeg', '-y', '-loglevel', 'error', '-ss', f'{max(0, sec):.2f}', '-i', video_path,
                 '-frames:v', '1', '-vf', 'scale=768:-2', '-q:v', '4', path],
                capture_output=True, text=True, timeout=45,
            )
            if proc.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
                paths.append(path)
        except Exception:
            continue
    return frame_dir, paths


def _analyze_video(item: dict, full_text: dict, api_key: str):
    if not api_key or OpenAI is None:
        raise RuntimeError('AI_KEY_REQUIRED')

    transcript_hash = hashlib.sha256((full_text.get('transcript') or '').encode('utf-8')).hexdigest()[:12]
    cache_key = f"{item.get('id') or item.get('webpage_url')}|{transcript_hash}"
    with CACHE_LOCK:
        _cleanup_cache()
        cached = ANALYSIS_CACHE.get(cache_key)
        if cached:
            return dict(cached['data'])

    tmp_dir = tempfile.mkdtemp(prefix='dy-analysis-')
    video_path = os.path.join(tmp_dir, 'video.mp4')
    frame_dir = None
    frame_paths = []
    try:
        core._download_media_to_file(item, video_path)
        frame_dir, frame_paths = _sample_more_frames(video_path, item.get('duration'))

        prompt = f'''你是一名资深短视频导演、编剧、剪辑师和内容策划。请对这个抖音视频做“可用于复刻和优化”的专业分析。

硬性要求：
- 只根据提供的作品信息、完整语音转写和关键帧判断；无法确认的内容写“无法判断”，不要编造。
- 语音内容按实际顺序理解，不要只总结标题。
- 画面分析区分“关键帧可见事实”和“推断”。
- 输出必须具体，可直接用于下一条视频创作。

请按以下结构输出：
1. 一句话核心主题
2. 完整内容摘要（按时间/逻辑顺序）
3. 开头 0-3 秒钩子：画面钩子、语言钩子、信息差
4. 内容结构拆解：起—承—转—合，每段目的
5. 文案结构：关键句、设问、冲突、转折、结论、行动召唤
6. 人物表现：身份、情绪、眼神、动作、表演节奏
7. 镜头与画面：景别、构图、光线、机位、色调、视觉焦点
8. 剪辑节奏：可能的切点、信息密度、节奏变化
9. 声音层：口播/对白、环境声、音乐作用；无法判断时明确说明
10. 爆点与传播机制：为什么可能让人停留、评论、收藏、转发
11. 可复用创作公式：动机 → 钩子 → 展开 → 证明 → 反转/升华 → 收尾
12. 可直接复制的下一条视频脚本框架
13. 具体优化建议：至少 8 条，按优先级排序
14. 推荐标题：5 个
15. 推荐标签：10 个以内

作品标题：{item.get('title') or ''}
作者：{item.get('author') or ''}
视频时长：{item.get('duration') or 0} 秒

完整文字：
{(full_text.get('text') or '')[:32000]}
'''
        content = [{'type': 'input_text', 'text': prompt}]
        for frame_path in frame_paths[:7]:
            try:
                with open(frame_path, 'rb') as f:
                    encoded = base64.b64encode(f.read()).decode('ascii')
                content.append({
                    'type': 'input_image',
                    'image_url': f'data:image/jpeg;base64,{encoded}',
                    'detail': 'low',
                })
            except Exception:
                continue

        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=core.OPENAI_ANALYSIS_MODEL or 'gpt-5-mini',
            input=[{'role': 'user', 'content': content}],
        )
        analysis = (getattr(response, 'output_text', '') or '').strip()
        if not analysis:
            raise RuntimeError('AI 没有返回视频分析内容。')
        result = {
            'analysis': analysis,
            'frame_count': len(frame_paths),
            'model': core.OPENAI_ANALYSIS_MODEL or 'gpt-5-mini',
            'transcript_source': full_text.get('source') or '',
        }
        with CACHE_LOCK:
            ANALYSIS_CACHE[cache_key] = {'time': time.time(), 'data': dict(result)}
        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if frame_dir:
            shutil.rmtree(frame_dir, ignore_errors=True)


@app.get('/api/advanced-health')
def advanced_health():
    return jsonify(
        ok=True,
        version='4.3.0',
        full_text_supported=True,
        request_api_key_supported=True,
        env_ai_configured=bool(core.OPENAI_API_KEY and OpenAI is not None),
        analysis_supported=True,
        chunked_transcription=True,
        transcribe_chunk_seconds=TRANSCRIBE_CHUNK_SECONDS,
        transcribe_model=core.OPENAI_TRANSCRIBE_MODEL or 'gpt-4o-mini-transcribe',
        analysis_model=core.OPENAI_ANALYSIS_MODEL or 'gpt-5-mini',
    )


@app.post('/api/text-full/<token>')
def text_full(token):
    started = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    key = _api_key(payload)
    try:
        result = _full_text(token, key, allow_partial=True)
        return jsonify(
            ok=True,
            **result,
            api_key_used=bool(key),
            elapsed=round(time.perf_counter() - started, 2),
        )
    except KeyError as exc:
        return jsonify(ok=False, error=str(exc), error_code='expired'), 410
    except Exception as exc:
        message = str(exc).strip() or '完整文字提取失败'
        if message == 'AI_KEY_REQUIRED':
            return jsonify(ok=False, error='该视频没有可用字幕，需要 AI Key 才能进行完整语音转写。', error_code='ai_key_required'), 409
        return jsonify(ok=False, error=message, error_code='full_text_failed', elapsed=round(time.perf_counter() - started, 2)), 422


@app.post('/api/analyze-full/<token>')
def analyze_full(token):
    started = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    key = _api_key(payload)
    item = core._get_item(token)
    if not item:
        return jsonify(ok=False, error='解析结果已过期，请重新解析视频。', error_code='expired'), 410
    if not key or OpenAI is None:
        return jsonify(ok=False, error='视频内容分析需要 AI Key。请展开“AI 设置”填写后重试。', error_code='ai_key_required'), 409
    try:
        full_text = _full_text(token, key, allow_partial=False)
        result = _analyze_video(item, full_text, key)
        return jsonify(
            ok=True,
            **result,
            elapsed=round(time.perf_counter() - started, 2),
        )
    except Exception as exc:
        message = str(exc).strip() or '视频分析失败'
        code = 'ai_key_required' if message == 'AI_KEY_REQUIRED' else 'analysis_failed'
        return jsonify(ok=False, error=message, error_code=code, elapsed=round(time.perf_counter() - started, 2)), 422
