// Record-level knowledge editing and two-way browsing.
const knowledgeEntityTables=['projects','products','product_categories','materials','process_types','defect_types','technical_objects','model_tests','technical_experiences','technical_agreements','videos','images','engineering_projects','assets','after_sales'];
function knowledgeNormalize(value){return String(value||'').normalize('NFKC').replace(/\s+/g,'').toLowerCase()}
function knowledgeStatuses(){return S.schema?.find(t=>t.name==='knowledge_links')?.fields.find(f=>f.name==='confirmation_status')?.choices||['待补充','待验证','经验建议','已验证']}
function applyFieldConstraints(root,t){const meta=S.schema?.find(x=>x.name===t);if(!meta)return;root.querySelectorAll('[name]').forEach(input=>{const field=meta.fields.find(f=>f.name===input.name);if(!field)return;if(field.maxLength!=null)input.maxLength=field.maxLength;if(field.minimum!=null)input.min=field.minimum;if(field.maximum!=null)input.max=field.maximum})}
function objectName(t,r){const aliases=(S.data.entity_aliases||[]).filter(a=>a.entity_table===t&&a.entity_id===r.id).map(a=>a.name);return [r.name||r.file_name||label(t,r.id),r.spec_text||r.version||r.object_kind||'',`#${r.id}`,aliases.length?'别名：'+aliases.join('、'):''].filter(Boolean).join(' · ')}
function objectPicker(t,name,values=[],multiple=true){return `<div class="object-picker" data-object-table="${t}"><input type="search" data-object-search placeholder="搜索名称、编号、规格或别名…" aria-label="搜索已有对象"><select name="${name}" ${multiple?'multiple size="4"':''}><option value="">${multiple?'不关联 / 清除选择':'请选择已有对象'}</option>${(S.data[t]||[]).map(r=>`<option value="${r.id}" ${values.map(String).includes(String(r.id))?'selected':''}>${esc(objectName(t,r))}</option>`).join('')}</select>${S.auth?`<button type="button" data-object-new="${t}">＋ 新建${esc(S.schema.find(s=>s.name===t)?.label||'对象')}</button>`:''}</div>`}
function wireObjectPickers(root){root.querySelectorAll('[data-object-search]').forEach(input=>input.oninput=()=>{const q=knowledgeNormalize(input.value);input.parentElement.querySelectorAll('option').forEach(o=>{o.hidden=!!q&&!knowledgeNormalize(o.textContent).includes(q)&&!o.selected})});root.querySelectorAll('[data-object-new]').forEach(b=>b.onclick=()=>quickObject(b.dataset.objectNew,b.closest('.object-picker')))}
function quickObject(t,parent){
 const meta=S.schema.find(s=>s.name===t);if(!meta)return;const excluded=['id','created_by','created_at','updated_by','updated_at','preview_asset_id','asset_id'];
 if(['model_tests','technical_experiences','videos','technical_agreements','images','assets','engineering_projects'].includes(t)){toast('请先在对应业务模块保存记录，再回到这里关联；当前表单仍保留。');return}
 const fields=meta.fields.filter(f=>!f.readonly&&!f.hidden&&!excluded.includes(f.name)&&!(t==='products'&&f.name==='code'));
 const d=extraDialog(`<form><div class="dialogtop"><h2>新建${esc(meta.label)}</h2><button type="button" data-close>✕</button></div><p>保存前请搜索确认对象是否已存在。同名规格不同时应分别登记。</p><div class="aligned-fields">${fields.map(f=>`<label>${esc(f.label)}${f.required?' *':''}${f.ref?objectPicker(f.ref,f.name,[],false):f.choices?`<select name="${f.name}" ${f.required?'required':''}><option value="">请选择</option>${f.choices.map(x=>`<option>${esc(x)}</option>`).join('')}</select>`:`<input name="${f.name}" ${f.required?'required':''} maxlength="${f.name==='specification'?'20000':'191'}">`}</label>`).join('')}</div><p class="error"></p><button class="primary" type="submit">保存并选中</button></form>`);wireObjectPickers(d);
 d.querySelector('form').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('[type=submit]');b.disabled=true;try{const j=await request('/api/save',{table:t,record:Object.fromEntries(new FormData(e.target))});S=await request('/api/state');const r=S.data[t].find(x=>x.id===j.id),select=parent.querySelector('select'),o=document.createElement('option');o.value=j.id;o.textContent=objectName(t,r);o.selected=true;select.appendChild(o);d.close()}catch(e){d.querySelector('.error').textContent=e.message}finally{b.disabled=false}};
}
function knowledgeGroups(t){return t==='technical_experiences'?[['适用于','products','适用产品'],['适用于','product_categories','适用产品分类'],['适用于','defect_types','相关缺陷'],['适用于','materials','适用材质'],['适用于','process_types','适用工艺'],['使用设备','technical_objects','涉及工具与设备'],['测试依据','model_tests','参考测试记录']]:[['测试缺陷','defect_types','测试缺陷范围'],['使用设备','technical_objects','本次使用的设备 / 模型 / 软件'],['参考规范','technical_experiences','参考规范与经验']]}
function knowledgeFields(t,id,r={}){
 const links=(S.data.knowledge_links||[]).filter(l=>l.source_table===t&&l.source_id===id);
 return `<fieldset class="knowledge-fields"><legend>适用对象与依据</legend><p>先搜索并选择已有对象；没有合适对象再新建。未知可留空，关联不自动表示因果。</p><div class="aligned-fields">${t==='technical_experiences'?`<label>经验类型<select name="experience_type"><option value="">待补充</option>${['标注规范','调试经验','原理解释','工具操作','其他'].map(x=>`<option ${r.experience_type===x?'selected':''}>${x}</option>`).join('')}</select></label>`:''}<label>确认状态<select name="confirmation_status">${knowledgeStatuses().map(x=>`<option ${r.confirmation_status===x?'selected':''}>${x}</option>`).join('')}</select></label>${t==='technical_experiences'?`<label class="field-wide">适用条件与使用限制<textarea name="conditions" maxlength="20000">${esc(r.conditions)}</textarea></label>`:`<label>检测面与测试范围<input name="inspection_surface" maxlength="191" value="${esc(r.inspection_surface)}"></label><label class="field-wide">判定标准<textarea name="acceptance_criteria" maxlength="20000">${esc(r.acceptance_criteria)}</textarea></label>`}${knowledgeGroups(t).map(([rel,target,text])=>`<label class="field-wide">${text}${objectPicker(target,'kg_'+rel+'_'+target,links.filter(l=>l.relation===rel&&l.target_table===target).map(l=>l.target_id))}</label>`).join('')}</div>${t==='model_tests'?`<details><summary>历史设备与模型参数快照</summary><pre class="snapshot-text">${esc(r.parameter_snapshot||'保存时自动记录本次设备、模型及参数')}</pre></details>${id?'<label class="checkline"><input type="checkbox" name="recapture_snapshot">明确更新本次参数快照（设备字典日常更新不会改写历史快照）</label>':''}`:''}<details><summary>逐条关联的条件、状态与依据</summary><p>可为不同对象分别填写。留空时沿用本条记录的条件和状态。</p><div data-link-details>${links.length?'已有关联将在下方保留各自条件。':'选好对象后，点击展开逐条填写。'}</div><button type="button" data-link-config>展开已选关联</button></details><p>“已验证”的技术经验应关联测试依据；附件中的重要步骤还需写入正文。</p></fieldset>`;
}
function selectedKnowledgeLinks(form,t,id){
 const old=S.data.knowledge_links||[],result=[];const status=form.elements.confirmation_status?.value||'待补充',conditions=form.elements.conditions?.value||'';
 for(const [relation,target] of knowledgeGroups(t)){
  const select=form.elements['kg_'+relation+'_'+target];
  for(const opt of [...(select?.selectedOptions||[])].filter(o=>o.value)){
   const prior=old.find(l=>l.source_table===t&&l.source_id===id&&l.relation===relation&&l.target_table===target&&l.target_id===Number(opt.value));
   const key=relation+'_'+target+'_'+opt.value,detail=form.querySelector(`[data-link-key="${key}"]`);
   result.push({relation,target_table:target,target_id:Number(opt.value),conditions:detail?detail.querySelector('[data-condition]').value:prior?.conditions||conditions,confirmation_status:detail?detail.querySelector('[data-confirmation]').value:prior?.confirmation_status||status,evidence_test_id:detail?detail.querySelector('[data-evidence]').value||null:prior?.evidence_test_id||null,evidence_document_id:detail?detail.querySelector('[data-evidence-document]').value||null:prior?.evidence_document_id||null,evidence_locator:detail?detail.querySelector('[data-evidence-locator]').value:prior?.evidence_locator||''});
  }
 }
 const evidence=result.find(l=>l.relation==='测试依据')?.target_id;
 result.forEach(l=>{if(t==='technical_experiences'&&l.confirmation_status==='已验证'&&!l.evidence_test_id&&l.relation!=='测试依据')l.evidence_test_id=evidence||null});
 return result;
}
function wireKnowledgeForm(d,t,id){
 wireObjectPickers(d);applyFieldConstraints(d,t);const f=d.querySelector('form');d.querySelector('[data-link-config]')?.addEventListener('click',()=>{
  const links=selectedKnowledgeLinks(f,t,id);d.querySelector('[data-link-details]').innerHTML=links.map(l=>`<div class="link-detail" data-link-key="${l.relation}_${l.target_table}_${l.target_id}"><strong>${esc(l.relation)} · ${esc(objectName(l.target_table,S.data[l.target_table].find(r=>r.id===l.target_id)))}</strong><label>条件<textarea data-condition maxlength="20000">${esc(l.conditions)}</textarea></label><label>确认状态<select data-confirmation>${knowledgeStatuses().map(s=>`<option ${s===l.confirmation_status?'selected':''}>${s}</option>`).join('')}</select></label><label>测试依据<select data-evidence><option value="">未指定</option>${S.data.model_tests.map(r=>`<option value="${r.id}" ${r.id===Number(l.evidence_test_id)?'selected':''}>${esc(objectName('model_tests',r))}</option>`).join('')}</select></label><label>依据文档<select data-evidence-document><option value="">未指定</option>${(S.data.technical_agreements||[]).map(r=>`<option value="${r.id}" ${r.id===Number(l.evidence_document_id)?'selected':''}>${esc(r.name)} · ${esc(r.code)}</option>`).join('')}</select></label><label>证据定位<input data-evidence-locator maxlength="1024" value="${esc(l.evidence_locator)}" placeholder="如：报告第3页表2，或视频00:35"></label></div>`).join('')||'<p>尚未选择关联对象</p>';
 });
}
async function saveKnowledgeForm(form,t,id){
 const record=Object.fromEntries(new FormData(form));Object.keys(record).filter(k=>k.startsWith('kg_')||k==='recapture_snapshot').forEach(k=>delete record[k]);
 const old=id?S.data[t].find(r=>r.id===id):null;
 if(t==='model_tests'&&old?.parameter_snapshot)record.parameter_snapshot=old.parameter_snapshot;
 if(t==='technical_experiences'&&record.confirmation_status==='已验证'&&!selectedKnowledgeLinks(form,t,id).some(l=>l.relation==='测试依据'))throw Error('请为已验证经验选择参考测试记录');
 return request('/api/knowledge/save',{table:t,id,expected_updated_at:old?.updated_at??null,record,links:selectedKnowledgeLinks(form,t,id),recapture_snapshot:!!form.elements.recapture_snapshot?.checked});
}
function wireKnowledgeViews(root){root.querySelectorAll('[data-knowledge-view]').forEach(b=>b.onclick=()=>knowledgeDetails(b.dataset.knowledgeTable,Number(b.dataset.knowledgeView)))}
const dictionaryTables=new Set(['materials','process_types']);

async function editKnowledgeRecord(t,id,dialog){
 if(!S.auth){toast('请先登录后编辑');return}
 try{
  S=await request('/api/state');
  dialog?.close();
  table=t;go('records');edit(id);
 }catch(error){toast(error.message)}
}

async function deleteDictionary(t,id,dialog=null){
 if(S.auth?.role!=='admin'){toast('仅管理员可以删除字典条目');return}
 const row=S.data[t]?.find(r=>r.id===id),name=t==='materials'?'材质':'工艺';
 if(!row||!confirm(`删除${name}“${row.name}”？有关联时会保留该条目并提示处理。`))return;
 try{
  await request('/api/delete',{table:t,id,expected_updated_at:row.updated_at??null});
  dialog?.close();await refresh();toast(`${name}条目已删除`);
 }catch(error){
  if(dialog){dialog.querySelector('[data-maintenance-error]').textContent=error.message}
  else await knowledgeDetails(t,id,error.message);
 }
}

async function knowledgeDetails(t,id,initialNotice=''){
 const dictionary=dictionaryTables.has(t),title=dictionary?'字典详情与关联管理':'对象详情与关联资料';
 const d=extraDialog(`<div class="dialogtop"><h2>${title}</h2><button data-close>✕</button></div><div data-knowledge-body>正在读取关联…</div>`,'knowledge-dialog');
 let notice=initialNotice;
 const draw=async()=>{
  const data=await request('/api/knowledge/graph?'+new URLSearchParams({table:t,id,depth:1}));
  const nodes=new Map(data.nodes.map(n=>[n.key,n])),root=nodes.get(data.root),meta=S.schema.find(s=>s.name===t),r=root.record;
  const admin=S.auth?.role==='admin';
  const references=data.edges.filter(e=>e.target===data.root&&(e.binding||e.link_id)).length;
  const name=t==='materials'?'材质':'工艺';
  d.querySelector('[data-knowledge-body]').innerHTML=`
   <h2>${esc(root.label)}</h2><p class="subtle">${esc(meta?.label)} #${id} · 作者 ${esc(r.created_by||'历史记录未登记')}</p>
   <div class="toolbar"><button data-detail-refresh>刷新关联</button>${S.auth?'<button data-record-edit>编辑此记录</button>':''}${dictionary&&admin?`<button class="danger" data-dictionary-delete ${references?'disabled':''} ${references?'title="请先处理下方的引用"':''}>删除当前${name}${references?'（先处理引用）':''}</button>`:''}</div>
   <p class="error" role="alert" data-maintenance-error>${esc(notice)}</p>
   ${dictionary?`<div class="note"><p>仅名称录错时，可直接编辑此记录，已有产品关联会保留。</p><p>关联选错时，可在下方${t==='materials'?'更正产品材质':'更正工艺绑定'}，或由管理员逐条解除错误绑定。解除材质后该产品材质留空；解除工艺只移除这一条产品—工艺关系。</p><p>当前还有 ${references} 处引用需要处理。产品、图片和工程资料会保留。</p></div>`:''}
   <details ${dictionary?'':'open'}><summary>基本信息</summary><dl class="record-details">${(meta?.fields||[]).filter(f=>!f.hidden&&r[f.name]!=null).map(f=>`<dt>${esc(f.label)}</dt><dd>${esc(f.ref?label(f.ref,r[f.name]):r[f.name])}</dd>`).join('')}</dl></details>
   ${recordMedia(t,r)}<h3>别名</h3><p>${esc(root.aliases.join('、')||'尚未登记')}</p>${S.auth?'<button data-alias-new>添加经确认的别名</button>':''}
   <h3>双向关联与依据</h3>${data.edges.map((e,index)=>{
    const other=nodes.get(e.source===data.root?e.target:e.source);
    if(!other)return '';
    return `<article class="link-detail"><strong>${esc(nodes.get(e.source).label)} → ${esc(e.relation)} → ${esc(nodes.get(e.target).label)}</strong>
     <p>${esc(e.confirmation_status||'已有明确绑定')} ${e.conditions?' · 条件：'+esc(e.conditions):''}${e.evidence_test_id?' · 测试依据 #'+e.evidence_test_id:''}${e.evidence_document_id?' · 依据文档 #'+e.evidence_document_id:''}${e.evidence_locator?' · '+esc(e.evidence_locator):''}</p>
     <div class="toolbar"><button data-knowledge-table="${other.table}" data-knowledge-view="${other.id}">查看${esc(other.label)}</button>
     ${S.auth&&['products','materials','process_types','technical_experiences','model_tests'].includes(other.table)?`<button data-related-edit="${index}">${e.binding?.kind==='product_material'?'更正产品材质':e.binding?.kind==='product_process'?'更正工艺绑定':other.table==='products'?'编辑产品':'编辑关联记录'}</button>`:''}
     ${e.evidence_test_id?`<button data-knowledge-table="model_tests" data-knowledge-view="${e.evidence_test_id}">查看测试依据</button>`:''}
     ${e.evidence_document_id?`<button data-knowledge-table="technical_agreements" data-knowledge-view="${e.evidence_document_id}">查看依据文档</button>`:''}
     ${e.binding&&admin?`<button data-binding-unlink="${index}">解除${e.binding.kind==='product_material'?'材质':'工艺'}绑定</button>`:''}
     ${e.link_id&&admin?`<button data-knowledge-unlink="${index}">解除知识关联</button>`:''}</div></article>`;
   }).join('')||'<p>尚未登记相关资料</p>'}
   <details><summary>关系图</summary>${knowledgeSvg(data)}</details>`;
  wireKnowledgeViews(d);wireResourceActions(d);
  d.querySelector('[data-detail-refresh]').onclick=async event=>{
   event.target.disabled=true;
   try{await refresh();notice='';await draw()}
   catch(error){d.querySelector('[data-maintenance-error]').textContent=error.message;event.target.disabled=false}
  };
  d.querySelector('[data-record-edit]')?.addEventListener('click',()=>editKnowledgeRecord(t,id,d));
  d.querySelector('[data-dictionary-delete]')?.addEventListener('click',()=>deleteDictionary(t,id,d));
  d.querySelector('[data-alias-new]')?.addEventListener('click',()=>aliasEditor(t,id));
  d.querySelectorAll('[data-related-edit]').forEach(button=>button.onclick=()=>{
   const edge=data.edges[Number(button.dataset.relatedEdit)],other=nodes.get(edge.source===data.root?edge.target:edge.source);
   if(edge.binding?.kind==='product_material')editKnowledgeRecord('products',edge.binding.id,d);
   else if(edge.binding?.kind==='product_process')editKnowledgeRecord('product_processes',edge.binding.id,d);
   else editKnowledgeRecord(other.table,other.id,d);
  });
  const remove=async(button,operation,message)=>{
   button.disabled=true;
   d.querySelector('[data-maintenance-error]').textContent='';
   try{await operation();notice='';await refresh();await draw();toast(message)}
   catch(error){d.querySelector('[data-maintenance-error]').textContent=error.message;button.disabled=false}
  };
  d.querySelectorAll('[data-binding-unlink]').forEach(button=>button.onclick=()=>{
   const edge=data.edges[Number(button.dataset.bindingUnlink)],binding=edge.binding;
   const product=nodes.get(edge.source),target=nodes.get(edge.target),material=binding.kind==='product_material';
   if(!confirm(`解除产品“${product.label}”与“${target.label}”的${material?'材质':'工艺'}绑定？${material?'该产品材质将留空。':'该产品的其他工艺会保留。'}产品及关联资料会保留。`))return;
   return remove(button,()=>request('/api/knowledge/unlink-binding',{kind:binding.kind,id:binding.id,target_id:binding.target_id,expected_updated_at:binding.updated_at??null}),'错误绑定已解除，产品与资料已保留');
  });
  d.querySelectorAll('[data-knowledge-unlink]').forEach(button=>button.onclick=()=>{
   const edge=data.edges[Number(button.dataset.knowledgeUnlink)];
   if(!confirm('解除这条知识关联？相关产品、经验和资料记录会保留。'))return;
   return remove(button,()=>request('/api/delete',{table:'knowledge_links',id:edge.link_id,expected_updated_at:edge.updated_at??null}),'知识关联已解除');
  });
 };
 try{await draw()}catch(error){d.querySelector('[data-knowledge-body]').textContent=error.message}
}
function aliasEditor(t,id){const d=extraDialog('<form><h2>添加对象别名</h2><p>确认是同一个对象后再添加；相似名称不会自动合并。</p><label>别名<input name="name" required maxlength="191"></label><p class="error"></p><button type="button" data-close>取消</button><button class="primary">保存别名</button></form>');d.querySelector('form').onsubmit=async e=>{e.preventDefault();try{await request('/api/save',{table:'entity_aliases',record:{entity_table:t,entity_id:id,name:e.target.elements.name.value}});S=await request('/api/state');d.close();toast('别名已登记，关联选择和智能问答均可检索')}catch(e){d.querySelector('.error').textContent=e.message}}}
function knowledgeSvg(data){
 const ns=data.nodes.slice(0,60),positions=new Map(ns.map((n,i)=>[n.key,{x:180+(i%3)*340,y:60+Math.floor(i/3)*120}]));const height=Math.max(200,Math.ceil(ns.length/3)*120+60);
 return `<div class="graphwrap"><svg width="1100" height="${height}" role="img" aria-label="具体记录之间的知识关系图">${data.edges.filter(e=>positions.has(e.source)&&positions.has(e.target)).map(e=>{const a=positions.get(e.source),b=positions.get(e.target);return `<path d="M${a.x},${a.y} L${b.x},${b.y}" stroke="#527d98"/><text x="${(a.x+b.x)/2}" y="${(a.y+b.y)/2-8}" fill="#8dcfc5" font-size="11">${esc(e.relation)}</text>`}).join('')}${ns.map(n=>{const p=positions.get(n.key);return `<g><rect x="${p.x-140}" y="${p.y-22}" width="280" height="44" rx="8" fill="#15283c" stroke="#42aaa4"/><text x="${p.x}" y="${p.y+5}" text-anchor="middle" fill="#e4edf9" font-size="12">${esc(n.label.slice(0,22))} #${n.id}</text></g>`}).join('')}</svg></div>${data.nodes.length>60?'<p>图中展示前60个对象，完整关联请查看列表。</p>':''}`;
}
async function knowledgePage(){
 $('#content').innerHTML=title('KNOWLEDGE CONNECTIONS','知识关联','查看具体产品、缺陷、测试与经验之间的关系，保留条件和依据。')+'<div class="toolbar"><input class="search" id="knowledge-filter" placeholder="搜索对象名称、编号或别名…"><button id="schema-view">查看表结构图</button></div><div id="knowledge-list" class="cards"></div>';
 $('#schema-view').onclick=()=>schemaGraph();
 const draw=()=>{const q=knowledgeNormalize($('#knowledge-filter').value);$('#knowledge-list').innerHTML=knowledgeEntityTables.filter(t=>t!=='assets').flatMap(t=>(S.data[t]||[]).filter(r=>knowledgeNormalize(objectName(t,r)).includes(q)).map(r=>`<article class="panel"><span class="pill">${esc(S.schema.find(s=>s.name===t)?.label)}</span><h3>${esc(r.name||r.file_name||label(t,r.id))}</h3><p>${esc(objectName(t,r))}</p><button data-knowledge-table="${t}" data-knowledge-view="${r.id}">查看详情与关联</button></article>`)).slice(0,150).join('')||'<p>没有匹配对象</p>';wireKnowledgeViews($('#knowledge-list'))};$('#knowledge-filter').oninput=draw;draw();
}
const schemaGraph=graph;graph=knowledgePage;
const rowsWithKnowledge=drawRows;drawRows=function(){
 rowsWithKnowledge();const currentTable=table;
 if(knowledgeEntityTables.includes(currentTable))$('#rows').querySelectorAll('[data-edit]').forEach(b=>{const button=document.createElement('button');button.textContent='详情与关联';button.onclick=()=>knowledgeDetails(currentTable,Number(b.dataset.edit));b.after(button)});
 if(dictionaryTables.has(currentTable))$('#rows').querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>deleteDictionary(currentTable,Number(b.dataset.delete)));
};
const modeltestsWithKnowledge=modeltests;modeltests=function(){modeltestsWithKnowledge();$('#model-test-list').querySelectorAll('[data-model-edit]').forEach(b=>{const button=document.createElement('button');button.textContent='详情与关联';button.onclick=()=>knowledgeDetails('model_tests',Number(b.dataset.modelEdit));b.before(button)})};
