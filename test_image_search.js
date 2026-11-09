// Uses isolated sample data; no browser or user database changes.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
const el=key=>{if(!elements.has(key))elements.set(key,{value:'',innerHTML:'',textContent:'',style:{},addEventListener:()=>{},querySelectorAll:()=>[]});return elements.get(key)};
const context=vm.createContext({document:{querySelector:el,addEventListener:()=>{}},setTimeout:()=>{},MutationObserver:class {observe(){}},console});
let source=fs.readFileSync(__dirname+'/static/app.js','utf8');
source=source.replace(/;refresh\(\)\.catch\(e=>\{.*?\}\);/,';');
vm.runInContext(source,context);
const sample=JSON.parse(fs.readFileSync(__dirname+'/sample.json','utf8'));sample.videos=[{id:1,project_id:1,name:'设备演示录像',file_name:'demo.mp4'}];
vm.runInContext('S='+JSON.stringify({data:sample})+';',context);
const run=code=>vm.runInContext(code,context);
assert.equal(run('matchingImageResults({}).length'),sample.images.length);
assert.equal(run("matchingImageResults({q:'设备演示录像'}).length"),sample.images.filter(i=>sample.project_assets.some(p=>p.project_id===1&&p.asset_id===i.asset_id)).length);
assert.equal(run("matchingImageResults({q:'不存在的工程关键词'}).length"),0);
const en=sample.engineering_projects[0];
run("S.data.engineering_projects[0].name='唯一工程检索词'");
const linked=sample.asset_relations.filter(r=>r.source_asset_id===en.asset_id&&r.relation_type==='paired').length;
assert.equal(run("matchingImageResults({q:'唯一工程检索词'}).length"),linked);
assert.equal(run('matchingImageResults({defect:1}).length'),sample.image_defects.filter(r=>r.defect_type_id===1).length);
run('search()');
assert(!el('#content').innerHTML.includes('id="stype"'));
assert.equal((el('#results').innerHTML.match(/<article /g)||[]).length,sample.images.length);
assert(!el('#results').innerHTML.includes('编辑资源'));
assert(el('#results').innerHTML.includes('data-searchvideo="1"'));
assert(el('#results').innerHTML.includes('data-searchimage='));
assert(el('#searchcount').textContent.includes('张图片'));
console.log('PASS: image-only results, engineering/video keyword search, confirmed-image defect filter, linked video actions, thumbnail cards, image counts, no resource type filter');

const expected=[...sample.images].sort((a,b)=>Number(sample.image_defects.some(d=>d.image_id===a.id))-Number(sample.image_defects.some(d=>d.image_id===b.id))||b.id-a.id).map(i=>i.id);
assert.deepEqual(Array.from(run('matchingImageResults({}).map(r=>r.i.id)')),expected);
console.log('PASS: unassigned-defect images first, newest ID first within each group');

run("S.data.after_sales=[{status:'待处理'},{status:'处理中'},{status:'已解决'}]; S.data.engineering_projects=[{id:1,image_count:120},{id:2,image_count:0},{id:3,image_count:null}]");
const stats=run('dashboardStats()');
assert.equal(stats.engineering,3);assert.equal(stats.total,120);assert.equal(stats.unknown,1);assert.equal(stats.openSales,2);assert.equal(stats.uploaded,sample.images.length);
console.log('PASS: dashboard manual image totals, zero counts, missing counts and pending after-sales');

run("extraDialog=html=>{globalThis.lastDialog=html;return {querySelector:()=>({}),close:()=>{}}};table='engineering_projects';edit(1)");
assert(context.lastDialog.includes('name="image_count"'));
assert(context.lastDialog.includes('value="120"'));
assert(!context.lastDialog.includes('name="software_name"'));
assert(!context.lastDialog.includes('name="asset_id"'));
assert.equal(run('pages.modeltests[1]'),'软件测试记录');
console.log('PASS: engineering edit opens explicit image count form without hidden asset/software inputs; model-test navigation registered');

run("S.auth=null;S.data.model_tests=[{id:1,name:'模型测试',model_name:'M',product_id:1,test_count:200,detection_rate:98.5,yield_rate:96.5,prompt:'GPU'}];S.data.model_test_files=[{test_id:1,asset_id:S.data.assets[0].id,role:'input'}];modeltests()");
assert(el('#model-test-list').innerHTML.includes('检出率：98.5%'));
assert(el('#model-test-list').innerHTML.includes('data-model-preview='));
assert(!el('#model-test-list').innerHTML.includes('<figure><a'));
run('modelTestEditor(1)');
assert(context.lastDialog.includes('name="product_id"'));
assert(!context.lastDialog.includes('name="project_id"'));
assert(context.lastDialog.includes('测试环境备注'));
assert(context.lastDialog.includes('name="test_count"'));
console.log('PASS: model test product/metrics form and click-to-preview image markup');

assert(!run("'sql' in pages"));
assert(el('#model-test-list').innerHTML.includes('良率：96.5%'));
assert(!el('#model-test-list').innerHTML.includes('漏检率'));
assert(context.lastDialog.includes('name="yield_rate"'));
assert(!context.lastDialog.includes('name="miss_rate"'));
console.log('PASS: MySQL navigation removed and yield rate replaces miss rate in model test views');

run("S.data.technical_agreements=[];S.data.projects=[{id:1,name:'项目A'}];agreementRecordEditor()");
assert(context.lastDialog.includes('data-agreement-file'));
assert(context.lastDialog.includes('上传并保存文档记录'));
assert(!context.lastDialog.includes('data-agreement-backup'));
console.log('PASS: agreement new-record form combines metadata with local file upload');

run('S.data.images=[];videoUpload()');
assert(context.lastDialog.includes('name="project_id"'));
assert(!context.lastDialog.includes('name="image_id"'));
console.log('PASS: video new-record upload binds a project without requiring any images');

run("S.data.model_test_files[0].id=77;S.auth={role:'editor'};modeltests()");
assert(el('#model-test-list').innerHTML.includes('data-model-file-rename="77"'));
assert(!el('#model-test-list').innerHTML.includes('data-model-file-delete='));
run("S.auth={role:'admin'};modeltests()");
assert(el('#model-test-list').innerHTML.includes('data-model-file-delete="77"'));
run("S.auth=null;modeltests()");
assert(!el('#model-test-list').innerHTML.includes('data-model-file-rename='));
assert(!el('#model-test-list').innerHTML.includes('data-model-file-delete='));
console.log('PASS: model image rename/delete buttons follow editor/admin/guest roles');

assert.equal(run('pages.offline[1]'),'大模型离线测试');assert(el('#content').innerHTML.includes('offline-shortcut'));

assert.equal(run('pages.guide[1]'),'AI智能问答助手');

run("S.data.model_tests[0].light_source='红色环形光';S.data.model_tests[0].camera='CCD-5MP';S.data.model_tests[0].lens='25mm';S.data.model_tests[0].working_distance_mm=0;S.data.model_tests[0].product_spec='M6';modelTestEditor(1)");
for(const field of ['light_source','camera','lens','working_distance_mm','product_spec'])assert(context.lastDialog.includes('name="'+field+'"'));
run('modeltests()');assert(el('#model-test-list').innerHTML.includes('0 mm'));assert(el('#model-test-list').innerHTML.includes('CCD-5MP'));
el('#model-test-filter').value='红色环形光';el('#model-test-filter').oninput();assert(el('#model-test-list').innerHTML.includes('模型测试'));
el('#model-test-filter').value='不存在的相机';el('#model-test-filter').oninput();assert(el('#model-test-list').innerHTML.includes('暂无测试记录'));
console.log('PASS: model test hardware fields, zero distance display and equipment search');

run("S.data.model_tests.push({id:2,name:'时间基准',test_module:'AI运行时间测试',model_name:'检测软件',actual_result:'平均 18 ms'});S.data.model_test_files=[];modeltests()");
el('#model-test-filter').value='';el('#test-module-filter').value='AI运行时间测试';el('#test-module-filter').onchange();
assert(el('#model-test-list').innerHTML.includes('平均 18 ms'));assert(!el('#model-test-list').innerHTML.includes('模型测试</h2>'));
run('modelTestEditor(2)');assert(context.lastDialog.includes('class="aligned-fields"'));assert(context.lastDialog.includes('name="test_module"'));assert(context.lastDialog.includes('name="actual_result"'));
run("S.data.technical_experiences=[{id:1,name:'标注规范',content:'边界复核',category:'标注规范'}];S.data.technical_experience_files=[];S.data.videos=[];technicalExperiences()");
assert(el('#technical-list').innerHTML.includes('边界复核'));
run('technicalExperienceEditor(1)');assert(context.lastDialog.includes('name="content"'));assert(!context.lastDialog.includes('name="project_id"'));
console.log('PASS: software module filtering, measurement data and independent technical knowledge forms');
