'use strict';

// Responses are scoped to the signed-in user, page visit and selected conversation.
const assistantUI={epoch:0,view:0,owner:null,activeId:null,messages:[],history:[],status:null,busy:false,loading:false,draft:'',error:'',controller:null,progress:''};
function assistantOwner(){return S.auth?String(S.auth.id)+':'+String(S.auth.username):null}
function assistantVisible(){return page==='guide'&&!!document.querySelector('#assistant-root')}
function assistantCurrent(epoch,view){return epoch===assistantUI.epoch&&assistantUI.owner===assistantOwner()&&assistantVisible()&&(view===undefined||view===assistantUI.view)}
function assistantDate(value){if(!value)return '';const date=new Date(value);return Number.isNaN(date.getTime())?'':date.toLocaleString('zh-CN',{hour12:false})}
function assistantMode(mode){return {model:'模型结合知识库回答',retrieval_only:'知识库检索结果',insufficient_evidence:'知识库依据不足',clarification_needed:'需要确认对象',service_error:'模型服务暂时不可用'}[mode]||'知识库问答'}
function assistantIsAdmin(){return S.auth?.role==='admin'}
async function assistantPage(){
 assistantUI.controller?.abort();
 const epoch=++assistantUI.epoch,owner=assistantOwner();
 if(owner!==assistantUI.owner){assistantUI.owner=owner;assistantUI.activeId=null;assistantUI.messages=[];assistantUI.history=[];assistantUI.status=null;assistantUI.draft=''}
 assistantUI.messages=assistantUI.messages.filter(item=>!item.pending);assistantUI.busy=false;assistantUI.loading=false;assistantUI.error='';const initialView=++assistantUI.view,initialConversation=assistantUI.activeId;
 if(!S.auth){$('#content').innerHTML=title('AI ASSISTANT','AI智能问答助手','根据售后经验、操作规范与技术经验查找处理办法。')+'<section class="panel"><h2>登录后使用智能问答</h2><p>登录账号可提问、查看自己的对话并反馈回答效果。管理员可以更新问答知识库。</p></section>';return}
 $('#content').innerHTML=title('AI ASSISTANT','AI智能问答助手','检索售后经验、操作规范与技术经验，回答附参考来源。')+`<div id="assistant-root"><div class="assistant-tools"><details class="assistant-status-details"><summary><strong>知识库状态</strong><span id="assistant-status-summary">正在读取…</span></summary><section id="assistant-status" class="assistant-status" aria-live="polite">正在读取知识库状态…</section></details>${assistantIsAdmin()?'<details class="panel assistant-management"><summary><strong>知识库管理</strong><span>导入与更新</span></summary><p>已解决且有处理方案或经验的售后记录、操作规范与技术经验会自动进入本地知识库。也可以直接导入已有的问答 CSV 或 Excel，不需要绑定项目和产品。</p><div class="toolbar"><label class="assistant-file-label">选择知识库文件<input id="assistant-knowledge-file" type="file" accept=".csv,.xlsx"></label><button id="assistant-knowledge-import" class="primary">导入问答知识</button><button id="assistant-rebuild">更新知识索引</button></div><p class="subtle">支持 CSV、XLSX，单文件最多 5 MB。可使用“问题类型 / 问题描述 / 解决方案”表头。模型连接由服务器配置。</p><p id="assistant-management-message" role="status"></p></details>':''}</div><div class="assistant-workspace"><div class="assistant-sidebar" role="region" aria-label="对话列表"><button id="assistant-new" class="primary">＋ 新建对话</button><h2>我的对话</h2><div id="assistant-history" aria-label="历史对话"></div></div><section class="assistant-chat" aria-label="智能问答"><div id="assistant-messages" class="assistant-messages" aria-live="polite"></div><form id="assistant-form" class="assistant-composer"><label for="assistant-question">描述你遇到的问题</label><textarea id="assistant-question" maxlength="4000" rows="2" placeholder="例如：检测圆环时出现漏检，应从哪些位置排查？"></textarea><div class="assistant-compose-footer"><span class="subtle">Enter 发送 · Shift + Enter 换行；回答请结合现场确认。</span><div><button type="button" id="assistant-stop" hidden>停止回答</button> <button type="submit" id="assistant-send" class="primary">发送</button></div></div><p id="assistant-error" class="assistant-error" role="alert"></p></form></section></div></div>`;
 $('#assistant-new').onclick=assistantNewConversation;
 $('#assistant-form').onsubmit=assistantSend;
 $('#assistant-stop').onclick=()=>assistantUI.controller?.abort();
 $('#assistant-question').value=assistantUI.draft;
 $('#assistant-question').oninput=e=>{assistantUI.draft=e.target.value};
 $('#assistant-question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#assistant-form').requestSubmit()}};
 if(assistantIsAdmin()){$('#assistant-knowledge-import').onclick=assistantImportKnowledge;$('#assistant-rebuild').onclick=assistantRebuild}
 assistantRenderMessages();assistantRenderHistory();
 const outcomes=await Promise.allSettled([request('/api/assistant/status'),request('/api/assistant/history')]);
 if(!assistantCurrent(epoch))return;
 if(outcomes[0].status==='fulfilled'){assistantUI.status=outcomes[0].value;assistantRenderStatus()}else{$('#assistant-status').textContent='知识库状态读取失败：'+outcomes[0].reason.message;$('#assistant-status-summary').textContent='状态暂不可用'}
 if(assistantUI.view===initialView){if(outcomes[1].status==='fulfilled'){assistantUI.history=outcomes[1].value.conversations||[];assistantRenderHistory()}else $('#assistant-history').textContent='对话记录读取失败：'+outcomes[1].reason.message}
 if(initialConversation&&assistantUI.view===initialView&&assistantUI.activeId===initialConversation)await assistantSelectConversation(initialConversation);
}
function assistantRenderStatus(){
 if(!assistantVisible())return;const status=assistantUI.status||{},configured=!!status.configured;
 $('#assistant-status-summary').textContent=(configured?(status.model||status.provider||'模型服务已配置'):'仅检索')+' · '+(status.documents??0)+' 个知识片段';
 $('#assistant-status').innerHTML=`<div class="assistant-status-heading"><strong>${configured?'模型服务已配置':'当前为知识库检索模式'}</strong><span class="pill">${esc(configured?(status.model||status.provider||'已配置模型'):'未连接生成模型')}</span></div><p>${configured?'提问后将检索售后经验、操作规范和技术经验，再由模型组织回答。':'尚未配置模型服务，将直接展示匹配的知识片段；不会生成模型回答。'}</p><div class="assistant-metrics"><span>知识片段 <b>${esc(status.documents??0)}</b></span><span>售后经验 <b>${esc(status.after_sales_count??0)}</b></span><span>技术经验 <b>${esc(status.technical_experience_count??0)}</b></span><span>问答知识 <b>${esc(status.knowledge_count??0)}</b></span><span>索引版本 <b>${esc(status.index_version??'—')}</b></span></div>${status.dirty?'<p class="assistant-alert">知识库有更新，下次提问时会自动同步；管理员也可立即更新索引。</p>':''}`;
}
function assistantRenderHistory(){
 if(!assistantVisible())return;$('#assistant-history').innerHTML=assistantUI.history.length?assistantUI.history.map(item=>`<button class="assistant-history-item ${String(item.id)===String(assistantUI.activeId)?'active':''}" data-conversation="${esc(item.id)}" title="${esc(item.title||'未命名对话')}"><strong>${esc(item.title||'未命名对话')}</strong><small>${esc(assistantDate(item.updated_at||item.created_at))}</small></button>`).join(''):'<p class="subtle">还没有对话。可以从一个具体的现场问题开始。</p>';
 $('#assistant-history').querySelectorAll('[data-conversation]').forEach(button=>{button.onclick=()=>assistantSelectConversation(button.dataset.conversation)});
}
function assistantSources(sources){
 if(!Array.isArray(sources)||!sources.length)return '';
 return `<details class="assistant-sources"><summary>参考依据 · ${sources.length} 条</summary>${sources.map((source,index)=>`<article class="assistant-source"><strong>${index+1}. ${esc(source.title||'知识片段')}</strong><small>${esc(source.source_type==='after_sales'?'售后经验':source.source_type==='technical_experiences'?'操作规范与技术经验':source.source_type==='knowledge_graph'?'知识关联与测试依据':source.source_type==='knowledge'?'问答知识':'知识库')} ${source.source_id!=null?'#'+esc(source.source_id):''}</small><p>${esc(source.text||'')}</p></article>`).join('')}</details>`;
}
function assistantMessage(item,index){
 const user=`<article class="assistant-message assistant-user"><div class="assistant-message-label">你</div><div class="assistant-message-text">${esc(item.question||'')}</div></article>`;
 if(item.pending&&!item.streaming)return user;
 const feedback=item.id!=null?`<div class="assistant-feedback"><span>这次回答有帮助吗？</span>${['helpful','unhelpful'].map(rating=>`<button type="button" data-feedback-index="${index}" data-rating="${rating}" class="${item.feedback?.rating===rating||item.feedback===rating?'active':''}">${rating==='helpful'?'有帮助':'需改进'}</button>`).join('')}<span class="assistant-feedback-status" id="assistant-feedback-${index}"></span></div>`:'';
 return user+`<article class="assistant-message assistant-answer"><div class="assistant-message-label">AI智能问答助手 <span>${esc(assistantMode(item.mode))}</span></div><div class="assistant-message-text" ${item.streaming?'id="assistant-live-answer"':''}>${esc(item.answer||'')}</div>${item.warning?`<p class="assistant-alert">${esc(item.warning)}</p>`:''}${assistantSources(item.sources)}${feedback}</article>`;
}
function assistantRenderMessages(){
 if(!assistantVisible())return;
 const messages=assistantUI.messages;
 $('#assistant-messages').innerHTML=(assistantUI.loading?'<p class="assistant-empty">正在加载对话…</p>':messages.length?messages.map(assistantMessage).join(''):'<div class="assistant-empty"><span class="assistant-empty-icon">✦</span><h2>把现场问题讲清楚，处理经验就在这里</h2><p>可以描述产品、缺陷现象、发生条件及已经尝试的处理方法。</p><div class="assistant-suggestions"><button type="button" data-suggestion="检测产品出现漏检，应该如何逐步排查？">产品漏检如何排查？</button><button type="button" data-suggestion="如何根据已有售后经验处理相机成像不稳定的问题？">相机成像不稳定怎么办？</button></div></div>')+(assistantUI.busy?'<div class="assistant-waiting" role="status"><span class="assistant-spinner"></span><span id="assistant-progress">'+esc(assistantUI.progress||'正在检索知识与适用条件…')+'</span></div>':'');
 $('#assistant-messages').querySelectorAll('[data-suggestion]').forEach(button=>{button.onclick=()=>{$('#assistant-question').value=button.dataset.suggestion;assistantUI.draft=button.dataset.suggestion;$('#assistant-question').focus()}});
 $('#assistant-messages').querySelectorAll('[data-feedback-index]').forEach(button=>{button.onclick=()=>assistantFeedback(Number(button.dataset.feedbackIndex),button.dataset.rating)});
 $('#assistant-question').disabled=assistantUI.loading;
 $('#assistant-send').disabled=assistantUI.busy||assistantUI.loading;$('#assistant-send').textContent=assistantUI.busy?'回答中…':'发送';
 $('#assistant-stop').hidden=!assistantUI.busy;
 $('#assistant-error').textContent=assistantUI.error;
 const container=$('#assistant-messages');container.scrollTop=container.scrollHeight;
}
function assistantNewConversation(){
 if(!assistantVisible())return;assistantUI.controller?.abort();++assistantUI.view;assistantUI.activeId=null;assistantUI.messages=[];assistantUI.busy=false;assistantUI.loading=false;assistantUI.error='';assistantUI.draft='';$('#assistant-question').value='';assistantRenderHistory();assistantRenderMessages();$('#assistant-question').focus();
}
async function assistantSelectConversation(id){
 assistantUI.controller?.abort();
 const epoch=assistantUI.epoch,view=++assistantUI.view;assistantUI.activeId=String(id);assistantUI.messages=[];assistantUI.busy=false;assistantUI.loading=true;assistantUI.error='';assistantUI.draft='';$('#assistant-question').value='';assistantRenderHistory();assistantRenderMessages();
 try{const value=await request('/api/assistant/history?'+new URLSearchParams({id}));if(!assistantCurrent(epoch,view))return;assistantUI.messages=Array.isArray(value.messages)?value.messages:[]}
 catch(error){if(assistantCurrent(epoch,view))assistantUI.error=error.message}
 finally{if(assistantCurrent(epoch,view)){assistantUI.loading=false;assistantRenderMessages()}}
}
async function assistantReadStream(payload,onEvent,signal){
 const response=await fetch('/api/assistant/chat-stream',{method:'POST',headers:{'Content-Type':'application/json','X-AOI-Client':'local-v1'},body:JSON.stringify(payload),signal});
 if(!response.ok){let value;try{value=await response.json()}catch{}throw Error(value?.error||'问答连接失败，请重试')}
 if(!response.body?.getReader)throw Error('浏览器不支持流式读取，请更新浏览器后重试');
 const reader=response.body.getReader(),decoder=new TextDecoder('utf-8');let buffer='',done=false,total=0;
 try{
  while(true){const part=await reader.read();buffer+=decoder.decode(part.value||new Uint8Array(),{stream:!part.done});total+=part.value?.length||0;if(total>3000000)throw Error('回答数据过大');buffer=buffer.replace(/\r\n/g,'\n');let end;
   while((end=buffer.indexOf('\n\n'))>=0){const frame=buffer.slice(0,end);buffer=buffer.slice(end+2);let type='message';const data=[];for(const line of frame.split('\n')){if(line.startsWith('event:'))type=line.slice(6).trim();else if(line.startsWith('data:'))data.push(line.slice(5).trimStart())}if(!data.length)continue;const value=JSON.parse(data.join('\n'));if(type==='error')throw Error(value.error||'回答中断，请重试');onEvent(type,value);if(type==='done')done=true}
   if(done)break;if(part.done)throw Error('回答连接已中断，请重试');
  }
 }finally{try{await reader.cancel()}catch{}reader.releaseLock()}
}
async function assistantSend(event){
 event.preventDefault();if(!assistantVisible()||assistantUI.busy||assistantUI.loading)return;const question=$('#assistant-question').value.trim();if(!question){assistantUI.error='请先输入问题';assistantRenderMessages();return}if(question.length>4000){assistantUI.error='问题最多 4000 个字符';assistantRenderMessages();return}
 const epoch=assistantUI.epoch,view=++assistantUI.view,conversationId=assistantUI.activeId,controller=new AbortController();assistantUI.controller=controller;
 const pending={question,pending:true,streaming:true,answer:'',sources:[]};assistantUI.messages.push(pending);assistantUI.busy=true;assistantUI.progress='正在检索知识与适用条件…';assistantUI.error='';assistantUI.draft='';$('#assistant-question').value='';assistantRenderMessages();
 try{await assistantReadStream({question,conversation_id:conversationId},(kind,value)=>{
  if(!assistantCurrent(epoch,view)){controller.abort();return}
  if(kind==='status'){assistantUI.progress=value.message||'正在生成回答…';const progress=$('#assistant-progress');if(progress)progress.textContent=assistantUI.progress}
  if(kind==='sources'){pending.sources=value.sources||[];assistantUI.activeId=value.conversation_id;assistantRenderMessages()}
  if(kind==='delta'){pending.answer+=value.text||'';const root=$('#assistant-messages'),atBottom=root.scrollHeight-root.scrollTop-root.clientHeight<100;const answer=$('#assistant-live-answer');if(answer)answer.textContent=pending.answer;if(atBottom)root.scrollTop=root.scrollHeight}
  if(kind==='reset'){pending.answer=value.answer||'';pending.mode=value.mode;pending.warning=value.warning;assistantRenderMessages()}
  if(kind==='done'){Object.assign(pending,value,{id:value.question_id,pending:false,streaming:false});assistantUI.activeId=value.conversation_id;const previous=assistantUI.history.find(item=>String(item.id)===String(value.conversation_id));const updated={id:value.conversation_id,title:previous?.title||question.slice(0,60),updated_at:new Date().toISOString()};assistantUI.history=[updated,...assistantUI.history.filter(item=>String(item.id)!==String(value.conversation_id))];assistantRenderHistory();if(value.index_version!=null&&assistantUI.status){assistantUI.status.index_version=value.index_version;assistantUI.status.dirty=false;if(value.documents!=null)assistantUI.status.documents=value.documents;assistantRenderStatus()}}
 },controller.signal)}
 catch(error){if(!assistantCurrent(epoch,view))return;if(pending.answer){pending.pending=false;pending.streaming=false;pending.mode='service_error';pending.warning=error.name==='AbortError'?'已停止回答，以上内容未完整生成。':'回答中断，以上内容未完整生成，请重试。';delete pending.id}else{assistantUI.messages=assistantUI.messages.filter(item=>item!==pending)}assistantUI.error=error.name==='AbortError'?'已停止回答':error.message;if(!$('#assistant-question').value.trim()){assistantUI.draft=question;$('#assistant-question').value=question}}
 finally{if(assistantCurrent(epoch,view)){assistantUI.busy=false;assistantUI.controller=null;assistantRenderMessages()}}
}
async function assistantFeedback(index,rating){
 const epoch=assistantUI.epoch,view=assistantUI.view,item=assistantUI.messages[index];if(!item?.id)return;
 const controls=Array.from($('#assistant-messages').querySelectorAll('[data-feedback-index]')).filter(button=>Number(button.dataset.feedbackIndex)===index);controls.forEach(button=>button.disabled=true);
 try{await request('/api/assistant/feedback',{question_id:item.id,rating,comment:''});if(!assistantCurrent(epoch,view))return;item.feedback={rating};assistantRenderMessages();const message=$('#assistant-feedback-'+index);if(message)message.textContent='已记录'}catch(error){if(assistantCurrent(epoch,view)){const message=$('#assistant-feedback-'+index);if(message)message.textContent=error.message}}finally{if(assistantCurrent(epoch,view))controls.forEach(button=>button.disabled=false)}
}
function assistantValidateImport(file){if(!file)throw Error('请先选择 CSV 或 XLSX 文件');if(!/\.(csv|xlsx)$/i.test(file.name))throw Error('仅支持 CSV 和 XLSX 文件');if(file.size>5*1024*1024)throw Error('文件大小不能超过 5 MB');if(!file.size)throw Error('文件为空，请重新选择');return file}
async function assistantPostFile(path,file,params={}){
 const response=await fetch(path+'?'+new URLSearchParams({name:file.name,...params}),{method:'POST',headers:{'X-AOI-Client':'local-v1'},body:file});let value;try{value=await response.json()}catch{throw Error('服务器未返回有效结果，请检查文件格式和服务状态')}if(!response.ok)throw Error(value.error||'导入失败');return value;
}
async function assistantImportKnowledge(){
 if(!assistantIsAdmin())return;const epoch=assistantUI.epoch,message=$('#assistant-management-message'),button=$('#assistant-knowledge-import'),field=$('#assistant-knowledge-file'),rebuild=$('#assistant-rebuild');let file;try{file=assistantValidateImport(field.files[0])}catch(error){message.textContent=error.message;return}
 button.disabled=true;field.disabled=true;rebuild.disabled=true;message.textContent='正在导入知识并更新索引…';
 try{const value=await assistantPostFile('/api/assistant/knowledge-import',file);if(!assistantCurrent(epoch))return;message.textContent=`已导入 ${value.imported??0} 条，跳过重复 ${value.duplicates??0} 条。`+(value.index_updated===false?' 知识源已保存，但索引更新失败，请重试更新索引。':'');field.value='';const status=value.status||await request('/api/assistant/status');if(assistantCurrent(epoch)){assistantUI.status=status;assistantRenderStatus()}}
 catch(error){if(assistantCurrent(epoch))message.textContent=error.message}finally{if(assistantCurrent(epoch)){button.disabled=false;field.disabled=false;rebuild.disabled=false}}
}
async function assistantRebuild(){
 if(!assistantIsAdmin())return;const epoch=assistantUI.epoch,message=$('#assistant-management-message'),button=$('#assistant-rebuild'),importButton=$('#assistant-knowledge-import');button.disabled=true;importButton.disabled=true;message.textContent='正在更新本地知识索引…';
 try{const value=await request('/api/assistant/rebuild',{});if(!assistantCurrent(epoch))return;assistantUI.status=value.status||value;assistantRenderStatus();message.textContent='知识索引已更新。'}catch(error){if(assistantCurrent(epoch))message.textContent=error.message}finally{if(assistantCurrent(epoch)){button.disabled=false;importButton.disabled=false}}
}
function afterSalesImportParams(form){return {project_id:form.elements.project_id.value,product_id:form.elements.product_id.value,status:form.elements.status.value}}
function afterSalesImportPreview(value){
 const errors=Array.isArray(value.errors)?value.errors:[],rows=Array.isArray(value.preview)?value.preview:[];
 return `<div class="assistant-import-summary">共 ${esc(value.total??0)} 行 · 可导入 ${esc(value.valid_count??0)} 行 · 重复 ${esc(value.duplicate_count??0)} 行</div>${errors.length?`<div class="assistant-import-errors"><strong>请修正以下错误后重新选择文件并预览</strong><ul>${errors.slice(0,30).map(error=>`<li>第 ${esc(error.row)} 行：${esc(error.message)}</li>`).join('')}</ul>${errors.length>30?`<p>共 ${errors.length} 个错误，显示前 30 个。</p>`:''}</div>`:''}${rows.length?`<div class="assistant-import-table"><table><thead><tr><th>行号</th><th>问题标题</th><th>项目 / 产品</th><th>处理状态</th></tr></thead><tbody>${rows.slice(0,10).map(item=>`<tr><td>${esc(item.row)}</td><td>${esc(item.record?.name||'')}</td><td>${esc(item.record?.project_id??'')} / ${esc(item.record?.product_id??'')}</td><td>${esc(item.record?.status||'')}</td></tr>`).join('')}</tbody></table></div><p class="subtle">预览前 ${Math.min(rows.length,10)} 条记录。</p>`:''}`;
}
function afterSalesImportDialog(){
 if(!S.auth){toast('请先登录再导入售后经验');return}
 const d=extraDialog(`<form><div class="dialogtop"><h2>批量导入售后经验</h2><button type="button" data-close>✕</button></div><p>导入现有 CSV 或 Excel（.xlsx），保留问题现象、处理方案和经验。导入后会更新本地问答知识库。</p><div class="uploadbox"><input type="file" name="source_file" accept=".csv,.xlsx" required><p class="subtle">单文件最多 5 MB。问答表只有问题和答案时，请选择默认项目、默认产品。</p></div><div class="uploadfields"><label>默认项目<select name="project_id"><option value="">按文件中每行的项目填写</option>${(S.data.projects||[]).map(item=>`<option value="${esc(item.id)}">#${esc(item.id)} · ${esc(item.name)}</option>`).join('')}</select></label><label>默认产品<select name="product_id"><option value="">按文件中每行的产品填写</option>${(S.data.products||[]).map(item=>`<option value="${esc(item.id)}">#${esc(item.id)} · ${esc(item.name)}</option>`).join('')}</select></label><label>默认处理状态<select name="status"><option>已解决</option><option>待处理</option><option>处理中</option></select></label></div><p class="subtle">默认值只补充文件中的空值。每条售后必须有明确的项目与产品；无法匹配的记录会在预览中提示。</p><div class="toolbar"><button type="button" data-template>下载 CSV 模板</button><button type="button" data-preview class="primary">预览导入</button><button type="submit" data-commit disabled>确认导入</button></div><p data-import-message role="status"></p><div data-import-preview></div></form>`,'assistant-import-dialog');
 const form=d.querySelector('form'),preview=d.querySelector('[data-preview]'),commit=d.querySelector('[data-commit]'),message=d.querySelector('[data-import-message]'),output=d.querySelector('[data-import-preview]');let prepared=null,busy=false,revision=0,closed=false;
 d.addEventListener('close',()=>{closed=true;++revision});
 const invalidate=()=>{prepared=null;++revision;commit.disabled=true;output.innerHTML='';message.textContent='文件或默认值已更改，请重新预览。'};
 form.elements.source_file.onchange=invalidate;for(const key of ['project_id','product_id','status'])form.elements[key].onchange=invalidate;
 const setBusy=value=>{busy=value;preview.disabled=value;commit.disabled=value||!prepared;for(const key of ['source_file','project_id','product_id','status'])form.elements[key].disabled=value};
 d.querySelector('[data-template]').onclick=()=>download('售后经验导入模板.csv','\uFEFFproject_id,product_id,name,symptom,cause,resolution,experience,status,remark\r\n','text/csv;charset=utf-8');
 preview.onclick=async()=>{if(busy)return;let file;try{file=assistantValidateImport(form.elements.source_file.files[0])}catch(error){message.textContent=error.message;return}const params=afterSalesImportParams(form),version=++revision;prepared=null;setBusy(true);message.textContent='正在检查文件、绑定关系和重复记录…';output.innerHTML='';try{const value=await assistantPostFile('/api/after-sales/import-preview',file,params);if(closed||revision!==version)return;output.innerHTML=afterSalesImportPreview(value);if(!(value.errors||[]).length&&Number(value.valid_count)>0){prepared={file,params};message.textContent='预览通过。确认后将写入售后经验并更新知识库。'}else message.textContent=(value.errors||[]).length?'预览发现错误，尚未写入任何数据。':'没有可导入的新记录。'}catch(error){if(!closed&&revision===version)message.textContent=error.message}finally{if(!closed&&revision===version)setBusy(false)}};
 form.onsubmit=async event=>{event.preventDefault();if(busy||!prepared)return;const plan=prepared;setBusy(true);message.textContent='正在导入，请勿重复提交…';try{const value=await assistantPostFile('/api/after-sales/import',plan.file,plan.params);prepared=null;if(!closed)d.close();await refresh();toast(`已导入 ${value.imported??0} 条售后经验，跳过重复 ${value.duplicates??0} 条${value.index_updated?'，知识索引已更新':''}。`)}catch(error){if(!closed){prepared=null;message.textContent=error.message+'；请重新预览后再导入。'}}finally{if(!closed)setBusy(false)}};
}
