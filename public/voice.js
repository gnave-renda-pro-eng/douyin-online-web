const EMOTIONS=[
{cat:'喜',name:'释然',level:1,scene:'压力解除、误会化解、危机过去后的松弛感',volume:'中低',speed:'稍慢',pitch:'平稳偏低',pause:'句间自然短停',ending:'句尾自然落下，少量轻扬',breath:'轻柔呼气，整体平稳',texture:'放松、克制、像终于卸下一口气',avoid:'不要明显大笑，不要突然抬高音量'},
{cat:'喜',name:'羞涩',level:1,scene:'被夸奖、被靠近、心意被点破时的含蓄开心',volume:'偏低',speed:'稍慢',pitch:'轻微上扬',pause:'句中留短停，像在斟酌',ending:'尾音放轻，偶尔略扬',breath:'偏轻，略带气音',texture:'开心但不完全说满，带一点不好意思',avoid:'不要连续发笑，不要突然变得外放'},
{cat:'喜',name:'欣慰',level:1,scene:'看到事情变好、对方平安或结果落定后的安心',volume:'中低',speed:'稍慢',pitch:'平稳',pause:'均匀短停',ending:'稳定收住',breath:'完整、平顺',texture:'温和、沉稳，有一种放心下来的暖意',avoid:'不要出现强重音，不要做成兴奋感'},
{cat:'喜',name:'雀跃',level:2,scene:'心情突然变轻快，明显开心但仍然自然',volume:'中等',speed:'略快',pitch:'偏亮，轻微上扬',pause:'停顿缩短，节奏轻快',ending:'轻轻扬起',breath:'顺畅、有弹性',texture:'明亮、活泼、自然外露',avoid:'不要变成尖叫或连续大笑'},
{cat:'喜',name:'窃喜',level:2,scene:'心里偷偷高兴，但不想让别人完全察觉',volume:'偏低',speed:'稍慢',pitch:'平稳略藏',pause:'句中短停',ending:'轻收，个别句尾带短气音笑',breath:'平稳、收着说',texture:'藏着笑意和一点小心思',avoid:'不要提高音量，不要连续发笑'},
{cat:'喜',name:'得意',level:3,scene:'觉得自己赢了、占了上风，带轻微炫耀或挑衅',volume:'中等',speed:'中等偏慢',pitch:'轻微上扬',pause:'短句间留一点空隙',ending:'句尾略挑，个别短句微拉长',breath:'稳定',texture:'自信、从容，带一点“我早知道”的味道',avoid:'不要大笑，不要夸张炫耀'},
{cat:'喜',name:'惊喜',level:3,scene:'先意外停住，随后迅速转为明显开心',volume:'中等',speed:'前慢后快',pitch:'由平转亮并上扬',pause:'开头先停半拍',ending:'句尾轻扬',breath:'略快，但保持清楚',texture:'先愣住，再亮起来',avoid:'不要从第一字就直接兴奋到顶'},
{cat:'喜',name:'狂喜',level:5,scene:'愿望实现、巨大好消息出现后，开心几乎压不住',volume:'偏高',speed:'明显加快',pitch:'高而明亮',pause:'停顿短，节奏外放',ending:'上扬但不拖腔',breath:'略急',texture:'兴奋、外放、控制力下降但仍能听清',avoid:'不要持续尖叫，不要让笑声盖过台词'},
{cat:'喜',name:'喜极而泣',level:5,scene:'久等结果终于出现，喜悦与哭意同时涌上来',volume:'中低',speed:'中慢',pitch:'轻微颤动',pause:'句间短停，像压住情绪',ending:'尾音轻颤',breath:'轻微不稳',texture:'笑意和哭意并存，情绪复杂',avoid:'不要变成单纯大哭，也不要连续大笑'},
{cat:'怒',name:'微怒',level:1,scene:'轻微不满，已经不高兴但还没有真正发火',volume:'中低',speed:'平稳',pitch:'偏低',pause:'停顿略短',ending:'快速收住，不上扬',breath:'平稳',texture:'克制的不悦，字变短、变重',avoid:'不要大喊，不要持续重读'},
{cat:'怒',name:'强忍',level:2,scene:'因为身份、场合或目的，必须把怒气压住',volume:'中低',speed:'偏慢',pitch:'压低',pause:'短暂停顿后马上接句',ending:'明显下压，迅速停住',breath:'收紧但不急促',texture:'怒气被强行封在声音里面',avoid:'不要突然爆发，不要让音量一路升高'},
{cat:'怒',name:'愤怒',level:4,scene:'怒意已经外露，但人物仍有基本控制力',volume:'中高',speed:'略快',pitch:'略抬高',pause:'句间变短',ending:'下压且变重',breath:'略急',texture:'咬字清楚、重音增强、有冲击力',avoid:'不要尖叫，不要拖长尾音'},
{cat:'怒',name:'讥讽',level:3,scene:'用反话、冷笑、挖苦表达攻击性不满',volume:'中等',speed:'中慢',pitch:'不高，局部轻挑',pause:'短句后留一点空白',ending:'句尾轻挑',breath:'稳定',texture:'冷、刺、像故意把话说给对方听',avoid:'冷笑最多一两处，不要演成大笑'},
{cat:'怒',name:'质问',level:4,scene:'连续追问、逼问真相、要求对方解释',volume:'中高',speed:'中快',pitch:'略上扬',pause:'问句之间停顿短',ending:'问句末端加重或上扬',breath:'略急',texture:'连续施压，问题一个接一个',avoid:'不要拖成慢长句，不要喊破音'},
{cat:'怒',name:'警告',level:3,scene:'不是发泄，而是压低声音让对方立刻停下',volume:'中低',speed:'放慢',pitch:'压低',pause:'句间短停',ending:'明显下压并快速停住',breath:'稳定',texture:'低声、明确、带控制和威慑',avoid:'不要急促，不要连续提高音量'},
{cat:'怒',name:'羞恼',level:3,scene:'被戳穿、难堪或当众冒犯后的急促恼怒',volume:'中等',speed:'略快',pitch:'略高',pause:'停顿短，衔接偏急',ending:'短促收住',breath:'略急',texture:'恼怒里混着不自在和防御感',avoid:'不要长时间上扬，不要喊成暴怒'},
{cat:'怒',name:'怨恨',level:4,scene:'长期积压的不甘、敌意和恨意，不是瞬间发火',volume:'中低',speed:'偏慢',pitch:'低沉',pause:'较长停顿',ending:'下沉，不上扬',breath:'偏沉',texture:'冷、重、带长期积压感',avoid:'不要突然喊叫，不要明亮轻快'},
{cat:'怒',name:'暴怒',level:5,scene:'控制力明显下降，冲突进入爆发点',volume:'高',speed:'快',pitch:'明显升高',pause:'停顿很短，短句连续',ending:'用力下压',breath:'急促',texture:'强烈、外放、带爆发力',avoid:'不要全程尖叫，不要让台词听不清'},
{cat:'悲',name:'低落',level:1,scene:'情绪下沉，没有明显哭意，只是整个人变得低沉',volume:'偏低',speed:'慢',pitch:'下沉',pause:'自然短停',ending:'自然落下',breath:'平稳但偏弱',texture:'安静、失落、没有力气争辩',avoid:'不要哭腔，不要突然抬高音量'},
{cat:'悲',name:'叹息',level:1,scene:'沉默、无奈、遗憾里带出轻轻的呼气',volume:'中低',speed:'偏慢',pitch:'偏低',pause:'句间略长',ending:'下落并留空',breath:'开头或句间轻呼气',texture:'无奈、疲惫、像话说到一半又咽回去',avoid:'不要连续喘气，不要变成明显哭声'},
{cat:'悲',name:'苦笑',level:2,scene:'明明难过，却用很短的笑压住真正情绪',volume:'中低',speed:'偏慢',pitch:'平低',pause:'停顿略长',ending:'尾音放轻',breath:'偏弱',texture:'笑意干、短、不明亮，底下是难过',avoid:'不要连续笑，不要让笑声盖住台词'},
{cat:'悲',name:'哽咽',level:3,scene:'悲伤堵在喉咙里，快哭出来但还在坚持说话',volume:'中低',speed:'偏慢',pitch:'发紧',pause:'句中停顿增多',ending:'轻微发颤',breath:'略不稳',texture:'声音像被堵住，句子不够顺',avoid:'不要完整大哭，不要让声音彻底断掉'},
{cat:'悲',name:'哭腔',level:3,scene:'声音里已经明显有哭意，但还能连贯说完整句子',volume:'中低',speed:'偏慢',pitch:'轻颤',pause:'句间短停',ending:'尾音颤动',breath:'轻微不稳，偶有轻吸气',texture:'有明显哭意但仍努力把话说完',avoid:'不要持续哭喊，不要每句话都断裂'},
{cat:'悲',name:'啜泣',level:4,scene:'已经小声哭出来，讲话夹着断续吸气和轻颤',volume:'偏低',speed:'慢',pitch:'低而不稳',pause:'短促吸气穿插句间',ending:'发颤',breath:'断续、轻抽气',texture:'小声哭，句子仍能辨认',avoid:'不要放声大哭，不要让抽气太长'},
{cat:'悲',name:'崩溃',level:5,scene:'悲伤彻底失控，大哭、断句和急促吸气同时出现',volume:'中高且不稳定',speed:'忽快忽慢',pitch:'起伏大',pause:'被哭声与吸气打断',ending:'明显颤抖',breath:'急促、断续',texture:'失控但仍保留能听懂的台词片段',avoid:'不要让整段只剩哭声，不要每个尾音都拖长'},
{cat:'悲',name:'沙哑',level:3,scene:'哭过、喊过或长时间压抑后，声音发干发哑',volume:'中低',speed:'偏慢',pitch:'偏低',pause:'短停',ending:'变轻、变虚',breath:'不足',texture:'干、哑、疲惫，不再继续大哭',avoid:'不要清脆明亮，不要突然提高音量'},
{cat:'悲',name:'麻木',level:4,scene:'悲伤消耗到极点后，反而几乎没有情绪起伏',volume:'低',speed:'很慢',pitch:'低平',pause:'较长停顿',ending:'直接落下',breath:'很轻但稳定',texture:'空、平、像情绪已经被掏空',avoid:'不要哭腔，不要明显哽咽，不要加入强重音'},
{cat:'惧',name:'心虚',level:1,scene:'害怕秘密暴露、被追问或露出破绽',volume:'偏低',speed:'略不稳定',pitch:'不明显升高',pause:'句中短停',ending:'快速收住',breath:'偏轻',texture:'不敢把话说满，像边说边观察对方',avoid:'不要大声，不要突然变得强硬'},
{cat:'惧',name:'惊疑',level:2,scene:'察觉不对劲，但还不能确认，边害怕边试探',volume:'中低',speed:'偏慢',pitch:'轻微上扬',pause:'明显短停，像边想边说',ending:'轻扬但不拖长',breath:'偏轻',texture:'不确定、警觉、试探',avoid:'不要急着喊叫，不要突然加快太多'},
{cat:'惧',name:'吸气',level:2,scene:'突然受惊，第一反应先吸住一口气再开口',volume:'偏低',speed:'偏慢',pitch:'发紧',pause:'开头短促吸气后停半拍',ending:'轻收',breath:'短、紧',texture:'先被吓住，再勉强说话',avoid:'不要直接尖叫，不要让吸气过长'},
{cat:'惧',name:'颤抖',level:3,scene:'害怕已经影响声音稳定性，但还能继续表达',volume:'中低',speed:'偏慢或断续',pitch:'不稳定',pause:'句中短停',ending:'轻微发颤',breath:'不稳',texture:'音量轻微起伏，声音像控制不住地抖',avoid:'不要大喊，不要夸张成哭腔'},
{cat:'惧',name:'急喘',level:3,scene:'受到惊吓、奔跑、逃离或高度紧张后的急促呼吸',volume:'中等',speed:'偏快',pitch:'略高',pause:'句间插入短促喘气',ending:'不拖长',breath:'明显急促',texture:'身体反应已经进入声音里',avoid:'不要让喘气盖住台词，不要变成尖叫'},
{cat:'惧',name:'惊呼',level:4,scene:'被突然吓到，短促喊出声但没有持续尖叫',volume:'开头瞬间偏高',speed:'短促',pitch:'快速上扬',pause:'喊出后短停',ending:'随后快速回落',breath:'略急',texture:'瞬间被吓到的爆点反应',avoid:'喊声要短，不要持续高声'},
{cat:'惧',name:'求饶',level:4,scene:'处于弱势，害怕伤害继续，只能放低姿态请求',volume:'偏低',speed:'偏快但发软',pitch:'略下滑',pause:'句间短停',ending:'向下收住',breath:'不稳',texture:'软、急、带求生感',avoid:'不要强硬，不要喊成命令'},
{cat:'惧',name:'尖叫',level:5,scene:'受到强烈惊吓，声音突然变尖、变高并明显外放',volume:'高',speed:'爆发后不稳定',pitch:'高而尖',pause:'尖叫后短停再继续',ending:'高点后快速回落',breath:'急促吸气',texture:'强烈惊吓的瞬间外放',avoid:'不要整段都尖叫，不要让声音完全破掉'},
{cat:'惧',name:'崩乱',level:5,scene:'恐惧彻底失控，语速、音量、气息和句子结构全部变乱',volume:'忽高忽低',speed:'忽快忽慢',pitch:'大幅起伏',pause:'句子断开，急促停顿',ending:'不稳定',breath:'急促、凌乱',texture:'慌乱喊声与断句交织，控制力很低',avoid:'不要每句都尖叫，保留能听清的说话部分'}
];

let activeCat='全部';
let activeLevel=0;
let current=EMOTIONS[0];

const $=s=>document.querySelector(s);
const grid=$('#emotionGrid');
const promptOutput=$('#promptOutput');
const fullOutput=$('#fullOutput');
const dialogueInput=$('#dialogueInput');
const toast=$('#toast');

function makePrompt(e){
  return `【人物声音情绪：${e.name}】\n适用状态：${e.scene}。\n声音控制：音量保持${e.volume}；语速${e.speed}；音调${e.pitch}；${e.pause}；${e.ending}；气息${e.breath}。\n表演质感：${e.texture}。\n限制：${e.avoid}。整段始终以角色当下动机为核心，不要为了“表现情绪”而机械夸张，确保台词内容清楚、自然、有层次。`;
}

function showToast(msg='已复制'){
  toast.textContent=msg;toast.classList.add('show');clearTimeout(showToast.t);showToast.t=setTimeout(()=>toast.classList.remove('show'),1400);
}
async function copyText(text){
  if(!text){showToast('没有可复制内容');return}
  try{await navigator.clipboard.writeText(text);showToast('已复制到剪贴板')}catch{showToast('复制失败，请手动复制')}
}
function levelPips(level){return `<span class="levelPips">${[1,2,3,4,5].map(n=>`<i class="${n<=level?'on':''}"></i>`).join('')}</span>`}
function filtered(){
  const q=$('#emotionSearch').value.trim().toLowerCase();
  return EMOTIONS.filter(e=>(activeCat==='全部'||e.cat===activeCat)&&(activeLevel===0||e.level===activeLevel)&&(!q||`${e.name}${e.scene}${e.texture}`.toLowerCase().includes(q)));
}
function renderGrid(){
  const list=filtered();
  grid.innerHTML=list.length?list.map(e=>`<button class="emotionCard ${e.name===current.name?'active':''}" data-name="${e.name}"><div class="top"><span class="catDot">${e.cat}</span>${levelPips(e.level)}</div><h3>${e.name}</h3><p>${e.scene}</p></button>`).join(''):'<div style="grid-column:1/-1;color:#777;padding:28px;text-align:center">没有匹配的情绪</div>';
  grid.querySelectorAll('.emotionCard').forEach(btn=>btn.addEventListener('click',()=>selectEmotion(EMOTIONS.find(e=>e.name===btn.dataset.name))));
}
function selectEmotion(e){
  if(!e)return;current=e;
  $('#currentBadge').textContent=e.cat;
  $('#currentName').textContent=e.name;
  $('#currentScene').textContent=e.scene;
  $('#paramGrid').innerHTML=[['音量',e.volume],['语速',e.speed],['音调',e.pitch],['停顿',e.pause],['尾音',e.ending],['气息',e.breath]].map(([k,v])=>`<div class="param"><span>${k}</span><b>${v}</b></div>`).join('');
  promptOutput.value=makePrompt(e);
  fullOutput.value='';
  renderGrid();
}
function buildFull(){
  const dialogue=dialogueInput.value.trim();
  const base=makePrompt(current);
  fullOutput.value=dialogue?`${base}\n\n【需要生成的角色台词】\n${dialogue}`:`${base}\n\n【需要生成的角色台词】\n（请在上方输入角色台词）`;
  if(!dialogue)showToast('请先输入角色台词');
}

document.querySelectorAll('#categoryTabs button').forEach(btn=>btn.addEventListener('click',()=>{
  document.querySelectorAll('#categoryTabs button').forEach(b=>b.classList.remove('active'));btn.classList.add('active');activeCat=btn.dataset.cat;renderGrid();
}));
document.querySelectorAll('.levelFilter button').forEach(btn=>btn.addEventListener('click',()=>{
  document.querySelectorAll('.levelFilter button').forEach(b=>b.classList.remove('active'));btn.classList.add('active');activeLevel=Number(btn.dataset.level);renderGrid();
}));
$('#emotionSearch').addEventListener('input',renderGrid);
$('#randomEmotion').addEventListener('click',()=>{const pool=filtered();selectEmotion(pool[Math.floor(Math.random()*pool.length)]||EMOTIONS[Math.floor(Math.random()*EMOTIONS.length)]);document.querySelector('.composer').scrollIntoView({behavior:'smooth',block:'start'});});
$('#copyCurrent').addEventListener('click',()=>copyText(promptOutput.value));
$('#copyPrompt').addEventListener('click',()=>copyText(promptOutput.value));
$('#buildFull').addEventListener('click',buildFull);
$('#copyFull').addEventListener('click',()=>copyText(fullOutput.value));
$('#clearDialogue').addEventListener('click',()=>{dialogueInput.value='';fullOutput.value='';showToast('已清空')});

dialogueInput.addEventListener('input',()=>{if(fullOutput.value)buildFull()});
selectEmotion(current);
