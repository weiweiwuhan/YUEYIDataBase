"""Local extraction only; uploaded documents are never sent to an external service."""
from pathlib import Path
import zipfile,xml.etree.ElementTree as ET

def extract(path):
    path=Path(path)
    if path.stat().st_size>30*1024*1024:raise ValueError('文字读取支持 30 MB 以内文件；原文件仍可保存和下载')
    ext=path.suffix.lower()
    if ext in ('.txt','.md','.csv'):
        raw=path.read_bytes()
        for encoding in ('utf-8-sig','utf-16','gb18030'):
            try:text=raw.decode(encoding);break
            except UnicodeError:continue
        else:raise ValueError('无法识别文本编码，请另存为 UTF-8')
    elif ext=='.docx':
        with zipfile.ZipFile(path) as z:
            info=z.getinfo('word/document.xml')
            if info.file_size>10*1024*1024:raise ValueError('文档展开后过大')
            root=ET.fromstring(z.read(info))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text='\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p',ns))
    elif ext=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(path)
        if reader.is_encrypted:raise ValueError('请先解除 PDF 密码保护')
        if len(reader.pages)>200:raise ValueError('文字读取最多支持 200 页 PDF')
        parts=[];length=0
        for page in reader.pages:
            part=page.extract_text() or '';parts.append(part);length+=len(part)
            if length>=100000:break
        text='\n'.join(parts)
    else:raise ValueError('文字读取支持 PDF、DOCX、TXT；扫描件和图片需要先做 OCR，旧版 DOC 请另存为 DOCX')
    text=text.replace('\x00','').strip()
    if not text:raise ValueError('未读取到文字，可能是扫描件。请先做 OCR 后再上传，或手动输入信息')
    return {'text':text[:100000],'truncated':len(text)>100000}
