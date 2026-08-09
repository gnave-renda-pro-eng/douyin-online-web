const express = require('express');
const path = require('path');
const { spawn } = require('child_process');

const app = express();
app.use(express.json({limit:'2mb'}));
app.use(express.static(path.join(__dirname,'public')));

app.get('/api/health',(req,res)=>res.json({ok:true,service:'douyin-online-web'}));

app.post('/api/parse', async (req,res)=>{
  const text = String(req.body.text || '');
  const url = text.match(/https?:\/\/[^\s]+/)?.[0];
  if(!url) return res.status(400).json({ok:false,error:'未识别到视频链接'});

  const args=['--dump-single-json','--no-playlist',url];
  const p=spawn('yt-dlp',args);
  let out='',err='';
  p.stdout.on('data',d=>out+=d);
  p.stderr.on('data',d=>err+=d);
  p.on('close',()=>{
    if(!out) return res.json({ok:false,error:err||'解析失败'});
    try{
      const j=JSON.parse(out);
      res.json({ok:true,title:j.title||'',author:j.uploader||'',cover:j.thumbnail||'',url:j.url||''});
    }catch(e){res.json({ok:false,error:'解析结果异常'});}
  });
});

app.listen(process.env.PORT||3000,()=>console.log('server running'));
