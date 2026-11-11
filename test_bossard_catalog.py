"""Offline collector/export checks; never contact Bossard or modify business data."""
import io,json,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch,Mock
from collections import deque
from openpyxl import load_workbook
from bossard_catalog import ATTRIBUTES,PublicCrawler,CrawlBlocked,canonical,category_id,product_id,parse_product,export_workbook

class CatalogExportTests(unittest.TestCase):
    def test_source_identifiers_and_pagination(self):
        self.assertEqual(category_id('https://www.bossard.com.cn/a/c/01.100.200.110/?page=3'),'01.100.200.110')
        self.assertEqual(product_id('https://www.bossard.com.cn/a/p/874/'),'BN874')
        self.assertEqual(canonical('https://www.bossard.com.cn/a/c/01.100/?page=3&utm_source=a#x'),'https://www.bossard.com.cn/a/c/01.100/?page=3')
    def test_explicit_public_fields_only(self):
        html='''<html><body><h1>六角螺钉 蓝色镀锌</h1><p>BN 874</p><dl><dt>材质</dt><dd>钢</dd><dt>制造材料</dt><dd>硬化</dd><dt>材料类型</dt><dd>A2</dd><dt>表面处理</dt><dd>蓝色镀锌</dd><dt>标准</dt><dd>~DIN 123</dd></dl></body></html>'''
        row=parse_product(html,'https://www.bossard.com.cn/x/p/874/')
        self.assertEqual(row['material'],'钢');self.assertEqual(row['manufacturing_material'],'硬化');self.assertEqual(row['material_type'],'A2')
        self.assertEqual(row['head_type'],'');self.assertEqual(row['color'],'');self.assertEqual(row['standards'],'~DIN 123')
    def test_matching_bn_and_name_required(self):
        with self.assertRaises(ValueError):parse_product('<h1>访问验证</h1>','https://www.bossard.com.cn/x/p/874/')
    def test_three_material_fields_and_drive_aliases(self):
        html='<h1>螺钉</h1>BN 2034<table><tr><td>材质</td><td>聚酰胺</td></tr><tr><td>材料类型</td><td>PA 6.6</td></tr><tr><td>头形</td><td>平圆头</td></tr><tr><td>驱动槽型</td><td>内六角花形</td></tr></table>'
        row=parse_product(html,'https://www.bossard.com.cn/x/p/2034/')
        self.assertEqual(row['material_type'],'PA 6.6');self.assertEqual(row['manufacturing_material'],'');self.assertEqual(row['head_type'],'平圆头')
    def test_workbook_defaults_review_and_preserves_formula_like_text(self):
        categories=[{'category_id':'01.100','parent_id':'','name':'标准紧固件','source_url':'https://www.bossard.com.cn/c/01.100/'}]
        products=[{'source_product_id':'BN874','bn':'BN 874','name':'=SHOULD_BE_TEXT','source_url':'https://www.bossard.com.cn/x/p/874/','raw_attributes':{'材质':'钢'},'material':'钢','category_ids':['01.100']}]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'review.xlsx';export_workbook(categories,products,path)
            wb=load_workbook(path,data_only=False);ws=wb['产品审核'];headers=[x.value for x in ws[1]]
            self.assertEqual(ws.cell(2,1).value,'待审核');self.assertEqual(ws.cell(2,6).data_type,'s');self.assertEqual(ws.cell(2,6).value,'=SHOULD_BE_TEXT')
            self.assertNotEqual(headers.index('材料类型'),headers.index('制造材料'));self.assertIn('分类候选（待确认）',headers)
    def test_invalid_category_cycle_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):export_workbook([{'category_id':'a','name':'A','parent_id':'b'},{'category_id':'b','name':'B','parent_id':'a'}],[],Path(tmp)/'bad.xlsx')
    def test_robots_403_stops_crawl(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler=PublicCrawler(tmp)
            error=urllib.error.HTTPError('https://www.bossard.com.cn/robots.txt',403,'blocked',{},None)
            with patch('urllib.request.urlopen',side_effect=error),self.assertRaises(CrawlBlocked):crawler.check_robots('https://www.bossard.com.cn/x/p/874/')

class PublicDiscoveryTests(unittest.TestCase):
    def test_nested_sitemap_only_discovers_matching_seed_candidates(self):
        root='https://www.bossard.com.cn'
        target=root+'/cn-zh-cn/eshop/spiral-spring-pins/example/p/874/'
        external='https://example.com/sitemap.xml'
        documents={
            root+'/sitemap.xml':('<sitemapindex><sitemap><loc>'+root+'/public-products.xml</loc></sitemap><sitemap><loc>'+external+'</loc></sitemap></sitemapindex>').encode(),
            root+'/public-products.xml':('<urlset><url><loc>'+target+'</loc></url><url><loc>'+root+'/cn-zh-cn/eshop/unrelated/example/p/999/</loc></url></urlset>').encode()}
        with tempfile.TemporaryDirectory() as tmp:
            crawler=PublicCrawler(tmp);crawler.public_sitemap=Mock(side_effect=lambda url:documents[url])
            discovered={};candidates={}
            crawler.discover_sitemaps({'spiral-spring-pins':{'01.100.400.10'}},discovered,candidates,lambda:None)
            self.assertEqual(discovered,{target:set()})
            self.assertEqual(candidates[target],{'01.100.400.10'})
            self.assertEqual(crawler.public_sitemap.call_count,2)
            self.assertNotIn(external,[c.args[0] for c in crawler.public_sitemap.call_args_list])
            self.assertFalse(crawler.sitemap_pending)

    def test_visible_next_progresses_and_repeated_state_stops(self):
        import re
        from bossard_catalog import START_URL
        for looping in (False,True):
            with self.subTest(looping=looping),tempfile.TemporaryDirectory() as tmp:
                crawler=PublicCrawler(tmp,max_category_pages=10)
                page=Mock();page.url=START_URL;page.index=0
                crawler.navigate=Mock();crawler.guard_page=Mock();crawler.throttle=Mock()
                crawler.links=Mock(side_effect=lambda _:[{'url':'https://www.bossard.com.cn/cn-zh-cn/eshop/spiral-spring-pins/example/p/'+str(874+page.index)+'/','text':'BN','rel':''}])
                button=Mock()
                def click():page.index=(page.index+1)%2 if looping else page.index+1
                button.click.side_effect=click
                crawler.visible_button=lambda _,pattern:button if re.match(pattern,'下一页') and (looping or page.index<2) else None
                discovered={}
                complete=crawler.crawl_category(page,START_URL,{'01.100':{'category_id':'01.100','name':'标准紧固件'}},discovered,deque(),set(),lambda:None)
                self.assertEqual(complete,not looping)
                self.assertEqual(len(discovered),2 if looping else 3)
                self.assertTrue(all(not ids for ids in discovered.values()))
                self.assertEqual(len(crawler.link_candidates),len(discovered))
                self.assertEqual(bool(crawler.pagination_pending),looping)
                self.assertLessEqual(crawler.category_views,3)

    def test_blocked_resume_preserves_discovered_products_and_cache(self):
        from bossard_catalog import START_URL
        categories=[{'category_id':'01.100','parent_id':'','name':'标准紧固件','source_url':START_URL}]
        url='https://www.bossard.com.cn/cn-zh-cn/eshop/spiral-spring-pins/example/p/874/'
        row=parse_product('<h1>弹性圆柱销</h1><p>BN 874</p><dl><dt>材质</dt><dd>钢</dd></dl>',url,['01.100'])
        with tempfile.TemporaryDirectory() as tmp:
            crawler=PublicCrawler(tmp)
            crawler.write_json(crawler.cache/'category-checkpoint.json',{'categories':categories,'product_urls':{url:['01.100']}})
            crawler.write_json(crawler.cache_path(url),row)
            crawler.check_robots=Mock(side_effect=CrawlBlocked('robots禁止，停止'))
            _,products,report=crawler.crawl(categories)
            self.assertEqual(len(products),1);self.assertEqual(products[0]['source_product_id'],'BN874')
            self.assertEqual(products[0]['category_ids'],[])
            self.assertTrue(products[0]['category_candidates'])
            self.assertTrue(report['status'].startswith('访问受限'))
            self.assertEqual(report['discovered_unique_bn_count'],1)
            self.assertFalse(report['complete_catalog']);self.assertEqual(report['cached_product_series_used'],1)
            checkpoint=json.loads((crawler.cache/'category-checkpoint.json').read_text())
            self.assertIn(url,checkpoint['product_urls'])

    def test_zero_discovery_is_failed_and_does_not_claim_complete(self):
        from bossard_catalog import START_URL
        categories=[{'category_id':'01.100','parent_id':'','name':'标准紧固件','source_url':START_URL}]
        with tempfile.TemporaryDirectory() as tmp:
            crawler=PublicCrawler(tmp)
            crawler.write_json(crawler.cache/'category-checkpoint.json',{'completed_category_pages':[START_URL]})
            crawler.check_robots=Mock();crawler.discover_sitemaps=Mock()
            _,products,report=crawler.crawl(categories)
            self.assertEqual(products,[]);self.assertTrue(report['status'].startswith('失败'))
            self.assertEqual(report['discovered_unique_bn_count'],0);self.assertFalse(report['complete_catalog'])

if __name__=='__main__':unittest.main()
