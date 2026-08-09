import base64
import hashlib
import os
import shutil
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
    """Conservative dedupe: only remove obvious consecutive repeats.

    We deliberately avoid aggressive semantic dedupe so the user's full transcript
    is preserved even when a speaker intentionally repeats a sentence.
    """
    if not text:
        return ''
    output = []
    for raw in text.replace('\r', '').split('\n'):
        line = ' '.join(raw.strip().split())
        if not line:
            continue
        if output and line == output[-1]:
            continue
        # Rolling captions sometimes repeat the previous line and append a few chars.
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
    blocks = []
    for label, value in sections:
        blocks.append(f'【{label}】\n{value}')
    return '\n\n'.join(blocks).strip()


def _transcribe_full(item: dict, api_key: str):
    if not api_key or OpenAI is None:
        raise RuntimeError('要提取“完整版语音文字”，当前视频没有可用字幕，需要配置 OpenAI API Key 后进行完整语音转写。')

    tmp_dir = tempfile.mkdtemp(prefix='dy-fulltext-')
    video_path = os.path.join(tmp_dir, 'video.mp4')
    audio_path = os.path.join(tmp_dir, 'audio.mp3')
    try:
        core._download_media_to_file(item, video_path)
        core._extract_audio(video_path, audio_path)
        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1024:
            raise RuntimeError('没有检测到可转写的音频轨道。')
        if os.path.getsize(audio_path) > 24 * 1024 * 1024:
            raise RuntimeError('音频文件超过当前单次转写限制，请先压缩或截短视频后再试。')

        client = OpenAI(api_key=api_key)
        kwargs = {
            'model': core.OPENAI_TRANSCRIBE_MODEL or 'gpt-4o-mini-transcribe',
            'language': 'zh',
        }
        with open(audio_path, 'rb') as f:
            result = client.audio.transcriptions.create(file=f, **kwargs)
        text = (getattr(result, 'text', '') or '').strip()
        if not text:
            raise RuntimeError('语音转写完成，但没有返回文字。')
        return _dedupe_caption_lines(text)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _full_text(token: str, api_key: str):
    item = core._get_item(token)
    if not item:
        raise KeyError('解析结果已过期，请重新解析视频。')

    cache_key = f'{token}|full'
    with CACHE_LOCK:
        _cleanup_cache()
        cached = FULL_TEXT_CACHE.get(cache_key)
        if cached:
            return dict(cached['data'])

    subtitle, subtitle_source = core._fetch_subtitle_text(item)
    subtitle = _dedupe_caption_lines(subtitle)
    if subtitle:
        source = subtitle_source or '视频字幕'
        transcript = subtitle
        ai_used = False
    else:
        transcript = _transcribe_full(item, api_key)
        source = 'AI 完整语音转写'
        ai_used = True

    result = {
        'text': _format_full_text(item, transcript, source),
        'transcript': transcript,
        'source': source,
        'ai_used': ai_used,
        'title': item.get('title') or '',
        'description': item.get('description') or '',
        'author': item.get('author') or '',
    }
    with CACHE_LOCK:
        FULL_TEXT_CACHE[cache_key] = {'time': time.time(), 'data': dict(result)}
    return result


def _analyze_video(item: dict, full_text: dict, api_key: str):
    if not api_key or OpenAI is None:
        raise RuntimeError('视频内容分析需要 OpenAI API Key。请在网页“AI 设置”中临时填写，或在 Render Environment 中配置 OPENAI_API_KEY。')

    cache_key = f"{item.get('id') or item.get('webpage_url')}|{hashlib.sha256((full_text.get('transcript') or '').encode('utf-8')).hexdigest()[:12]}"
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
        try:
            frame_dir, frame_paths = core._sample_frames(video_path, item.get('duration'))
        except Exception:
            frame_dir, frame_paths = None, []

        transcript = (full_text.get('transcript') or '').strip()
        prompt = f'''你是一名资深短视频导演、编剧、剪辑师和内容策划。请对这个抖音视频做“可用于复刻和优化”的专业分析。

硬性要求：
- 只根据提供的作品信息、完整语音转写和关键帧判断；无法确认的内容写“无法判断”，不要编造。
- 语音内容要按实际顺序理解，不要只总结标题。
- 画面分析要区分“关键帧能看出的事实”和“推断”。
- 输出必须具体，可直接用于下一条视频创作。

请按以下结构输出：
1. 一句话核心主题
2. 完整内容摘要（按时间/逻辑顺序）
3. 开头 0-3 秒钩子：画面钩子、语言钩子、信息差
4. 内容结构拆解：起—承—转—合，每段目的
5. 文案结构：关键句、设问、冲突、转折、结论、行动召唤
6. 人物表现：身份、情绪、眼神、动作、表演节奏（看不出就明确说明）
7. 镜头与画面：景别、构图、光线、机位、色调、视觉焦点
8. 剪辑节奏：可能的切点、信息密度、节奏变化
9. 声音层：口播/对白、环境声、音乐作用（无法从帧判断声音细节时说明）
10. 爆点与传播机制：为什么可能让人停留、评论、收藏、转发
11. 可复用创作公式：写成“动机 → 钩子 → 展开 → 证明 → 反转/升华 → 收尾”形式
12. 可直接复制的下一条视频脚本框架
13. 具体优化建议：至少 8 条，按优先级排序
14. 推荐标题：5 个
15. 推荐标签：10 个以内

作品标题：{item.get('title') or ''}
作者：{item.get('author') or ''}
视频时长：{item.get('duration') or 0} 秒

完整文字：
{(full_text.get('text') or '')[:30000]}
'''
        content = [{'type': 'input_text', 'text': prompt}]
        for frame_path in frame_paths[:4]:
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
        version='4.2.0',
        full_text_supported=True,
        request_api_key_supported=True,
        env_ai_configured=bool(core.OPENAI_API_KEY and OpenAI is not None),
        analysis_supported=True,
        transcribe_model=core.OPENAI_TRANSCRIBE_MODEL or 'gpt-4o-mini-transcribe',
        analysis_model=core.OPENAI_ANALYSIS_MODEL or 'gpt-5-mini',
    )


@app.post('/api/text-full/<token>')
def text_full(token):
    started = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    key = _api_key(payload)
    try:
        result = _full_text(token, key)
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
        code = 'ai_key_required' if ('API Key' in message or 'api key' in message.lower()) and not key else 'full_text_failed'
        return jsonify(ok=False, error=message, error_code=code, elapsed=round(time.perf_counter() - started, 2)), 422


@app.post('/api/analyze-full/<token>')
def analyze_full(token):
    started = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    key = _api_key(payload)
    item = core._get_item(token)
    if not item:
        return jsonify(ok=False, error='解析结果已过期，请重新解析视频。', error_code='expired'), 410
    if not key or OpenAI is None:
        return jsonify(ok=False, error='视频内容分析需要 OpenAI API Key。请展开“AI 设置”填写后重试。', error_code='ai_key_required'), 422
    try:
        full_text = _full_text(token, key)
        result = _analyze_video(item, full_text, key)
        return jsonify(
            ok=True,
            **result,
            elapsed=round(time.perf_counter() - started, 2),
        )
    except Exception as exc:
        return jsonify(ok=False, error=str(exc).strip() or '视频分析失败', error_code='analysis_failed', elapsed=round(time.perf_counter() - started, 2)), 422
