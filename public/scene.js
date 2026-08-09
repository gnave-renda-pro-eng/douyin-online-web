const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const eras=['先秦','秦朝','西汉','东汉','三国','晋朝','南北朝','隋朝','唐朝','五代十国','北宋','南宋','元朝','明朝','清朝'];
const places=['皇宫大殿','宫廷长廊','长安朱雀大街','贵族府邸','酒楼','客栈','书房','庭院','军营','战场','山道','寺院','竹林','渡口','江边','城楼','边关','监牢'];
const times=['清晨','上午','正午','下午','黄昏','夜晚','深夜'];
const seasons=['春','夏','秋','冬'];
const weathers=['晴','阴','薄雾','小雨','暴雨','大雪','风沙','无特殊天气'];
const storyStages=['平静','初入环境','试探','对峙','秘密会谈','权谋博弈','宴会','离别','重逢','追杀','逃亡','审讯','战斗前','战斗中','战争'];
const architecture={
'先秦':'先秦夯土台基、木构梁架、茅瓦或早期瓦面、青铜与漆木器物体系，空间朴素雄浑。','秦朝':'秦代大型夯土台基、深色木构、瓦顶、宽阔宫院与青铜黑铁器物，整体严整厚重。','西汉':'汉代高台木构、交错院落、灰瓦、朱色木构与青砖石阶，尺度庄重。','东汉':'东汉木构院落、瓦顶、门阙、石阶与漆木器具，真实克制。','三国':'汉末三国木构府署、军营、城墙与民居体系，夯土、木材、灰瓦和粗粝军用材质并存。','晋朝':'魏晋木构院落、园林、廊庑与文士空间，灰瓦、木梁、竹帘和石阶，清雅但不仙侠。','南北朝':'南北朝木构、石窟寺院、城郭与府邸并存，地域差异真实但工艺属于同一时代。','隋朝':'隋代整齐木构宫室、城郭、宽街、灰瓦与石台基，向唐代过渡但不过度华丽。','唐朝':'唐代大型木构建筑体系，大出檐、斗拱、朱红立柱、深色梁架、灰黑瓦顶、石质台基与宽阔院落；禁止明清宫殿化。','五代十国':'晚唐至五代木构、城郭与府院系统，尺度略收敛，保留灰瓦、木梁与厚重城防。','北宋':'北宋木构城市、瓦舍店铺、官署宅院、桥梁与精细市井空间，灰瓦木窗、青石地面，克制雅正。','南宋':'南宋江南木构、临水街巷、宅院、廊桥与园林，青瓦、白灰墙、深木梁与湿润石板。','元朝':'元代大都宫城、草原与中原融合的建筑和器物体系，木构、毡帐、砖石城墙按场景合理出现。','明朝':'明代木构宫室、城墙、府邸与街巷体系，砖石比例上升，灰瓦或身份相符琉璃瓦，结构制度明确。','清朝':'清代宫廷、王府、官署与旗人生活空间，彩绘、硬山歇山屋顶、砖木与院落制度符合身份。'};
const eraColor={
'唐朝':'深木棕、玄黑、土灰、暗朱红为环境主色，青灰、米白、玉色为辅助色，旧铜、暗金、黑铁作为金属色。',
'北宋':'墨灰、青灰、茶褐、米白为主，少量黛青与暗红点缀，整体更清润克制。',
'南宋':'青灰、湿石色、米白、墨绿、木褐为主，低饱和江南空气感。',
'三国':'土褐、铁黑、暗红、灰青为主，材质粗粝，战争与政权更替感明显。',
'明朝':'玄青、深红、墨黑、灰砖色为主，金属与织物颜色克制。',
'清朝':'深青、玄黑、暗红、灰褐为主，身份色彩明确但避免戏曲化高饱和。'};
const negative='不同世界，不同朝代，建筑朝代混乱，服装朝代混乱，人物不属于同一电影，人物画风不一致，人物摄影风格不同，角色变脸，角色年龄漂移，角色肤色变化，角色骨相变化，同脸不同人物，不同脸同一人物，人物身份交换，服装随机变化，发型随机变化，武器随机变化，背景随机变化，场景重构，建筑风格漂移，色温漂移，灯光方向漂移，时间变化，天气随机变化，现代建筑，现代家具，现代物品，现代服饰，电灯，玻璃幕墙，塑料，现代道路，仙侠，玄幻，修仙，魔法，灵气，发光武器，游戏场景，游戏UI，CG，3D游戏人物，动漫，漫画，插画，二次元，网红滤镜，美容磨皮，过度HDR，过饱和，假景深，人物悬浮，人物贴图感，背景贴图，错误透视，人体比例异常，多手，多腿，多指，文字，字幕，logo，水印，二维码。';
let state={tab:'full',world:true,character:true,continuity:true,history:true,negative:true,imported:null},out={positive:'',negative:'',full:''};
function opts(el,arr,val){el.innerHTML=arr.map(x=>`<option${x===val?' selected':''}>${x}</option>`).join('')}
opts($('#era'),eras,'唐朝');opts($('#place'),places,'长安朱雀大街');opts($('#time'),times,'清晨');opts($('#season'),seasons,'秋');opts($('#weather'),weathers,'薄雾');opts($('#storyStage'),storyStages,'初入环境');
function ageTexture(age){age=+age||25;if(age<=20)return'年轻自然皮肤，毛孔较细，保留细小皮纹与真实唇纹，不做幼态磨皮。';if(age<=30)return'真实毛孔、鼻翼纹理、少量眼下纹理和轻微表情纹，皮肤干净但不磨皮。';if(age<=45)return'眼角与额头出现自然浅纹，面部皮肤纹理更加明显，保留成熟年龄感。';return'保留自然皱纹、眼袋、法令纹和额头纹，不做AI强行年轻化。'}
function eraVisual(e){return architecture[e]||`${e}真实东方木构、城郭、府邸、民居、道路与器物体系，严格遵守时代工艺边界。`}
function colorVisual(e){return eraColor[e]||'低饱和土灰、木褐、墨色、米白与身份色形成统一历史电影调色，金属为旧铜、黑铁或克制暗金。'}
function importedText(){const d=state.imported;if(!d)return'';return `已导入角色资料：${d.name||'角色'}，${d.age||''}岁，${d.gender||''}，${d.era||''}，身份${d.role||''}，剧情定位${d.relation||'未填写'}，骨相${d.bone||'自动匹配'}，色彩方案${d.palette||'自动匹配'}。${d.temperament?`人物核心气质：${d.temperament}。`:''}${d.face?`既定脸型：${d.face}。`:''}${d.wardrobe?`既定服装：${d.wardrobe}。`:''}`}
function generate(){const e=$('#era').value,wid=$('#worldId').value.trim()||`WORLD_${e}_001`,region=$('#region').value.trim(),worldType=$('#worldType').value,worldDna=$('#worldDna').value.trim(),scene=$('#sceneName').value.trim()||'未命名场景',place=$('#place').value,time=$('#time').value,season=$('#season').value,weather=$('#weather').value,env=$('#environment').value.trim(),characters=$('#characters').value.trim(),relations=$('#relations').value.trim(),blocking=$('#blocking').value.trim(),stage=$('#storyStage').value,intensity=$('#intensity').value,plot=$('#plot').value.trim(),motives=$('#motives').value.trim(),perf=$('#performance').value.trim(),shot=$('#shot').value,lens=$('#lens').value,ratio=$('#ratio').value,camera=$('#camera').value.trim(),lighting=$('#lighting').value.trim();
const roleAge=state.imported?.age;const p=[];
p.push(`8K超高清真实电影摄影，中国古代历史电影场景，${worldType}，东方历史现实主义世界，超写实真人演员质感，真实电影摄影机成像，真实东方古代建筑、服装、兵器、器物与生活环境。画幅${ratio}，印刷级细节但保持真实摄影质感。`);
p.push(`世界ID：${wid}。本场景严格继承已经建立的世界观Bible。历史时期为${e}，地域为${region||'与人物所属政权和文化圈一致'}。世界视觉DNA：${worldDna||colorVisual(e)}。所有地点、建筑、群众、服装、道具、兵器、材质、灯光与调色都必须属于同一时代、同一国家、同一电影美术体系。`);
p.push(`历史建筑与环境制度：${eraVisual(e)} ${colorVisual(e)} 真实木材具有细小磨损与纹理，石材边缘存在自然使用痕迹，金属存在氧化与微划痕，布料具有纤维、褶皱和真实重量。禁止空置影视城感和游戏地图感。`);
p.push(`场景：${scene}。地点：${place}。时间：${time}。季节：${season}。天气：${weather}。${env||'环境中存在符合时代的自然生活痕迹、远近层次和合理背景人物活动，不堆砌无意义装饰。'}`);
p.push(`出场人物：${characters||'按照既定角色库选择人物进入场景。'}。${importedText()} ${roleAge?ageTexture(roleAge):'所有人物保留各自真实年龄皮肤与细微不对称。'} 人物关系：${relations||'依据剧情保持真实社会距离和身份秩序。'} 人物位置与场面调度：${blocking||'人物站位遵循剧情关系、空间逻辑与画面构图，不机械排排站。'}`);
p.push(`剧情阶段：${stage}。核心剧情：${plot||'人物在当前环境中完成一个清晰且可观察的剧情动作。'} 人物目的与动机：${motives||'每个角色必须有明确行动目的，表演由动机驱动而不是直接摆出情绪。'}`);
p.push(`人物表演采用“动机 → 眼神 → 呼吸 → 脸部 → 身体 → 手部 → 声音状态 → 情绪收尾”的完整链条，情绪强度为${intensity}。${perf||'先让视线产生变化，再出现呼吸和面部细微变化，随后身体与手部动作配合，最后用眼神或姿态完成情绪收尾，避免夸张舞台表演。'}`);
p.push(`镜头设计：${lens}电影镜头，${shot}。${camera||'摄影机高度、距离和人物视线关系必须真实，构图服务人物关系和环境叙事。'} 真实透视，真实景深，不允许所有区域同时锐利。人物与环境必须产生真实接触阴影、环境色反射与空气透视，禁止人物贴图感。`);
p.push(`光线设计：${lighting||'采用自然主义电影布光，所有光线必须有现实来源；白天来自天空、窗户或庭院，夜晚来自油灯、烛火、宫灯或月光。'} 统一曝光、白平衡、色温、光线方向和阴影软硬度，真实高光滚降，自然肤色，无美容平光、无网红滤镜、无极端青橙调色。`);
if(state.world)p.push(`WORLD CONSISTENCY LOCK：${wid}为本项目唯一世界身份。后续任何镜头不得重新设计时代、建筑工艺、主要材质、色彩体系、摄影体系、灯光体系和调色体系。不同地点允许空间功能变化，但必须像由同一个历史电影美术部门完成。`);
if(state.character)p.push('CHARACTER IDENTITY LOCK：禁止重新设计人物。所有已建立角色进入任何场景必须保持同一脸型、同一骨相、同一五官比例、同一年龄、同一肤色、同一发际线、同一基础发型、同一身份和同一身体比例。只允许情绪、眼神、姿态、动作、衣服褶皱、环境光、汗水、灰尘、雨水等剧情性变化。');
if(state.continuity)p.push('SHOT CONTINUITY LOCK：如果生成同一场戏的连续镜头，地点结构、人物服装、发型、道具位置、时间、天气、主光方向、环境色和空间轴线必须持续一致。每个镜头只能改变景别、机位、焦段、人物动作阶段和构图，不得重建场景。');
if(state.history)p.push(`历史考据模式开启：所有建筑、冠帽、服装、兵器、交通工具、家具、餐具、文书和群众服饰必须符合${e}的历史制度与工艺，禁止跨朝代混搭，禁止使用后世最典型的影视符号替代当前时代。`);
out.positive=p.join('\n\n');out.negative=negative;out.full=out.positive+(state.negative?'\n\n负面提示词：'+negative:'');$('#worldTitle').textContent=wid;$('#mEra').textContent=e;$('#mScene').textContent=scene;$('#mTime').textContent=time+' · '+weather;$('#mShot').textContent=lens+' · '+shot;render()}
function render(){const t=state.tab==='positive'?out.positive:state.tab==='negative'?out.negative:out.full;$('#prompt').textContent=t;$('#count').textContent=t.length.toLocaleString()+' 字符'}
function toast(t){const e=$('#toast');e.textContent=t;e.classList.add('show');clearTimeout(window.__st);window.__st=setTimeout(()=>e.classList.remove('show'),1500)}
async function copy(t){try{await navigator.clipboard.writeText(t)}catch{const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();document.execCommand('copy');a.remove()}toast('已复制')}
function importRole(){try{const d=JSON.parse(localStorage.getItem('historyStudio'));if(!d){toast('角色工坊还没有保存角色');return}state.imported=d;$('#era').value=d.era||$('#era').value;$('#characters').value=`${d.name||'角色'}｜${d.age||''}岁｜${d.era||''}｜${d.role||''}｜${d.bone||'自动匹配'}｜${d.palette||'自动配色'}`;$('#importInfo').textContent=`已导入：${d.name||'角色'} · ${d.age||''}岁 · ${d.era||''} · ${d.role||''} · ${d.bone||'自动骨相'}`;if(d.era==='唐朝'&&!$('#region').value.trim())$('#region').value='唐代长安及其政治文化圈';generate();toast('角色已导入并锁定')}catch{toast('角色数据读取失败')}}
function save(){const ids=['worldId','era','region','worldType','worldDna','sceneName','place','time','season','weather','environment','characters','relations','blocking','storyStage','intensity','plot','motives','performance','shot','lens','ratio','camera','lighting'];const d={};ids.forEach(id=>d[id]=$('#'+id).value);d.state={world:state.world,character:state.character,continuity:state.continuity,history:state.history,negative:state.negative};localStorage.setItem('sceneStudio',JSON.stringify(d));toast('场景已保存到浏览器')}
function load(){try{const d=JSON.parse(localStorage.getItem('sceneStudio'));if(!d)return;Object.keys(d).forEach(k=>{const el=$('#'+k);if(el&&d[k]!=null)el.value=d[k]});if(d.state)Object.keys(d.state).forEach(k=>state[k]=d.state[k]);$$('.switch').forEach(x=>x.classList.toggle('on',state[x.dataset.key]));generate()}catch{}}
function exportTxt(){const b=new Blob([out.full],{type:'text/plain;charset=utf-8'}),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download=($('#sceneName').value||'历史场景')+'_同世界场景提示词.txt';a.click();URL.revokeObjectURL(u)}
$$('input,select,textarea').forEach(x=>x.addEventListener('input',generate));$$('.switch').forEach(x=>x.onclick=()=>{const k=x.dataset.key;state[k]=!state[k];x.classList.toggle('on',state[k]);generate()});$$('.tab').forEach(x=>x.onclick=()=>{state.tab=x.dataset.tab;$$('.tab').forEach(y=>y.classList.toggle('on',x===y));render()});$('#generate').onclick=()=>{generate();toast('场景提示词已生成')};$('#importRole').onclick=importRole;$('#save').onclick=save;$('#copy').onclick=()=>copy(state.tab==='positive'?out.positive:state.tab==='negative'?out.negative:out.full);$('#copyFull').onclick=()=>copy(out.full);$('#export').onclick=exportTxt;$('#clear').onclick=()=>{localStorage.removeItem('sceneStudio');location.reload()};generate();setTimeout(load,20);