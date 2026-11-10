"""Knowledge scope, ambiguity, provenance and generated contract regressions."""
import json,unittest
import test_assistant_http as harness
from knowledge_contract import normalize_term,contains_term
from export_contract import artifacts
from schema import TABLES,json_schema

class KnowledgeContractHTTPTests(unittest.TestCase):
    setUp=harness.AssistantHTTPTests.setUp
    stop_server=harness.AssistantHTTPTests.stop_server
    client=staticmethod(harness.AssistantHTTPTests.client)
    api=harness.AssistantHTTPTests.api
    rejected=harness.AssistantHTTPTests.rejected
    def save(self,t,r,rid=None):return self.api(self.editor,'/api/save',{'table':t,'record':r,'id':rid})['id']
    def test_material_process_and_category_projection(self):
        material=self.save('materials',{'name':'不锈钢'})
        process=self.save('process_types',{'name':'镀锌'})
        parent=self.save('product_categories',{'name':'紧固件'})
        child=self.save('product_categories',{'name':'螺钉','parent_id':parent})
        product=self.save('products',{'name':'M6螺钉','category_id':child,'material_id':material})
        self.save('product_processes',{'product_id':product,'process_id':process})
        graph=self.api(self.guest,'/api/knowledge/graph?table=products&id='+str(product)+'&depth=2')
        self.assertTrue({'产品材质','采用工艺','上级分类'}<={e['relation'] for e in graph['edges']})
        self.save('entity_aliases',{'entity_table':'materials','entity_id':material,'name':'ＳＵＳ　３０４'})
        answer=self.api(self.editor,'/api/assistant/chat',{'question':'sus 304有哪些产品'})
        self.assertTrue(any('不锈钢' in d['text'] for d in answer['sources']))
        self.rejected(400,self.admin,'/api/delete',{'table':'materials','id':material})
    def test_ambiguity_requires_specification_and_normalized_aliases_resolve(self):
        for spec in ('M6','M8'):self.save('products',{'name':'圆环','spec_text':spec})
        reply=self.api(self.editor,'/api/assistant/chat',{'question':'圆环有哪些相关资料'})
        self.assertEqual(reply['mode'],'clarification_needed');self.assertIn('M6',reply['answer']);self.assertIn('M8',reply['answer'])
        resolved=self.api(self.editor,'/api/assistant/chat',{'question':'圆环 Ｍ６有哪些相关资料'})
        self.assertNotEqual(resolved['mode'],'clarification_needed')
    def test_wrong_evidence_scope_rolls_back_and_generic_save_cannot_bypass(self):
        defect=self.save('defect_types',{'name':'牙伤'})
        another=self.save('products',{'name':'M8紧固件'})
        test=self.api(self.editor,'/api/knowledge/save',{'table':'model_tests','record':{'name':'M6牙伤测试','model_name':'模型A','product_id':1,'test_count':100,'actual_result':'本批有效'},'links':[{'relation':'测试缺陷','target_table':'defect_types','target_id':defect}]})['id']
        experience={'name':'错误推广','content':'仅原产品测试过','confirmation_status':'已验证'}
        self.rejected(400,self.editor,'/api/knowledge/save',{'table':'technical_experiences','record':experience,'links':[{'relation':'测试依据','target_table':'model_tests','target_id':test},{'relation':'适用于','target_table':'products','target_id':another,'confirmation_status':'已验证','evidence_test_id':test}]})
        self.rejected(400,self.editor,'/api/save',{'table':'technical_experiences','record':experience})
        state=self.api(self.guest,'/api/state')['data'];self.assertFalse(state['technical_experiences'])
        correct=self.api(self.editor,'/api/knowledge/save',{'table':'technical_experiences','record':{**experience,'name':'M6专用经验'},'links':[{'relation':'测试依据','target_table':'model_tests','target_id':test},{'relation':'适用于','target_table':'products','target_id':1,'confirmation_status':'已验证','evidence_test_id':test}]})['id']
        state=self.api(self.guest,'/api/state')['data'];link=next(l for l in state['knowledge_links'] if l['source_table']=='technical_experiences' and l['source_id']==correct and l['relation']=='测试依据')
        self.rejected(400,self.admin,'/api/delete',{'table':'knowledge_links','id':link['id']})
        self.save('knowledge_links',{'source_table':'technical_experiences','source_id':correct,'relation':'适用于','target_table':'defect_types','target_id':defect,'confirmation_status':'已验证','evidence_test_id':test})
        test_defect=next(l for l in state['knowledge_links'] if l['source_table']=='model_tests' and l['relation']=='测试缺陷')
        self.rejected(400,self.admin,'/api/delete',{'table':'knowledge_links','id':test_defect['id']})
        doc=self.save('technical_agreements',{'name':'验证报告','code':'R-1'})
        existing=next(l for l in state['knowledge_links'] if l['source_table']=='technical_experiences' and l['source_id']==correct and l['relation']=='适用于')
        self.save('knowledge_links',{**existing,'evidence_document_id':doc,'evidence_locator':'第3页表2'},existing['id'])
        reply=self.api(self.editor,'/api/assistant/chat',{'question':'HTTP 测试产品有哪些经验'})
        self.assertTrue(any('第3页表2' in s['text'] for s in reply['sources']))
        self.rejected(400,self.admin,'/api/delete',{'table':'technical_agreements','id':doc})
    def test_retrieval_filters_explicit_product_and_version_conflicts(self):
        product=self.save('products',{'name':'M8产品'})
        for pid,name in ((1,'HTTP 测试产品'),(product,'M8产品')):
            for version in ('v1','v2'):
                tid=self.save('model_tests',{'name':name+'成像测试'+version,'model_name':'模型A','model_version':version,'product_id':pid,'test_count':100,'actual_result':name+' '+version+'独立结果'})
                self.api(self.editor,'/api/knowledge/save',{'table':'technical_experiences','record':{'name':name+'成像经验'+version,'content':'成像检查与光源条件','confirmation_status':'经验建议'},'links':[{'relation':'适用于','target_table':'products','target_id':pid},{'relation':'测试依据','target_table':'model_tests','target_id':tid}]})
        reply=self.api(self.editor,'/api/assistant/chat',{'question':'HTTP 测试产品 v2有哪些成像经验'})
        self.assertTrue(reply['sources'])
        combined='\n'.join(s['text'] for s in reply['sources'])
        self.assertNotIn('M8产品',combined);self.assertNotIn('v1独立结果',combined);self.assertIn('v2独立结果',combined)

class ContractTests(unittest.TestCase):
    def test_normalization_and_ascii_boundaries(self):
        self.assertEqual(normalize_term('ＳＵＳ　３０４'),'sus304');self.assertTrue(contains_term('使用模型A V1','模型A'));self.assertFalse(contains_term('V10','V1'));self.assertFalse(contains_term('M60','M6'))
    def test_contracts_are_derived_from_registered_fields(self):
        from pathlib import Path
        for name,content in artifacts().items():self.assertEqual((Path(__file__).parent/name).read_text('utf-8'),content)
        field=json_schema('model_tests')['properties']['detection_rate'];self.assertEqual(field['maximum'],100);self.assertEqual(field['minimum'],0)
        self.assertIn('evidence_document_id',json_schema('knowledge_links')['properties'])

if __name__=='__main__':unittest.main()
