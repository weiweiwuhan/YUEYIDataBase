"""Exercise real TXT, DOCX and PDF extraction without network services."""
import tempfile,zipfile
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject,DictionaryObject,NameObject
from agreement_text import extract

with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    (root/'sample.txt').write_text('技术协议\n检测精度 0.01mm',encoding='utf-8')
    assert '检测精度' in extract(root/'sample.txt')['text']
    with zipfile.ZipFile(root/'sample.docx','w') as z:
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>技术协议编号 TA-001</w:t></w:r></w:p></w:body></w:document>')
    assert 'TA-001' in extract(root/'sample.docx')['text']
    writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 700 Td (Agreement TA-001 tolerance 0.01mm) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    writer.write(root/'sample.pdf')
    assert '0.01mm' in extract(root/'sample.pdf')['text']
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(root/'scan.pdf')
    try:extract(root/'scan.pdf');assert False
    except ValueError as e:assert 'OCR' in str(e)
print('PASS: TXT, DOCX, PDF text extraction and scanned-PDF guidance')
