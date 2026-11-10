"""Verify actual PDF/Office first-page rendering, cache invalidation and backfill."""
import hashlib,io,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from media_preview import render_preview,backfill_previews,office_binary

class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.thumbs=self.root/'thumbs'
    def assert_red_page(self,data):
        with Image.open(io.BytesIO(data)) as image:
            r,g,b=image.getpixel((image.width//2,image.height//2));self.assertGreater(r,g+90);self.assertGreater(r,b+90)
    def pdf(self,path,first=(1,0,0)):
        import pymupdf
        with pymupdf.open() as document:
            for color in (first,(0,0,1)):
                page=document.new_page(width=500,height=700);page.draw_rect(page.rect,color=color,fill=color)
            document.save(path)
    def test_pdf_first_page_cache_and_changed_original(self):
        path=self.root/'two.pdf';self.pdf(path);original=path.read_bytes()
        data,info=render_preview(path,self.thumbs,'two.pdf');self.assertEqual(info['kind'],'pdf_first_page');self.assert_red_page(data)
        self.assertEqual(path.read_bytes(),original)
        with patch('media_preview._pdf_image',side_effect=AssertionError('cache not used')):self.assertEqual(render_preview(path,self.thumbs,'two.pdf')[0],data)
        path.unlink();self.pdf(path,(0,1,0));changed,_=render_preview(path,self.thumbs,'two.pdf');self.assertNotEqual(changed,data)
    @unittest.skipUnless(office_binary(),'LibreOffice not installed')
    def test_word_first_page_and_ppt_first_slide(self):
        try:
            from docx import Document
            from pptx import Presentation
            from pptx.dml.color import RGBColor
        except ImportError:self.skipTest('Install requirements-dev.txt for Office fixtures')
        word=self.root/'two.docx';document=Document();document.add_heading('FIRST PAGE',0);document.add_paragraph('First page only.');document.add_page_break();document.add_heading('SECOND PAGE MUST NOT APPEAR',0);document.save(word)
        data,info=render_preview(word,self.thumbs,word.name);self.assertEqual(info['kind'],'office_first_page',info)
        # Compare the actual first-page raster; merely extracting embedded thumbnails would fail this check.
        from media_preview import _office_image
        with patch('media_preview._pdf_image') as pdf:
            import pymupdf
            def inspect(path):
                with pymupdf.open(path) as result:
                    self.assertIn('FIRST PAGE',result[0].get_text());self.assertNotIn('SECOND PAGE',result[0].get_text())
                from PIL import Image
                return Image.new('RGB',(100,100),'red')
            pdf.side_effect=inspect;_office_image(word)
        presentation=Presentation()
        for color in ((255,0,0),(0,0,255)):
            slide=presentation.slides.add_slide(presentation.slide_layouts[6]);fill=slide.background.fill;fill.solid();fill.fore_color.rgb=RGBColor(*color)
        ppt=self.root/'two.pptx';presentation.save(ppt)
        data,info=render_preview(ppt,self.thumbs,ppt.name);self.assertEqual(info['kind'],'office_first_page',info);self.assert_red_page(data)
    def test_existing_documents_backfill_preserves_user_covers(self):
        path=self.root/'existing.pdf';self.pdf(path);original=hashlib.sha256(path.read_bytes()).hexdigest()
        database=self.root/'catalog.db';c=sqlite3.connect(database)
        c.execute('CREATE TABLE assets (id INTEGER,asset_type TEXT,preview_asset_id INTEGER,relative_path TEXT,storage_mode TEXT,file_name TEXT)')
        c.executemany('INSERT INTO assets VALUES (?,?,?,?,?,?)',[(1,'document',None,path.name,'file',path.name),(2,'document',99,path.name,'file','custom.pdf')]);c.commit();c.close()
        def connect():
            c=sqlite3.connect(database);c.row_factory=sqlite3.Row;return c
        execute=lambda c,sql,args=():c.execute(sql,args)
        report=backfill_previews(connect,execute,self.root,self.thumbs);self.assertEqual(report['generated'],1);self.assertEqual(report['items'][0]['asset_id'],1)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),original)
        self.assertEqual(backfill_previews(connect,execute,self.root,self.thumbs)['generated'],1)
    def test_missing_office_dependency_does_not_freeze_placeholder(self):
        path=self.root/'missing.docx';path.write_bytes(b'fixture')
        with patch('media_preview.office_binary',return_value=None):
            data,info=render_preview(path,self.thumbs,path.name);self.assertEqual(info['kind'],'placeholder');self.assertIn('LibreOffice',info['reason'])
        for file in self.thumbs.glob('*.jpg'):
            import os
            os.utime(file,(0,0))
        with patch('media_preview._office_image',return_value=Image.new('RGB',(100,100),'red')):
            data,info=render_preview(path,self.thumbs,path.name);self.assertEqual(info['kind'],'office_first_page');self.assert_red_page(data)

if __name__=='__main__':unittest.main()
