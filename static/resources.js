// Same discovery controls and card layout, expanded to all registered resource types.
function documentTypeNames(){return [...new Set(['技术协议','操作说明','测试报告','技术方案','其他技术文档',...(S.data.document_types||[]).map(r=>r.name),...(S.data.technical_agreements||[]).map(r=>r.document_type).filter(Boolean)])]}
function documentTypeOptions(selected){return documentTypeNames().map(name=>`<option value="${esc(name)}" ${name===selected?'selected':''}>${esc(name)}</option>`).join('')}
function newDocumentType(select){const d=extraDialog('<form><h2>新增文档类别</h2><label>类别名称<input name="name" required maxlength="191"></label><p class="error"></p><button type="button" data-close>取消</button><button class="primary">保存并选中</button></form>');d.querySelector('form').onsubmit=async e=>{e.preventDefault();try{const name=e.target.elements.name.value.trim();await request('/api/save',{table:'document_types',record:{name}});S=await request('/api/state');select.innerHTML=documentTypeOptions(name);d.close()}catch(e){d.querySelector('.error').textContent=e.message}}}
function addObjectSearch(root){
 root.querySelectorAll('select[name]').forEach(select=>{
  if(select.closest('.object-picker')||select.multiple)return;
  const name=select.name,ref={project_id:'projects',product_id:'products',category_id:'product_categories',defect_type_id:'defect_types',parent_id:'product_categories',asset_id:'assets',video_id:'videos',test_id:'model_tests',agreement_id:'technical_agreements'}[name];
  if(!ref)return;const wrapper=document.createElement('div');wrapper.className='object-picker';select.before(wrapper);const input=document.createElement('input');input.type='search';input.placeholder='搜索已有对象名称、编号或别名…';input.setAttribute('aria-label','搜索已有对象');wrapper.appendChild(input);wrapper.appendChild(select);
  for(const option of select.options){const r=S.data[ref]?.find(r=>r.id===Number(option.value));if(r)option.textContent=objectName(ref,r)}
  input.oninput=()=>{const q=input.value.toLowerCase();for(const o of select.options)o.hidden=!!q&&!o.textContent.toLowerCase().includes(q)&&!o.selected};
 });
}
const dialogWithObjectSearch=extraDialog;extraDialog=function(html,cls=''){const d=dialogWithObjectSearch(html,cls);addObjectSearch(d);return d};
const editWithObjectSearch=edit;edit=function(id){editWithObjectSearch(id);const root=document.querySelector('#dialog');if(root)addObjectSearch(root)};
function resourceContext(t,r,asset){
 const keys=new Set([t+':'+r.id]);if(asset)keys.add('assets:'+asset.id);
 if(t==='technical_agreements')for(const f of S.data.agreement_files||[])if(f.agreement_id===r.id)keys.add('assets:'+f.asset_id);
 if(t==='videos'&&r.asset_id)keys.add('assets:'+r.asset_id);
 for(const f of S.data.technical_experience_files||[])if(keys.has('assets:'+f.asset_id)||keys.has('videos:'+f.video_id))keys.add('technical_experiences:'+f.experience_id);
 for(let n=0;n<2;n++){const before=new Set(keys);for(const l of S.data.knowledge_links||[]){const a=l.source_table+':'+l.source_id,b=l.target_table+':'+l.target_id;if(before.has(a))keys.add(b);if(before.has(b))keys.add(a)}}
 const products=new Set(),projects=new Set(),defects=new Set();
 for(const key of keys){const [table,id]=key.split(':');if(table==='products')products.add(Number(id));if(table==='projects')projects.add(Number(id));if(table==='defect_types')defects.add(Number(id));if(table==='product_categories')for(const p of S.data.products)if(p.category_id===Number(id))products.add(p.id)}
 if(r.project_id)projects.add(r.project_id);
 if(asset){const d=assetDetails(asset);for(const p of d.products)products.add(p.id);for(const p of d.projects)projects.add(p.id)}
 if(t==='technical_agreements')for(const f of S.data.agreement_products||[])if(f.agreement_id===r.id)products.add(f.product_id);
 for(const f of S.data.project_products||[])if(products.has(f.product_id))projects.add(f.project_id);
 const texts=[r.name,r.file_name,r.document_type,r.requirements,r.extracted_text,r.remark];
 for(const key of keys){const [table,id]=key.split(':');const record=S.data[table]?.find(x=>x.id===Number(id));if(record)texts.push(record.name,record.content,record.tags,record.conditions,...(S.data.entity_aliases||[]).filter(a=>a.entity_table===table&&a.entity_id===Number(id)).map(a=>a.name))}
 for(const id of products){const p=S.data.products.find(p=>p.id===id);if(p)texts.push(p.name,p.spec_text,p.remark,label('materials',p.material_id))}
 for(const id of projects){const p=S.data.projects.find(p=>p.id===id);if(p)texts.push(p.name,p.code,p.customer_name)}
 return {products,projects,defects,text:texts.filter(Boolean).join(' ').toLowerCase()};
}
function matchingResourceResults(filters){
 const results=[],documents=S.data.technical_agreements||[],videos=S.data.videos||[],handled=new Set();
 for(const doc of documents){const files=(S.data.agreement_files||[]).filter(f=>f.agreement_id===doc.id),a=S.data.assets.find(a=>a.id===files[0]?.asset_id);files.forEach(f=>handled.add(f.asset_id));results.push({table:'technical_agreements',row:doc,asset:a,type:'文档',files})}
 for(const video of videos){if(video.asset_id)handled.add(video.asset_id);results.push({table:'videos',row:video,type:'视频'})}
 const covers=new Set([...S.data.assets,...videos].map(r=>r.preview_asset_id).filter(Boolean));
 for(const a of S.data.assets){if(handled.has(a.id)||covers.has(a.id)||a.asset_type==='image')continue;if(['document','engineering','annotation','archive','other'].includes(a.asset_type))results.push({table:'assets',row:a,asset:a,type:({engineering:'工程',archive:'资料包',document:'文档',annotation:'标注资料'})[a.asset_type]||'其他资料'})}
 const words=(filters.q||'').toLowerCase().split(/\s+/).filter(Boolean);
 return results.filter(item=>{const ctx=resourceContext(item.table,item.row,item.asset);return words.every(w=>ctx.text.includes(w))&&(!filters.project||ctx.projects.has(Number(filters.project)))&&(!filters.product||ctx.products.has(Number(filters.product)))&&(!filters.defect||ctx.defects.has(Number(filters.defect)))&&(!filters.process||(S.data.product_processes||[]).some(p=>ctx.products.has(p.product_id)&&p.process_id===Number(filters.process)))}).sort((a,b)=>b.row.id-a.row.id);
}
function resourceResultCard(item){
 const r=item.row,a=item.asset,t=item.table,owner=t==='videos'?'videos':'assets',ownerId=t==='videos'?r.id:a?.id;
 return `<article class="panel result">${ownerId?resourcePreview(owner,ownerId):''}<span class="pill blue">${item.type}</span><h3>${esc(r.name||r.file_name)}</h3><p>${esc(r.document_type||'')} ${esc(r.remark||r.requirements||'')}</p><p class="subtle">录入作者：${esc(r.created_by||'历史记录未登记')} · #${r.id}</p><div class="toolbar">${ownerId?`<button data-resource-table="${owner}" data-resource-view="${ownerId}">预览资料</button>`:''}<button data-knowledge-table="${t}" data-knowledge-view="${r.id}">详情与关联</button>${item.files?.map(f=>`<a href="/api/media?id=${f.asset_id}&mode=original">下载${esc(S.data.assets.find(a=>a.id===f.asset_id)?.file_name||'文档')}</a>`).join('')||''}</div></article>`;
}
const drawImageSearch=drawSearch;drawSearch=function(){
 drawImageSearch();const filters={q:$('#q').value,project:$('#sp').value,product:$('#spr').value,process:$('#sproc').value,defect:$('#sdef').value},images=matchingImageResults(filters),resources=matchingResourceResults(filters),root=$('#results');
 if(resources.length){if(!images.length)root.innerHTML='';root.insertAdjacentHTML('beforeend',resources.slice(0,150).map(resourceResultCard).join(''))}
 $('#searchcount').textContent=`匹配 ${images.length+resources.length} 条资料 · 图片 ${images.length} 张，其他资料 ${resources.length} 条`;
 wireResourceActions(root);wireKnowledgeViews(root);
};
const rowsWithResourcePreview=drawRows;drawRows=function(){rowsWithResourcePreview();if(['technical_agreements','videos'].includes(table))$('#rows').querySelectorAll('[data-edit]').forEach(b=>{const r=S.data[table].find(r=>r.id===Number(b.dataset.edit));if(!r)return;const a=table==='technical_agreements'?S.data.agreement_files.find(f=>f.agreement_id===r.id):null,owner=table==='videos'?'videos':'assets',id=table==='videos'?r.id:a?.asset_id;if(!id)return;const preview=document.createElement('button');preview.innerHTML=resourcePreview(owner,id)+'预览资料';preview.className='table-preview';preview.onclick=()=>resourceView(owner,id);b.after(preview)})};
