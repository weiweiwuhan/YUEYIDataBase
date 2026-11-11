'use strict';

// External public catalog metadata stays separate from customer product specifications.
const catalogAttributeFields=[['head_type','头型'],['drive_type','驱动槽型'],['thread_type','螺纹'],['material','材质'],['material_type','材料类型'],['manufacturing_material','制造材料'],['property_class','性能等级'],['surface_treatment','表面处理'],['color','颜色']];
const catalogFieldLabels=Object.fromEntries([...catalogAttributeFields,['name','产品名称'],['bn','BN编号'],['standards','标准'],['category_path','分类路径'],['source_url','来源URL'],['fetched_at','采集时间'],['remark','审核备注'],['raw_attributes_json','原始公开属性'],['record_scope','记录层级'],['source_system','来源系统'],['source_product_id','来源产品编号']]);
const catalogUI={query:'',category:'',source:'',page:1,pageSize:50,epoch:0};
function catalogIsAdmin(){return S.auth?.role==='admin'}
function catalogNormalize(value){return String(value??'').normalize('NFKC').replace(/\s+/g,'').toLocaleLowerCase('zh-CN')}
function catalogSafeURL(value){try{const url=new URL(String(value||''));return ['https:','http:'].includes(url.protocol)?url.href:''}catch{return ''}}
function catalogSourceLink(value,label='查看公开来源'){const url=catalogSafeURL(value);return url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`:'<span class="muted">未提供可访问来源</span>'}
let catalogCachedIndex=null;
function catalogDataIndex(){
 const products=S.data.catalog_products||[],categories=S.data.catalog_categories||[],links=S.data.catalog_product_categories||[];
 if(catalogCachedIndex?.products===products&&catalogCachedIndex.categories===categories&&catalogCachedIndex.links===links)return catalogCachedIndex;
 const byCategory=new Map(categories.map(row=>[Number(row.id),row])),byProduct=new Map(),children=new Map();
 for(const category of categories){const parent=Number(category.parent_id);if(category.parent_id!=null){if(!children.has(parent))children.set(parent,[]);children.get(parent).push(Number(category.id))}}
 for(const link of links){const category=byCategory.get(Number(link.catalog_category_id));if(!category)continue;const id=Number(link.catalog_product_id);if(!byProduct.has(id))byProduct.set(id,[]);byProduct.get(id).push(category)}
 const textByProduct=new Map(products.map(row=>[Number(row.id),catalogNormalize([row.bn,row.source_product_id,row.name,row.source_system,row.category_path,row.standards,row.remark,...catalogAttributeFields.map(([key])=>row[key]),...(byProduct.get(Number(row.id))||[]).flatMap(category=>[category.name,category.category_path,category.source_category_id])].join(' '))]));
 const sorted=[...products].sort((a,b)=>String(a.bn||a.source_product_id||'').localeCompare(String(b.bn||b.source_product_id||''),'zh-CN',{numeric:true}));
 return catalogCachedIndex={products,categories,links,byProduct,children,textByProduct,sorted};
}
function catalogCategoryDescendants(id){
 const selected=new Set([Number(id)]),pending=[Number(id)],children=catalogDataIndex().children;
 while(pending.length)for(const child of children.get(pending.pop())||[])if(!selected.has(child)){selected.add(child);pending.push(child)}
 return selected;
}
function catalogProductCategories(id){return catalogDataIndex().byProduct.get(Number(id))||[]}
function catalogMatchingProducts(filters={}){
 const index=catalogDataIndex(),scope=filters.category?catalogCategoryDescendants(filters.category):null;
 const productIds=scope?new Set(index.links.filter(link=>scope.has(Number(link.catalog_category_id))).map(link=>Number(link.catalog_product_id))):null;
 const terms=String(filters.q||'').split(/\s+/).filter(Boolean).map(catalogNormalize);
 return index.sorted.filter(row=>{
  if(filters.source&&row.source_system!==filters.source)return false;
  if(productIds&&!productIds.has(Number(row.id)))return false;
  const text=index.textByProduct.get(Number(row.id))||'';return terms.every(term=>text.includes(term));
 });
}
function catalogCategoryOptions(){
 return [...(S.data.catalog_categories||[])].sort((a,b)=>String(a.category_path||a.source_category_id).localeCompare(String(b.category_path||b.source_category_id),'zh-CN',{numeric:true})).map(row=>`<option value="${esc(row.id)}" ${String(row.id)===String(catalogUI.category)?'selected':''}>${esc(row.category_path||row.name)} · ${esc(row.source_category_id)}${row.source_system?' / '+esc(row.source_system):''}</option>`).join('');
}
function catalogPage(){
 ++catalogUI.epoch;
 const products=S.data.catalog_products||[],categories=S.data.catalog_categories||[],sources=[...new Set(products.map(row=>row.source_system).filter(Boolean))].sort();
 $('#content').innerHTML=title('FASTENER CATALOG','紧固件目录','按来源分类查看标准紧固件公开属性，审核 Excel 后再写入目录。',catalogIsAdmin()?'<button class="primary" id="catalog-open-import">导入已审核 Excel</button>':'<span class="pill">目录只读</span>')+`<div id="catalog-root"><section class="catalog-intro panel"><div><h2>保留原分类与原始属性</h2><p>BN 通常表示产品系列，具体尺寸规格需另行确认。外部目录用于学习、检索和分类参考，公司已有的客户产品规格继续独立管理。</p><p class="subtle">材质、材料类型、制造材料分别保留；公开页未提供的字段显示“未提供”，不会根据名称、表面处理或图片猜测。</p></div><div class="catalog-counts"><span><b>${products.length.toLocaleString()}</b> 目录记录</span><span><b>${categories.length.toLocaleString()}</b> 来源分类</span></div></section><div class="catalog-filters"><label>搜索 BN、名称或属性<input id="catalog-query" type="search" value="${esc(catalogUI.query)}" placeholder="如：BN 874、六角、钢、PA6.6…"></label><label>分类（包含下级）<select id="catalog-category"><option value="">全部来源分类</option>${catalogCategoryOptions()}</select></label><label>来源<select id="catalog-source"><option value="">全部来源</option>${sources.map(source=>`<option value="${esc(source)}" ${source===catalogUI.source?'selected':''}>${esc(source)}</option>`).join('')}</select></label></div><div class="catalog-results-heading"><p id="catalog-result-count" class="subtle"></p><div class="catalog-pagination"><button id="catalog-previous">上一页</button><span id="catalog-page-number"></span><button id="catalog-next">下一页</button></div></div><div id="catalog-results"></div></div>`;
 $('#catalog-open-import')?.addEventListener('click',catalogImportDialog);
 $('#catalog-query').oninput=()=>{catalogUI.query=$('#catalog-query').value;catalogUI.page=1;catalogDraw()};
 $('#catalog-category').onchange=()=>{catalogUI.category=$('#catalog-category').value;catalogUI.page=1;catalogDraw()};
 $('#catalog-source').onchange=()=>{catalogUI.source=$('#catalog-source').value;catalogUI.page=1;catalogDraw()};
 $('#catalog-previous').onclick=()=>{catalogUI.page=Math.max(1,catalogUI.page-1);catalogDraw()};
 $('#catalog-next').onclick=()=>{catalogUI.page+=1;catalogDraw()};catalogDraw();
}
function catalogDraw(){
 const rows=catalogMatchingProducts({q:catalogUI.query,category:catalogUI.category,source:catalogUI.source}),pages=Math.max(1,Math.ceil(rows.length/catalogUI.pageSize));catalogUI.page=Math.min(Math.max(1,catalogUI.page),pages);
 const start=(catalogUI.page-1)*catalogUI.pageSize,shown=rows.slice(start,start+catalogUI.pageSize);
 $('#catalog-result-count').textContent=`匹配 ${rows.length.toLocaleString()} 条 · 当前展示 ${rows.length?start+1:0}–${Math.min(start+catalogUI.pageSize,rows.length)} 条`;
 $('#catalog-page-number').textContent=`${catalogUI.page} / ${pages}`;$('#catalog-previous').disabled=catalogUI.page===1;$('#catalog-next').disabled=catalogUI.page===pages;
 $('#catalog-results').innerHTML=shown.length?`<div class="tablewrap catalog-table"><table><thead><tr><th>BN / 来源编号</th><th>产品名称与分类</th>${catalogAttributeFields.map(([,label])=>`<th>${esc(label)}</th>`).join('')}<th>来源与详情</th></tr></thead><tbody>${shown.map(row=>`<tr><td><strong>${esc(row.bn||row.source_product_id)}</strong><small>${esc(row.source_system)} · ${row.record_scope==='article'?'目录规格':'产品系列'}</small></td><td class="catalog-name-cell"><strong>${esc(row.name)}</strong><small>${esc(catalogProductCategories(row.id).map(category=>category.category_path||category.name).join('；')||row.category_path||'未登记分类')}</small></td>${catalogAttributeFields.map(([field])=>`<td title="${esc(row[field]||'公开页未提供')}">${row[field]?esc(row[field]):'<span class="muted">未提供</span>'}</td>`).join('')}<td>${catalogSourceLink(row.source_url)}<button data-catalog-detail="${esc(row.id)}">查看全部属性</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">暂无匹配的目录记录。管理员可先导入审核后的 Excel，或调整搜索和分类条件。</div>';
 $('#catalog-results').querySelectorAll('[data-catalog-detail]').forEach(button=>button.onclick=()=>catalogDetail(Number(button.dataset.catalogDetail)));
}
function catalogDetail(id){
 const row=(S.data.catalog_products||[]).find(item=>Number(item.id)===Number(id));if(!row)return;
 const values=[['bn','BN编号'],['source_product_id','来源产品编号'],['source_system','来源系统'],['record_scope','记录层级'],...catalogAttributeFields,['standards','标准'],['category_path','来源分类路径'],['fetched_at','公开信息采集时间'],['remark','审核备注']];
 extraDialog(`<div class="dialogtop"><h2>${esc(row.bn||row.source_product_id)} · ${esc(row.name)}</h2><button data-close>✕</button></div><p>这是外部公开目录记录。产品系列中的尺寸、实物状态与项目适用性需另行核实。</p><dl class="catalog-detail">${values.map(([field,label])=>`<dt>${esc(label)}</dt><dd>${row[field]?esc(row[field]):'<span class="muted">未提供</span>'}</dd>`).join('')}</dl><p>${catalogSourceLink(row.source_url)}</p><details><summary>原始公开属性</summary><pre class="catalog-raw">${esc(row.raw_attributes_json||'{}')}</pre></details>`,'catalog-dialog');
}
function catalogValidateFile(file){if(!file)throw Error('请先选择审核后的 XLSX 文件');if(!/\.xlsx$/i.test(file.name))throw Error('目录导入仅支持 XLSX 文件');if(!file.size)throw Error('文件为空，请重新选择');if(file.size>20*1024*1024)throw Error('目录文件不能超过 20 MB');return file}
async function catalogPostFile(path,file,params={}){
 const response=await fetch(path+'?'+new URLSearchParams({name:file.name,mode:'fill_missing',...params}),{method:'POST',headers:{'X-AOI-Client':'local-v1'},body:file});let value;try{value=await response.json()}catch{throw Error('服务器未返回有效结果，请检查文件和服务状态')}if(!response.ok)throw Error(value.error||'目录导入失败');return value;
}
function catalogPreviewHTML(value){
 const errors=Array.isArray(value.errors)?value.errors:[],rows=Array.isArray(value.preview)?value.preview:[],categoryConflicts=Array.isArray(value.category_conflicts)?value.category_conflicts:[];
 const labels={add:'新增',update:'补充空值 / 分类',skip:'跳过',conflict:'冲突，保留已有值'};
 const text=value=>Array.isArray(value)?value.join(' / '):value==null||value===''?'空':String(value);
 return `<div class="catalog-preview-counts">${[['选中产品',value.selected_count],['新增产品',value.add_count],['更新产品',value.update_count],['跳过',value.skip_count],['产品冲突',value.conflict_count],['新增分类',value.category_add_count],['更新分类',value.category_update_count],['分类冲突',value.category_conflict_count],['错误',value.error_count]].map(([label,count])=>`<span>${esc(label)} <b>${esc(count??0)}</b></span>`).join('')}</div><p class="subtle">分类统计包含所选记录依赖的分类及祖先，其中“待审核”或空白的分类也可能写入，不表示已人工审核确认。请对照 Excel 的“分类”表核对；被引用的分类标为“否”会阻止本次整批导入。</p>${errors.length?`<div class="catalog-import-errors"><strong>请修正以下错误后重新预览，尚未写入数据</strong><ul>${errors.slice(0,50).map(error=>`<li>${esc(error.sheet||'工作表')} 第 ${esc(error.row??'?')} 行：${esc(error.message||'校验失败')}</li>`).join('')}</ul>${errors.length>50?'<p>此处显示前 50 个错误。</p>':''}</div>`:''}${categoryConflicts.length?`<div class="catalog-import-conflicts"><strong>分类中的已有值将保留</strong>${categoryConflicts.map(item=>`<p>${esc(item.source_category_id)}：${(item.conflicts||[]).map(conflict=>`${esc(catalogFieldLabels[conflict.field]||conflict.field)}：已有 ${esc(text(conflict.old))}；文件 ${esc(text(conflict.new))}`).join('；')}</p>`).join('')}</div>`:''}${rows.length?`<div class="tablewrap catalog-preview-table"><table><thead><tr><th>Excel 行</th><th>来源编号 / 产品</th><th>操作</th><th>计划补充的内容</th><th>冲突与保留值</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.row)}</td><td>${esc(row.bn||row.source_product_id)}<br>${esc(row.name)}</td><td>${esc(labels[row.action]||row.action)}</td><td>${Object.entries(row.changes||{}).filter(([key])=>key!=='raw_attributes_json').map(([field,change])=>`<div>${esc(catalogFieldLabels[field]||field)}：${esc(text(change.old))} → ${esc(text(change.new))}</div>`).join('')||'无字段变更'}${row.new_category_links?.length?`<div>补充分类：${esc(row.new_category_links.join(' / '))}</div>`:''}</td><td>${(row.conflicts||[]).map(conflict=>`<div>${esc(catalogFieldLabels[conflict.field]||conflict.field)}：保留 ${esc(text(conflict.old))}；文件 ${esc(text(conflict.new))}</div>`).join('')||'无'}</td></tr>`).join('')}</tbody></table></div><p class="subtle">预览最多展示前 50 条产品；确认会按本次校验计划处理全部选中记录。</p>`:''}`;
}
function catalogImportDialog(){
 if(!catalogIsAdmin()){toast('仅管理员可以导入目录，请联系管理员');return}
 const dialog=extraDialog(`<form><div class="dialogtop"><h2>导入已审核的紧固件目录</h2><button type="button" data-close>✕</button></div><p>先在 Excel 的“产品审核”或“分类”表中，将审核通过的记录的“是否导入”改为“是”。“待审核”或空白的产品不会导入。所选产品或分类依赖的分类及祖先，即使仍为“待审核”或空白，也会随依赖一并写入；这不表示分类已经过人工审核确认。请先核对 Excel 的“分类”表；任一被引用的分类标为“否”，都会阻止本次整批导入。</p><p class="subtle">同一来源编号重复导入会匹配已有记录；只补充空值和缺少的分类关联，冲突保留已有值，不删除现有记录。BN 系列进入外部目录，不覆盖客户产品规格。</p><label class="catalog-file-label">选择审核后的 Excel<input name="catalog_file" type="file" accept=".xlsx" required></label><div class="toolbar"><button type="button" data-catalog-preview class="primary">预览校验</button><button type="submit" data-catalog-commit disabled>确认更新目录</button></div><p data-catalog-import-message role="status"></p><div data-catalog-import-preview></div></form>`,'catalog-import-dialog');
 const form=dialog.querySelector('form'),field=form.elements.catalog_file,previewButton=dialog.querySelector('[data-catalog-preview]'),commitButton=dialog.querySelector('[data-catalog-commit]'),message=dialog.querySelector('[data-catalog-import-message]'),output=dialog.querySelector('[data-catalog-import-preview]');let prepared=null,busy=false,revision=0,closed=false;
 dialog.addEventListener('close',()=>{closed=true;prepared=null;++revision});
 const invalidate=()=>{prepared=null;++revision;commitButton.disabled=true;output.innerHTML='';message.textContent='文件已更改，请重新预览校验。'};
 field.onchange=invalidate;
 const setBusy=value=>{busy=value;field.disabled=value;previewButton.disabled=value;commitButton.disabled=value||!prepared};
 previewButton.onclick=async()=>{
  if(busy)return;let file;try{file=catalogValidateFile(field.files[0])}catch(error){message.textContent=error.message;return}
  const requestRevision=++revision;prepared=null;setBusy(true);message.textContent='正在校验审核状态、分类层级、来源编号和已有数据…';output.innerHTML='';
  try{const value=await catalogPostFile('/api/catalog/import-preview',file);if(closed||requestRevision!==revision)return;output.innerHTML=catalogPreviewHTML(value);const errors=Number(value.error_count??(value.errors||[]).length),selected=Number(value.selected_count||0),categories=Number(value.category_add_count||0)+Number(value.category_update_count||0);
   if(!errors&&(selected>0||categories>0)&&typeof value.preview_token==='string'&&value.preview_token){prepared={file,token:value.preview_token};message.textContent='预览通过。确认后按当前计划更新；非空冲突值会保留。'}else message.textContent=errors?'校验发现错误，未写入数据。请修正文件后重新选择并预览。':'没有已选择的待导入记录，请在 Excel 中将审核通过的记录标为“是”。';
  }catch(error){if(!closed&&requestRevision===revision)message.textContent=error.message}finally{if(!closed)setBusy(false)}
 };
 form.onsubmit=async event=>{
  event.preventDefault();if(busy||!prepared)return;const plan=prepared;setBusy(true);message.textContent='正在更新目录，请勿重复提交…';
  try{const result=await catalogPostFile('/api/catalog/import',plan.file,{preview_token:plan.token});prepared=null;if(!closed)dialog.close();await refresh();toast(`目录已更新：产品新增 ${result.add_count??0} 条，补充 ${result.update_count??0} 条，跳过 ${result.skip_count??0} 条；分类新增 ${result.category_add_count??0} 条，补充 ${result.category_update_count??0} 条。已有冲突值保留。`)}
  catch(error){if(!closed){prepared=null;message.textContent=error.message+'；请重新预览后再确认。'}}finally{if(!closed)setBusy(false)}
 };
}

// The generic records page uses the same read-only rule for external catalog tables.
function catalogTableReadOnly(){return ['catalog_categories','catalog_products','catalog_product_categories'].includes(table)&&!catalogIsAdmin()}
const catalogRecordsBase=records;records=function(){catalogRecordsBase();if(catalogTableReadOnly())$('#add')?.remove()};
const catalogDrawRowsBase=drawRows;drawRows=function(){catalogDrawRowsBase();if(catalogTableReadOnly())$('#rows').querySelectorAll('[data-edit],[data-delete]').forEach(button=>button.remove())};
const catalogEditBase=edit;edit=function(id){if(catalogTableReadOnly()){toast('目录只读，请联系管理员审核导入');return}return catalogEditBase(id)};
