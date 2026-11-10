"""Shared knowledge vocabulary and deterministic name normalization."""
import re
import unicodedata

ENTITY_TABLES={'projects','products','product_categories','materials','process_types','defect_types','technical_objects','model_tests','technical_experiences','technical_agreements','videos','images','engineering_projects','assets','after_sales'}
RELATIONS={
 '适用于':({'technical_experiences'},{'products','product_categories','materials','process_types','defect_types'}),
 '测试对象':({'model_tests'},{'products'}),
 '测试缺陷':({'model_tests'},{'defect_types'}),
 '使用设备':({'model_tests','technical_experiences'},{'technical_objects'}),
 '参考规范':({'model_tests'},{'technical_experiences'}),
 '测试依据':({'technical_experiences'},{'model_tests'}),
 '相关资料':(ENTITY_TABLES,{'technical_agreements','videos','images','engineering_projects','assets'}),
}
STATUS=['待补充','待验证','经验建议','已验证']

def normalize_term(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value or '')).casefold())

def contains_term(text,term):
    text=unicodedata.normalize('NFKC',str(text or '')).casefold()
    term=normalize_term(term)
    if len(term)<2:return False
    # M6 / V1 must not silently match M60 / V10.
    left=r'(?<![a-z0-9])' if re.match('[a-z0-9]',term) else ''
    right=r'(?![a-z0-9])' if re.search('[a-z0-9]$',term) else ''
    return bool(re.search(left+r'\s*'.join(re.escape(c) for c in term)+right,text))
