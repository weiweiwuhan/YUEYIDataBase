"""End-to-end knowledge, media catalog, preview, and readable file storage tests."""
import io,json,unittest,urllib.request
from urllib.parse import urlencode
from pathlib import Path
import test_assistant_http as harness_module

class KnowledgeHTTPTests(unittest.TestCase):
    setUp=harness_module.AssistantHTTPTests.setUp
    stop_server=harness_module.AssistantHTTPTests.stop_server
    client=staticmethod(harness_module.AssistantHTTPTests.client)
    api=harness_module.AssistantHTTPTests.api
    rejected=harness_module.AssistantHTTPTests.rejected
    def save(self,t,r,rid=None):return self.api(self.editor,'/api/save',{'table':t,'record':r,'id':rid})['id']
    def state(self):return self.api(self.guest,'/api/state')['data']
    def upload(self,name,content,**kwargs):return self.api(self.editor,'/api/upload?'+urlencode(dict(name=name,**kwargs)),raw=content)
    def test_promoted_master_records_previews_categories_and_renames(self):
        eid=self.save('technical_experiences',{'name':'通用标注','content':'按真实边界标注'})
        uploaded=self.upload('标注说明.pdf',b'%PDF-test',kind='technical_experience',experience_id=eid)
        video=self.upload('标注演示.mp4',b'0123456789',kind='technical_experience',experience_id=eid)
        s=self.state();doc=s['technical_agreements'][0];v=s['videos'][0]
        self.assertIsNone(doc['project_id']);self.assertIsNone(v['project_id'])
        self.assertEqual(v['asset_id'],video['asset_id'])
        self.assertEqual(s['agreement_files'][0]['asset_id'],uploaded['asset_id'])
        for aid,kind in [(uploaded['asset_id'],'documents'),(video['asset_id'],'videos')]:
            a=next(a for a in s['assets'] if a['id']==aid)
            self.assertTrue(a['relative_path'].startswith(kind+'/'))
            self.assertEqual(Path(a['relative_path']).name,a['file_name'])
            self.assertTrue((self.data/'uploads'/a['relative_path']).is_file())
        self.save('technical_agreements',{**doc,'name':'更名后的规范','document_type':'自定义作业指引'},doc['id'])
        self.save('videos',{**v,'name':'规范标注视频'},v['id'])
        s=self.state();a=next(a for a in s['assets'] if a['id']==uploaded['asset_id']);v=s['videos'][0]
        self.assertEqual(a['file_name'],'更名后的规范.pdf');self.assertEqual(Path(v['relative_path']).name,'规范标注视频.mp4')
        self.assertIn('自定义作业指引',[x['name'] for x in s['document_types']])
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(100,50),'red').save(out,format='PNG')
        cover=self.upload('规范封面.png',out.getvalue(),kind='preview',owner_table='assets',owner_id=a['id'])
        s=self.state();self.assertFalse(s['images'])
        with self.guest.open(self.base+'/api/preview?table=assets&id='+str(a['id'])) as response:
            self.assertEqual(response.headers.get_content_type(),'image/jpeg');im=Image.open(io.BytesIO(response.read()));self.assertEqual(im.size,(100,50))
        with self.guest.open(self.base+'/api/document-view?id='+str(a['id'])) as response:
            self.assertEqual(response.headers.get_content_type(),'application/pdf');self.assertEqual(response.read(),b'%PDF-test')
        with self.guest.open(urllib.request.Request(self.base+'/api/video?id='+str(v['id']),headers={'Range':'bytes=3-6'})) as response:self.assertEqual(response.read(),b'3456')
        before=len(s['assets']);self.rejected(400,self.editor,'/api/upload?'+urlencode({'kind':'preview','owner_table':'assets','owner_id':a['id'],'name':'bad.png'}),raw=b'not an image')
        self.assertEqual(len(self.state()['assets']),before)
        self.assertEqual(next(x for x in self.state()['assets'] if x['id']==a['id'])['preview_asset_id'],cover['asset_id'])
        self.api(self.admin,'/api/delete',{'table':'technical_experiences','id':eid})
        s=self.state();self.assertEqual(len(s['technical_agreements']),1);self.assertEqual(len(s['videos']),1)

    def test_graph_atomic_save_alias_lookup_bidirectional_links_and_frozen_snapshot(self):
        defect=self.save('defect_types',{'name':'牙伤'})
        camera=self.save('technical_objects',{'name':'检测相机A','object_kind':'相机','version':'V1','specification':'500万像素'})
        record={'name':'紧固件牙伤验证','model_name':'模型A','model_version':'v1','product_id':1,'actual_result':'检出率98%，仅本批100件','test_count':100,'detection_rate':98}
        test=self.api(self.editor,'/api/knowledge/save',{'table':'model_tests','record':record,'links':[{'relation':'测试缺陷','target_table':'defect_types','target_id':defect},{'relation':'使用设备','target_table':'technical_objects','target_id':camera}]})['id']
        exp={'name':'牙伤调试经验','content':'沿牙伤真实边界标注并复核','conditions':'仅适用本批工件和成像条件','confirmation_status':'已验证'}
        links=[{'relation':'适用于','target_table':'defect_types','target_id':defect,'confirmation_status':'已验证','evidence_test_id':test,'conditions':'本批100件'}, {'relation':'测试依据','target_table':'model_tests','target_id':test}]
        eid=self.api(self.editor,'/api/knowledge/save',{'table':'technical_experiences','record':exp,'links':links})['id']
        self.save('entity_aliases',{'entity_table':'defect_types','entity_id':defect,'name':'牙部损伤'})
        result=self.api(self.guest,'/api/knowledge/graph?'+urlencode({'table':'defect_types','id':defect,'depth':1}))
        self.assertTrue(any(n['table']=='model_tests' and n['id']==test for n in result['nodes']))
        self.assertTrue(any(n['table']=='technical_experiences' and n['id']==eid for n in result['nodes']))
        answer=self.api(self.editor,'/api/assistant/chat',{'question':'牙部损伤有哪些测试和规范'})
        self.assertTrue(any(s['source_type']=='knowledge_graph' for s in answer['sources']))
        self.assertIn('牙伤调试经验',answer['answer'])
        s=self.state();old=next(r for r in s['model_tests'] if r['id']==test);snapshot=old['parameter_snapshot'];self.assertIn('500万像素',snapshot)
        obj=next(r for r in s['technical_objects'] if r['id']==camera);self.save('technical_objects',{**obj,'specification':'2000万像素'},camera)
        self.save('model_tests',{**old,'remark':'补充备注'},test)
        self.assertEqual(next(r for r in self.state()['model_tests'] if r['id']==test)['parameter_snapshot'],snapshot)
        old=next(r for r in self.state()['technical_experiences'] if r['id']==eid)
        self.rejected(400,self.editor,'/api/knowledge/save',{'table':'technical_experiences','id':eid,'expected_updated_at':old['updated_at'],'record':{**old,'name':'不应保存'},'links':[{'relation':'适用于','target_table':'defect_types','target_id':99999}]})
        s=self.state();self.assertEqual(s['technical_experiences'][0]['name'],'牙伤调试经验');self.assertEqual(len([l for l in s['knowledge_links'] if l['source_table']=='technical_experiences']),2)
        self.rejected(409,self.editor,'/api/knowledge/save',{'table':'technical_experiences','id':eid,'expected_updated_at':'expired','record':old,'links':links})
        self.rejected(403,self.guest,'/api/knowledge/save',{'table':'technical_experiences','record':exp,'links':links})
        self.rejected(400,self.admin,'/api/model-test-delete',{'id':test})
        self.rejected(400,self.admin,'/api/delete',{'table':'defect_types','id':defect})
        self.rejected(400,self.editor,'/api/save',{'table':'entity_aliases','record':{'entity_table':'app_users','entity_id':1,'name':'非法别名'}})
        self.rejected(400,self.editor,'/api/knowledge/save',{'table':'technical_experiences','record':exp,'links':[]})

    def test_linking_existing_file_promotes_master_record_immediately(self):
        eid=self.save('technical_experiences',{'name':'独立经验','content':'操作步骤'})
        uploaded=self.upload('已有文档.pdf',b'%PDF-existing')
        a=next(a for a in self.state()['assets'] if a['id']==uploaded['asset_id'])
        self.save('assets',{**a,'asset_type':'document'},a['id'])
        self.save('technical_experience_files',{'experience_id':eid,'asset_id':a['id']})
        self.assertEqual(len(self.state()['technical_agreements']),1)
        video=self.upload('已有视频.mp4',b'existing-video')
        self.save('technical_experience_files',{'experience_id':eid,'asset_id':video['asset_id']})
        s=self.state();self.assertEqual(len(s['videos']),1)
        self.assertEqual(s['videos'][0]['asset_id'],video['asset_id'])
        link=next(f for f in s['technical_experience_files'] if f['asset_id']==a['id'])
        self.api(self.admin,'/api/delete',{'table':'technical_experience_files','id':link['id']})
        self.assertEqual(len(self.state()['technical_agreements']),1)

    def test_test_image_delete_protects_registered_knowledge_reference(self):
        test=self.save('model_tests',{'name':'图片引用测试','model_name':'模型A'})
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(20,20),'white').save(out,format='PNG')
        uploaded=self.upload('测试图片.png',out.getvalue(),kind='modeltest',test_id=test,role='input')
        aid=uploaded['asset_id'];file=self.state()['model_test_files'][0]
        link=self.save('knowledge_links',{'source_table':'model_tests','source_id':test,'relation':'相关资料','target_table':'assets','target_id':aid})
        self.rejected(400,self.admin,'/api/model-test-file-delete',{'file_id':file['id']})
        self.assertEqual(len(self.state()['model_test_files']),1)
        self.api(self.admin,'/api/delete',{'table':'knowledge_links','id':link})
        self.api(self.admin,'/api/model-test-file-delete',{'file_id':file['id']})
        self.assertFalse(self.state()['model_test_files'])

if __name__=='__main__':unittest.main()
