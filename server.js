const express = require('express');
const path = require('path');
const { spawn } = require('child_process');

const app = express();
const PORT = process.env.PORT || 3000;
const PUBLIC_DIR = path.join(__dirname, 'public');
const INDEX_FILE = path.join(PUBLIC_DIR, 'index.html');

app.use(express.json({ limit: '2mb' }));

// 明确返回首页，避免云端根路径出现 Not Found
app.get('/', (req, res) => {
  res.sendFile(INDEX_FILE);
});

app.get('/api/health', (req, res) => {
  res.json({ ok: true, service: 'douyin-online-web', version: '3.2.0' });
});

app.post('/api/parse', (req, res) => {
  const text = String(req.body?.text || '');
  const rawUrl = text.match(/https?:\/\/[^\s<>'\"]+/)?.[0];
  if (!rawUrl) {
    return res.status(400).json({ ok: false, error: '未识别到抖音链接，请粘贴完整分享文案或链接。' });
  }

  const url = rawUrl.replace(/[，。！？、；：)）\]}]+$/, '');
  const args = [
    '--dump-single-json',
    '--no-playlist',
    '--no-warnings',
    '--socket-timeout', '20',
    url
  ];

  const p = spawn('yt-dlp', args);
  let out = '';
  let err = '';

  p.stdout.on('data', d => { out += d.toString(); });
  p.stderr.on('data', d => { err += d.toString(); });

  p.on('error', e => {
    return res.status(500).json({ ok: false, error: `解析器启动失败：${e.message}` });
  });

  p.on('close', code => {
    if (!out.trim()) {
      return res.status(422).json({
        ok: false,
        error: err.trim() || `解析失败（退出码 ${code}）`
      });
    }

    try {
      const j = JSON.parse(out);
      const videoUrl = j.url || j.requested_downloads?.[0]?.url || j.formats?.filter(f => f.url && f.vcodec !== 'none').at(-1)?.url || '';
      return res.json({
        ok: true,
        title: j.title || j.description || '',
        author: j.uploader || j.creator || j.channel || '',
        cover: j.thumbnail || '',
        url: videoUrl,
        webpage_url: j.webpage_url || url
      });
    } catch (e) {
      return res.status(500).json({ ok: false, error: `解析结果异常：${e.message}` });
    }
  });
});

// 静态资源放在 API 路由之后
app.use(express.static(PUBLIC_DIR));

// 非 API 的未知路径都回到首页，方便直接打开网址
app.use((req, res, next) => {
  if (req.path.startsWith('/api/')) return next();
  res.sendFile(INDEX_FILE);
});

// API 错误统一返回 JSON，避免前端再次遇到 HTML/XML 被当 JSON 解析
app.use((req, res) => {
  res.status(404).json({ ok: false, error: 'API 路径不存在' });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`douyin-online-web listening on ${PORT}`);
});
