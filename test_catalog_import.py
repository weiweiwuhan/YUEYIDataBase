"""Reviewed catalog import through isolated HTTP; no live scrape or business data."""
import io,json,unittest
from urllib.parse import urlencode
import test_assistant_http as harness

PRODUCT_HEADERS=['是否导入','来源系统','来源产品编号','BN编号','记录层级','产品名称','分类编号','分类路径','头型','驱动槽型','螺纹','材质','材料类型','制造材料','性能等级','表面处理','颜色','标准','来源URL','抓取时间','原始属性JSON']
CATEGORY_HEADERS=['是否导入','来源系统','分类编号','父分类编号','分类名称','分类路径','来源URL']

def workbook(products=None,categories=None):
    from openpyxl import Workbook
    book=Workbook();sheet=book.active;sheet.title='产品审核';sheet.append(PRODUCT_HEADERS)
    for product in products or []:sheet.append([product.get(header) for header in PRODUCT_HEADERS])
    sheet=book.create_sheet('分类');sheet.append(CATEGORY_HEADERS)
    for row in categories or []:sheet.append([row.get(header) for header in CATEGORY_HEADERS])
    other=book.create_sheet('字段说明');other.append(['说明','制造材料与材料类型保持独立'])
    stream=io.BytesIO();book.save(stream);book.close();return stream.getvalue()

def sample_product(**changes):
    return {'是否导入':'是','来源系统':'Bossard','来源产品编号':'BN874','BN编号':'BN 874','记录层级':'series','产品名称':'公开目录演示螺钉','分类编号':'01.100.01','分类路径':'标准紧固件 > 螺钉','头型':'圆柱头','驱动槽型':'内六角','螺纹':'公制螺纹','材质':'钢','制造材料':'硬化','表面处理':'发黑','来源URL':'https://www.bossard.com.cn/cn-zh-cn/eshop/p/874','抓取时间':'2026-11-11T10:00:00+08:00','原始属性JSON':json.dumps({'材质':'钢','制造材料':'硬化','表面处理':'发黑'},ensure_ascii=False),**changes}

def sample_categories():
    return [{'是否导入':'待审核','来源系统':'Bossard','分类编号':'01.100','分类名称':'标准紧固件','分类路径':'标准紧固件','来源URL':'https://www.bossard.com.cn/cn-zh-cn/eshop/c/01.100'},
            {'是否导入':'待审核','来源系统':'Bossard','分类编号':'01.100.01','父分类编号':'01.100','分类名称':'螺钉','分类路径':'标准紧固件 > 螺钉','来源URL':'https://www.bossard.com.cn/cn-zh-cn/eshop/c/01.100.01'}]

class CatalogHTTPTests(unittest.TestCase):
    setUp=harness.AssistantHTTPTests.setUp
    stop_server=harness.AssistantHTTPTests.stop_server
    client=staticmethod(harness.AssistantHTTPTests.client)
    api=harness.AssistantHTTPTests.api
    rejected=harness.AssistantHTTPTests.rejected
    def state(self):return self.api(self.guest,'/api/state')['data']
    def preview(self,content,opener=None):return self.api(opener or self.admin,'/api/catalog/import-preview?name=review.xlsx',raw=content)
    def commit(self,content,token,opener=None):return self.api(opener or self.admin,'/api/catalog/import?'+urlencode({'name':'review.xlsx','preview_token':token}),raw=content)
    def save(self,table,record,rid=None):return self.api(self.admin,'/api/save',{'table':table,'record':record,'id':rid})['id']
    def test_explicit_review_import_provenance_hierarchy_and_idempotence(self):
        unreviewed=workbook([sample_product(**{'是否导入':'待审核'})],sample_categories())
        before=self.state();preview=self.preview(unreviewed)
        self.assertEqual(preview['selected_count'],0);self.assertEqual(preview['add_count'],0);self.assertEqual(self.state(),before)
        content=workbook([sample_product()],sample_categories());preview=self.preview(content)
        self.assertFalse(preview['errors']);self.assertEqual(preview['add_count'],1);self.assertEqual(preview['category_add_count'],2)
        self.assertEqual(self.state(),before,'preview must never write')
        result=self.commit(content,preview['preview_token']);self.assertEqual(result['add_count'],1)
        data=self.state();self.assertEqual(len(data['products']),1,'catalog series must not become a concrete product')
        product=data['catalog_products'][0]
        self.assertEqual(product['material'],'钢');self.assertEqual(product['manufacturing_material'],'硬化');self.assertIsNone(product['material_type']);self.assertIsNone(product['color'])
        self.assertEqual(product['record_scope'],'series');self.assertEqual(product['created_by'],'admin')
        category_by_name={r['name']:r for r in data['catalog_categories']}
        self.assertEqual(category_by_name['螺钉']['parent_id'],category_by_name['标准紧固件']['id'])
        self.assertEqual(len(data['catalog_product_categories']),1)
        same=self.preview(content);self.assertEqual(same['skip_count'],1);self.assertEqual(same['add_count'],0);self.assertEqual(same['update_count'],0)
        self.commit(content,same['preview_token']);self.assertEqual(self.state(),data)
    def test_three_material_fields_blank_fill_and_manual_conflict_protection(self):
        content=workbook([sample_product()],sample_categories());p=self.preview(content);self.commit(content,p['preview_token'])
        existing=self.state()['catalog_products'][0]
        self.save('catalog_products',{**existing,'head_type':'人工确认头型'},existing['id'])
        updated=workbook([sample_product(**{'头型':'来源新头型','材料类型':'材料类型原文','性能等级':'8.8'})],sample_categories())
        plan=self.preview(updated);self.assertEqual(plan['update_count'],1);self.assertEqual(plan['conflict_count'],1)
        self.commit(updated,plan['preview_token']);record=self.state()['catalog_products'][0]
        self.assertEqual(record['head_type'],'人工确认头型');self.assertEqual(record['material'],'钢');self.assertEqual(record['manufacturing_material'],'硬化');self.assertEqual(record['material_type'],'材料类型原文');self.assertEqual(record['property_class'],'8.8')
    def test_stale_preview_or_changed_file_or_different_user_cannot_commit(self):
        content=workbook([sample_product()],sample_categories());plan=self.preview(content)
        altered=workbook([sample_product(**{'性能等级':'8.8'})],sample_categories())
        self.rejected(400,self.admin,'/api/catalog/import?'+urlencode({'name':'review.xlsx','preview_token':plan['preview_token']}),raw=altered)
        self.save('catalog_categories',{'source_system':'Bossard','source_category_id':'other','name':'其他'})
        self.rejected(400,self.admin,'/api/catalog/import?'+urlencode({'name':'review.xlsx','preview_token':plan['preview_token']}),raw=content)
        self.assertFalse(self.state()['catalog_products'])
        self.rejected(403,self.editor,'/api/catalog/import-preview?name=review.xlsx',raw=content)
        self.rejected(403,self.guest,'/api/catalog/import-preview?name=review.xlsx',raw=content)
    def test_missing_reference_cycle_formula_and_batch_error_never_partially_write(self):
        missing=workbook([sample_product()],[]);plan=self.preview(missing);self.assertGreater(plan['error_count'],0)
        self.rejected(400,self.admin,'/api/catalog/import?'+urlencode({'name':'review.xlsx','preview_token':plan['preview_token']}),raw=missing)
        self.assertFalse(self.state()['catalog_products'])
        categories=sample_categories();categories[0]['父分类编号']='01.100.01'
        plan=self.preview(workbook([sample_product()],categories));self.assertGreater(plan['error_count'],0)
        formula=workbook([sample_product(**{'产品名称':'=HYPERLINK("https://example.org")'})],sample_categories())
        self.rejected(400,self.admin,'/api/catalog/import-preview?name=review.xlsx',raw=formula)
        invalid=workbook([sample_product(),sample_product(**{'来源产品编号':'BN900','BN编号':'BN900','来源URL':'javascript:alert(1)'})],sample_categories())
        plan=self.preview(invalid);self.assertEqual(plan['error_count'],1)
        self.rejected(400,self.admin,'/api/catalog/import?'+urlencode({'name':'review.xlsx','preview_token':plan['preview_token']}),raw=invalid)
        self.assertFalse(self.state()['catalog_products']);self.assertFalse(self.state()['catalog_categories'])
    def test_generic_catalog_writes_and_dedicated_commit_require_admin(self):
        content=workbook([sample_product()],sample_categories());plan=self.preview(content)
        for opener in (self.guest,self.editor):
            self.rejected(403,opener,'/api/catalog/import?'+urlencode({'name':'review.xlsx','preview_token':plan['preview_token']}),raw=content)
        self.commit(content,plan['preview_token']);before=self.state()
        for table in ('catalog_categories','catalog_products','catalog_product_categories'):
            row=before[table][0]
            record={key:value for key,value in row.items() if key not in ('id','created_at','created_by','updated_at','updated_by')}
            for opener in (self.guest,self.editor):
                self.rejected(403,opener,'/api/save',{'table':table,'record':record})
                self.rejected(403,opener,'/api/save',{'table':table,'id':row['id'],'record':record})
                self.rejected(403,opener,'/api/delete',{'table':table,'id':row['id']})
                self.rejected(403,opener,'/api/import',{'data':{table:[row]}})
        self.assertEqual(self.state(),before,'denied generic requests must not change the catalog')
        product=before['catalog_products'][0]
        self.save('catalog_products',{**product,'remark':'管理员审核备注'},product['id'])
        self.assertEqual(self.state()['catalog_products'][0]['remark'],'管理员审核备注')

    def test_same_category_name_under_different_parents_and_multiple_memberships(self):
        categories=sample_categories()+[{'来源系统':'Bossard','分类编号':'02','分类名称':'另一根'}, {'来源系统':'Bossard','分类编号':'02.01','父分类编号':'02','分类名称':'螺钉'}]
        content=workbook([sample_product(**{'分类编号':'01.100.01 | 02.01'})],categories)
        p=self.preview(content);self.assertFalse(p['errors']);self.commit(content,p['preview_token'])
        data=self.state();self.assertEqual(len([r for r in data['catalog_categories'] if r['name']=='螺钉']),2);self.assertEqual(len(data['catalog_product_categories']),2)
        root=next(r for r in data['catalog_categories'] if r['source_category_id']=='01.100');child=next(r for r in data['catalog_categories'] if r['source_category_id']=='01.100.01')
        self.rejected(400,self.admin,'/api/save',{'table':'catalog_categories','id':root['id'],'record':{**root,'parent_id':child['id']}})

if __name__=='__main__':unittest.main()
