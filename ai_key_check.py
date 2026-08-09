from flask import jsonify, request

import enhanced

app = enhanced.app
OpenAI = enhanced.OpenAI


def _friendly_key_error(exc):
    msg = str(exc).strip() or 'AI Key 验证失败'
    low = msg.lower()
    if '401' in low or 'invalid_api_key' in low or 'incorrect api key' in low or 'authentication' in low:
        return 'AI Key 无效或已失效，请检查后重新填写。', 'invalid_key', 401
    if '429' in low or 'quota' in low or 'billing' in low or 'insufficient_quota' in low:
        return 'AI Key 可以识别，但当前项目额度/计费不可用，请检查 API 账户额度。', 'quota_unavailable', 429
    if '403' in low or 'permission' in low or 'forbidden' in low:
        return 'AI Key 已识别，但当前项目权限不足，请检查项目或模型权限。', 'permission_denied', 403
    return 'AI Key 验证失败：' + msg, 'key_test_failed', 422


@app.post('/api/test-ai-key')
def test_ai_key():
    payload = request.get_json(silent=True) or {}
    request_key = str(payload.get('api_key') or '').strip()
    key = request_key or str(enhanced.core.OPENAI_API_KEY or '').strip()
    if not key:
        return jsonify(ok=False, error='尚未填写 AI Key。', error_code='ai_key_required'), 422
    if OpenAI is None:
        return jsonify(ok=False, error='服务器 OpenAI SDK 未正确加载。', error_code='sdk_unavailable'), 503
    try:
        client = OpenAI(api_key=key)
        # 只做认证/项目可访问性检查，不发起转写或内容生成，不产生模型推理调用。
        client.models.list()
        return jsonify(
            ok=True,
            version='4.4.0',
            source='page' if request_key else 'environment',
            message='AI Key 验证成功：完整版语音转写和专业视频分析已可使用。',
        )
    except Exception as exc:
        message, code, status = _friendly_key_error(exc)
        return jsonify(ok=False, error=message, error_code=code), status


@app.get('/api/advanced-health-v2')
def advanced_health_v2():
    return jsonify(
        ok=True,
        version='4.4.0',
        full_text_supported=True,
        request_api_key_supported=True,
        api_key_test_supported=True,
        env_ai_configured=bool(enhanced.core.OPENAI_API_KEY and OpenAI is not None),
        analysis_supported=True,
        chunked_transcription=True,
        transcribe_chunk_seconds=enhanced.TRANSCRIBE_CHUNK_SECONDS,
        transcribe_model=enhanced.core.OPENAI_TRANSCRIBE_MODEL or 'gpt-4o-mini-transcribe',
        analysis_model=enhanced.core.OPENAI_ANALYSIS_MODEL or 'gpt-5-mini',
    )
