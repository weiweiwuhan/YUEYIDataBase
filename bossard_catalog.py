"""Public Bossard catalogue -> review workbook, with resumable, robots-aware crawling.

No login, prices, customer data, CAPTCHA bypass or numeric product-ID probing.
BN rows describe product series; individual dimensional articles are out of scope.
"""

from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request, urllib.robotparser
import shlex
import subprocess
from collections import deque, Counter
from datetime import datetime, timezone
from pathlib import Path
from bossard_images import (
    select_product_image,
    allowed_image_url,
    save_product_image,
    local_image,
    add_workbook_images,
    MAX_IMAGE_BYTES,
)

TOOLKIT_VERSION = "2.0.1"
SOURCE = "bossard_cn"
ROOT_ID = "01.100"
START_URL = "https://www.bossard.com.cn/cn-zh-cn/eshop/products/fastening-technology/standard-fastening-elements/c/01.100/"
USER_AGENT = (
    "YueyiCatalogReview/2.0 (public product metadata and gallery photos; low rate)"
)
ATTRIBUTES = {
    "head_type": ("头形", "头型", "Headform", "Head shape"),
    "drive_type": ("驱动槽型", "驱动", "Drive"),
    "thread_type": ("螺纹", "Thread"),
    "material": ("材质", "Material"),
    "material_type": ("材料类型", "Material type"),
    "manufacturing_material": (
        "制造材料",
        "Material execution",
        "Material execution / manufacturing",
    ),
    "property_class": ("性能等级", "等级", "Property class"),
    "surface_treatment": (
        "表面处理",
        "底涂层",
        "Surface",
        "Surface treatment",
        "Coating",
    ),
    "color": ("颜色", "Colour", "Color"),
    "standards": ("标准", "Standard", "Standards"),
}
FIELD_LABELS = {
    "head_type": "头型",
    "drive_type": "驱动槽型",
    "thread_type": "螺纹",
    "material": "材质",
    "material_type": "材料类型",
    "manufacturing_material": "制造材料",
    "property_class": "性能等级",
    "surface_treatment": "表面处理",
    "color": "颜色",
    "standards": "标准",
}
PRODUCT_COLUMNS = [
    "是否导入",
    "来源系统",
    "来源产品编号",
    "BN编号",
    "记录层级",
    "产品名称",
    "分类编号",
    "分类路径",
    "头型",
    "驱动槽型",
    "螺纹",
    "材质",
    "材料类型",
    "制造材料",
    "性能等级",
    "表面处理",
    "颜色",
    "标准",
    "来源URL",
    "抓取时间",
    "备注",
    "原始属性JSON",
    "分类候选（待确认）",
    "分类证据",
    "未获取字段",
    "采集方式",
    "产品图片",
    "图片本地路径",
    "图片来源URL",
    "图片状态",
    "图片说明",
]
CATEGORY_COLUMNS = [
    "是否导入",
    "来源系统",
    "分类编号",
    "父分类编号",
    "分类名称",
    "分类路径",
    "来源URL",
    "网页声明产品数",
]


class CrawlBlocked(RuntimeError):
    pass


def format_command(arguments):
    """控制台命令按本机 shell 的引用习惯显示；执行仍使用参数列表。"""
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def print_install_help():
    """使用本次解释器生成安装指令，避免装到另一套 Python 环境。"""
    requirement = Path(__file__).with_name("collector_requirements.txt")
    if not requirement.is_file():
        requirement = Path(__file__).with_name("requirements-catalog.txt")
    commands = (
        [sys.executable, "-m", "pip", "install", "-r", str(requirement)],
        [sys.executable, "-m", "playwright", "install", "chromium"],
    )
    print("请先在同一 Python 环境安装采集依赖和浏览器，再重试：", file=sys.stderr)
    for command in commands:
        print(format_command(command), file=sys.stderr, flush=True)


def now():
    """采集记录统一用UTC的ISO8601时间，Excel可据此追溯来源。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value):
    """只归一化显示空白，不推断技术属性。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def category_id(url):
    """从真实 /c/ 链接提取供应商分类编号，保留完整层级。"""
    match = re.search(r"/c/(\d+(?:\.\d+)+)(?:/|$)", urllib.parse.urlsplit(url).path)
    return match.group(1) if match else None


def product_id(url):
    """从真实 /p/ 链接提取BN稳定键，不自行构造编号请求。"""
    match = re.search(r"/p/(\d+)(?:/|$)", urllib.parse.urlsplit(url).path)
    return "BN" + match.group(1) if match else None


def canonical(url):
    """产品/分类页去追踪参数，保留 page 翻页参数；不要用于图片 URL。"""
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query)
    # Only pagination is needed. Never retain tracking, login or customer parameters.
    suffix = (
        urllib.parse.urlencode({"page": query["page"][0]}) if query.get("page") else ""
    )
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, suffix, "")
    )


def allowed_url(url):
    """公开页面范围检查；图片还需使用更严格的 allowed_image_url。"""
    u = urllib.parse.urlsplit(url)
    return (
        u.scheme == "https"
        and u.hostname == "www.bossard.com.cn"
        and not u.username
        and not u.password
    )


def text_attributes(lines):
    """在可见文本行中按明确标签读取相邻值，作为结构化标签解析的补充。"""
    labels = {key for names in ATTRIBUTES.values() for key in names} | {
        "Hardness",
        "硬度",
        "型号",
    }
    result = {}
    for index, line in enumerate(lines[:-1]):
        key = clean(line).rstrip(":：")
        if key in labels:
            value = clean(lines[index + 1])
            if (
                value
                and value not in labels
                and len(value) < 2000
                and value not in ("选择产品规格", "描述", "规格", "規格", "CAD")
            ):
                if key not in result:
                    result[key] = value
    return result


def parse_product(html, url, category_ids=()):
    """解析已渲染详情 HTML，返回一条 BN 系列记录；本函数不联网。

    输入 url 必须含 /p/数字/，正文必须确认同一 BN 且存在产品名称。
    属性来自明确标签，缺失留空；图片只记录主画廊 URL，下载在 collect_image。
    category_ids 是调用者提供的归属；普通链接发现的分类会在 crawl 降为候选。
    """
    from lxml import html as parser

    doc = parser.fromstring(html)
    for element in doc.xpath("//script|//style|//noscript|//nav|//header|//footer"):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    text = "\n".join(doc.itertext())
    pid = product_id(url)
    if not pid:
        raise ValueError("URL中没有BN系列编号")
    numeric = pid[2:]
    if not re.search(
        r"(?<![a-zA-Z0-9])BN\s*" + re.escape(numeric) + r"(?![0-9])", text, re.I
    ):
        raise ValueError("页面正文未确认对应BN编号，可能未加载或被访问拦截")
    titles = [clean(x.text_content()) for x in doc.xpath("//h1")]
    name = next(
        (x for x in titles if x and not re.fullmatch(r"BN\s*\d+", x, re.I)), None
    )
    if not name:
        raise ValueError("页面缺少产品名称")
    attrs = {}
    for dl in doc.xpath("//dl"):
        for label in dl.xpath(".//dt"):
            values = label.xpath("following-sibling::dd[1]")
            if values:
                attrs.setdefault(
                    clean(label.text_content()).rstrip(":："),
                    clean(values[0].text_content()),
                )
    for row in doc.xpath("//tr"):
        cells = row.xpath("./th|./td")
        if len(cells) == 2:
            attrs.setdefault(
                clean(cells[0].text_content()).rstrip(":："),
                clean(cells[1].text_content()),
            )
    # Label and value divs are common on the public product detail page.
    known = {x for values in ATTRIBUTES.values() for x in values}
    for element in doc.xpath("//*[not(*)]"):
        key = clean(element.text_content()).rstrip(":：")
        if key not in known:
            continue
        sibling = element.getnext()
        if sibling is not None:
            value = clean(sibling.text_content())
            if value and value not in known and len(value) < 2000:
                attrs.setdefault(key, value)
    # Use visible lines as a fallback without deriving properties from titles or pictures.
    lines = [clean(x) for x in re.split(r"[\r\n]+", text) if clean(x)]
    for key, value in text_attributes(lines).items():
        attrs.setdefault(key, value)
    photo = select_product_image(doc, url)
    row = {
        "source_system": SOURCE,
        "source_product_id": pid,
        "bn": "BN " + numeric,
        "record_scope": "series",
        "name": name,
        "source_url": canonical(url),
        "fetched_at": now(),
        "raw_attributes": attrs,
        "acquisition_method": "public_rendered_page",
        "category_ids": list(category_ids),
        "field_sources": {},
    }
    for field, labels in ATTRIBUTES.items():
        key = next((x for x in labels if attrs.get(x)), None)
        row[field] = attrs.get(key, "")
        if key:
            row["field_sources"][field] = key
    row.update(photo)
    row["missing_fields"] = [field for field in ATTRIBUTES if not row[field]]
    return row


def normalise_input(product):
    """兼容旧采集JSON字段名，不把BN系列转换为实际检测产品。"""
    result = dict(product)
    aliases = {
        "source_id": "source_product_id",
        "head_shape": "head_type",
        "thread": "thread_type",
        "record_level": "record_scope",
    }
    for old, new in aliases.items():
        if new not in result:
            result[new] = result.get(old, "")
    result["record_scope"] = (
        "series"
        if result.get("record_scope") in ("", "product_series")
        else result["record_scope"]
    )
    result.setdefault("source_system", SOURCE)
    result.setdefault(
        "category_ids", [result["category_code"]] if result.get("category_code") else []
    )
    result.setdefault("review_note", "")
    return result


def category_paths(categories):
    """按 parent_id 建完整分类路径；父级缺失或循环时抛 ValueError。"""
    lookup = {c["category_id"]: c for c in categories}
    paths = {}

    def visit(cid, seen=None):
        if cid in paths:
            return paths[cid]
        seen = set() if seen is None else set(seen)
        if cid in seen:
            raise ValueError("分类形成循环：" + cid)
        seen.add(cid)
        row = lookup[cid]
        parent = row.get("parent_id") or row.get("parent_category_id") or ""
        if parent and parent not in lookup:
            raise ValueError("分类父级缺失：" + parent)
        paths[cid] = (visit(parent, seen) if parent else []) + [row["name"]]
        return paths[cid]

    for cid in lookup:
        visit(cid)
    return paths


def export_workbook(
    categories, products, destination, report=None, image_root=None, embed_images=True
):
    """离线生成待审核 XLSX，不访问源站、不连接业务数据库。

    categories/products 为记录列表；image_root 是包含 images/ 的缓存根目录。
    embed_images=False 只写图片路径；返回行数、输出路径和实际嵌图数量。
    所有审核选择初始为“待审核”。调用者负责决定是否允许覆盖 destination。
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.worksheet.datavalidation import DataValidation

    products = [normalise_input(x) for x in products]
    paths = category_paths(categories)
    report = dict(report or {})
    wb = Workbook()
    instructions = wb.active
    instructions.title = "使用说明"
    notes = [
        ("项目", "说明"),
        ("导出时间", now()),
        (
            "范围",
            "Bossard 中国标准紧固件公开BN产品系列；不包含具体尺寸SKU、价格、库存或客户账户数据。",
        ),
        ("本次采集状态", report.get("status", "审核数据导出")),
        ("分类行数", len(categories)),
        ("产品系列行数", len(products)),
        (
            "审核步骤",
            "先查看来源URL和原始属性。确认后将“产品审核”或“分类”中的“是否导入”改为“是”，其他保持待审核或改否。",
        ),
        (
            "分类确认",
            "“分类候选（待确认）”不是已确认分类；审核后把正确分类编号填入“分类编号”，多个分类用 | 分隔。",
        ),
        (
            "材料字段",
            "材质、材料类型、制造材料为独立原字段。示例：钢/材料类型/硬化不能互相代填。",
        ),
        (
            "缺失值",
            "空白仅表示公开页面未获取到该字段；不会从产品名称、图片或表面处理推断颜色等信息。",
        ),
        (
            "规格范围",
            "BN是产品系列，记录层级=series，不代表某个具体尺寸产品。客户产品规格表保持原有语义。",
        ),
        (
            "导入方式",
            "网站→紧固件目录→导入审核Excel→预览校验→确认导入。默认只补空值，冲突保留原有非空值，重复导入跳过。",
        ),
        (
            "分类祖先",
            "选中产品引用的分类及祖先会自动补入；如果分类明确标为否，相关产品会在预览中提示错误。",
        ),
        (
            "待审核安全默认",
            "本文件所有数据初始均为待审核。不会自动写入现有业务数据库。",
        ),
        (
            "数据准确性",
            "保留标准中的 ~ 等原始符号。分类是供应商目录分类，不自动代表本公司产品分类或汽车行业标准。",
        ),
        (
            "来源与许可",
            "仅采集公开技术事实与来源链接；批量使用需遵守网站使用条款、robots和适用授权。",
        ),
    ]
    for row in notes:
        instructions.append(row)
    cat = wb.create_sheet("分类")
    cat.append(CATEGORY_COLUMNS)
    for item in sorted(categories, key=lambda x: x["category_id"]):
        cid = item["category_id"]
        cat.append(
            [
                "待审核",
                item.get("source_system", SOURCE),
                cid,
                item.get("parent_id") or item.get("parent_category_id") or "",
                item["name"],
                " > ".join(paths[cid]),
                item.get("source_url", ""),
                item.get("declared_product_count", ""),
            ]
        )
        cat.cell(cat.max_row, 5).alignment = Alignment(
            indent=min(len(paths[cid]) - 1, 10), vertical="top"
        )
    sheet = wb.create_sheet("产品审核")
    sheet.append(PRODUCT_COLUMNS)
    ordered_products = sorted(
        products,
        key=lambda x: int(re.sub(r"\D", "", x.get("source_product_id") or "0") or 0),
    )
    for p in ordered_products:
        categories_for_row = p.get("category_ids") or []
        pathtext = " | ".join(
            " > ".join(paths[cid]) for cid in categories_for_row if cid in paths
        )
        candidates = " | ".join(
            (
                c.get("category_code", "")
                + " "
                + " > ".join(c.get("category_path", []))
            ).strip()
            for c in p.get("category_candidates", [])
        )
        evidence = " | ".join(
            c.get("evidence", "") for c in p.get("category_candidates", [])
        ) or p.get("category_status", "")
        sheet.append(
            [
                "待审核",
                p.get("source_system", SOURCE),
                p.get("source_product_id", ""),
                p.get("bn", ""),
                p.get("record_scope", "series"),
                p.get("name", ""),
                " | ".join(categories_for_row),
                pathtext,
            ]
            + [p.get(field, "") for field in ATTRIBUTES]
            + [
                p.get("source_url", ""),
                p.get("fetched_at", ""),
                p.get("review_note", ""),
                json.dumps(
                    p.get("raw_attributes", {}), ensure_ascii=False, sort_keys=True
                ),
                candidates,
                evidence,
                "、".join(FIELD_LABELS.get(f, f) for f in p.get("missing_fields", [])),
                p.get("acquisition_method", ""),
                " ",
                p.get("image_path", ""),
                p.get("image_url", ""),
                p.get("image_status", "pending"),
                p.get("image_note", ""),
            ]
        )
    dictionary = wb.create_sheet("字段字典")
    dictionary.append(["导入字段", "官网原字段候选", "含义"])
    for field, labels in ATTRIBUTES.items():
        dictionary.append(
            [
                FIELD_LABELS[field],
                " / ".join(labels),
                "保留公开原值；缺失留空，不从其他属性推断",
            ]
        )
    dictionary.append(
        [
            "来源产品编号",
            "详情页BN编号",
            "稳定键，例如BN874；与来源系统共同用于幂等更新",
        ]
    )
    dictionary.append(
        ["分类编号", "官网 /c/ 分类代码", "多个明确归属用 | 分隔，候选单独审核"]
    )
    summary = wb.create_sheet("采集报告")
    summary.append(["指标", "内容"])
    for key, value in {
        "exported_category_count": len(categories),
        "exported_product_series_count": len(products),
        **report,
    }.items():
        summary.append(
            [
                key,
                (
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else value
                ),
            ]
        )
    validation = DataValidation(
        type="list", formula1='"待审核,是,否"', allow_blank=True
    )
    validation.errorTitle = "请选择审核状态"
    validation.error = "仅支持待审核、是、否"
    validation.showErrorMessage = True
    for ws in (cat, sheet):
        from copy import copy

        dv = copy(validation)
        ws.add_data_validation(dv)
        dv.add("A2:A" + str(max(5000, ws.max_row + 100)))
    for ws in wb:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.row_dimensions[1].height = 26
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="143D4B")
            cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF")
            cell.alignment = Alignment(vertical="center")
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                if not cell.alignment.indent:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.font = Font(name="Microsoft YaHei", size=10)
            if ws in (cat, sheet):
                row[0].fill = PatternFill("solid", fgColor="FFF1BA")
        for column in ws.columns:
            letter = column[0].column_letter
            header = str(column[0].value or "")
            ws.column_dimensions[letter].width = (
                55
                if header in ("来源URL", "原始属性JSON", "说明", "内容")
                else (
                    48
                    if header in ("分类路径", "分类候选（待确认）", "分类证据", "备注")
                    else 30 if header in ("产品名称", "分类名称", "未获取字段") else 19
                )
            )
    for ws in (cat, sheet):
        source_column = next(i + 1 for i, c in enumerate(ws[1]) if c.value == "来源URL")
        for row in ws.iter_rows(min_row=2):
            cell = row[source_column - 1]
            if cell.value and allowed_url(cell.value):
                cell.hyperlink = cell.value
                cell.font = Font(
                    name="Microsoft YaHei", size=10, color="176B9B", underline="single"
                )
    image_column = PRODUCT_COLUMNS.index("产品图片") + 1
    sheet.column_dimensions[sheet.cell(1, image_column).column_letter].width = 23
    embedded = add_workbook_images(
        sheet, ordered_products, image_column, image_root, embed_images
    )
    summary.append(["embedded_image_count", embedded])
    instructions.append(
        [
            "产品主图",
            "产品图片为详情页主画廊照片；本地PNG供查看，.source文件保留下载原图。缺图不使用推荐图或技术图替代。图片列是审核辅助，不会通过Excel自动写入业务图片库。",
        ]
    )
    instructions.column_dimensions["A"].width = 23
    instructions.column_dimensions["B"].width = 110
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destination)
    return {
        "categories": len(categories),
        "product_series": len(products),
        "path": str(destination),
        "embedded_images": embedded,
    }


class PublicCrawler:
    """有状态的单进程公开目录采集器，适合本地运行。

    cache 保存断点、每个产品的 JSON、原图和 PNG；delay 为请求间隔秒数，
    最低1秒，robots 声明更慢时采用更慢值。max_products=0 不主动限制数量。
    executable 是可选 Chrome/Chromium 路径；download_images 默认开启。
    images_only=True 仅给缓存中已有产品补图，不发现新产品或清空目录断点。
    一个缓存目录同一时刻只运行一个进程，避免互相覆盖断点文件。
    """

    def __init__(
        self,
        cache,
        delay=1.5,
        max_products=0,
        max_category_pages=1000,
        executable=None,
        max_sitemap_pages=200,
        download_images=True,
        images_only=False,
    ):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.delay = max(float(delay), 1.0)
        self.max_products = max(int(max_products), 0)
        self.max_category_pages = max(int(max_category_pages), 1)
        self.max_sitemap_pages = max(int(max_sitemap_pages), 1)
        self.executable = executable
        self.last = 0.0
        self.policies = {}
        self.failures = []
        self.visited_categories = set()
        self.visited_products = set()
        self.access_blocked = False
        self.completed_categories = set()
        self.robots_sitemaps = []
        self.robots_status = "not_checked"
        self.sitemaps_done = set()
        self.sitemap_pending = []
        self.sitemap_results = []
        self.sitemap_sources = {}
        self.link_candidates = {}
        self.link_sources = {}
        self.pagination_pending = []
        self.category_views = 0
        self.load_more_clicks = 0
        self.sitemap_requests = 0
        self.download_images = download_images
        self.images_only = images_only
        self.browser_block = None
        self.resumed = False
        self.cached_products = 0
        self.runtime_error = None
        self.runtime_phase = "not_started"
        self.new_image_count = 0

    def throttle(self):
        """页面、sitemap 和图片共用同一串行限速时钟。"""
        remaining = self.delay - (time.monotonic() - self.last)
        if remaining > 0:
            time.sleep(remaining)
        self.last = time.monotonic()

    @staticmethod
    def blocked_text(text):
        """识别人机验证提示，防止把验证页当成产品详情解析。"""
        return bool(
            re.search(
                r"verify you are human|captcha|访问过于频繁|安全验证|人机验证",
                text,
                re.I,
            )
        )

    def failure(self, url, error, phase):
        """收集失败URL、处理阶段与原因，稍后写入报告。"""
        self.failures.append(
            {"url": str(url), "phase": phase, "reason": str(error)[:400]}
        )

    def check_robots(self, url):
        """首次读取并缓存 robots 规则；禁止访问/受限时抛 CrawlBlocked。"""
        if not allowed_url(url):
            raise CrawlBlocked("URL超出获准的Bossard中国公开目录范围：" + url)
        root = "https://www.bossard.com.cn"
        if root not in self.policies:
            self.throttle()
            parser = urllib.robotparser.RobotFileParser(root + "/robots.txt")
            try:
                req = urllib.request.Request(
                    root + "/robots.txt", headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    final_url = response.geturl()
                    if not allowed_url(final_url):
                        raise CrawlBlocked("robots.txt重定向超出获准同域范围，停止采集")
                    raw = response.read(1000001)
                if len(raw) > 1000000:
                    raise CrawlBlocked(
                        "robots.txt超过读取上限，无法确认站点规则，停止采集"
                    )
                body = raw.decode("utf-8-sig", errors="replace")
                if body.lstrip().startswith("<") or (
                    self.blocked_text(body)
                    and not re.search(r"^\s*User-agent\s*:", body, re.I | re.M)
                ):
                    raise CrawlBlocked("robots.txt返回验证页或非规则正文，停止采集")
                parser.parse(body.splitlines())
                self.robots_status = "fetched"
                self.robots_sitemaps = list(parser.site_maps() or [])
                crawl_delay = parser.crawl_delay(USER_AGENT)
                rate = parser.request_rate(USER_AGENT)
                self.delay = max(
                    self.delay,
                    float(crawl_delay or 0),
                    (
                        float(rate.seconds) / rate.requests
                        if rate and rate.requests
                        else 0
                    ),
                )
            except urllib.error.HTTPError as error:
                if error.code in (404, 410):
                    parser.parse([])
                    self.robots_status = "missing_http_" + str(error.code)
                else:
                    raise CrawlBlocked(
                        "robots.txt访问失败（HTTP " + str(error.code) + "）；未继续抓取"
                    ) from None
            except urllib.error.URLError as error:
                raise CrawlBlocked(
                    "当前网络无法访问Bossard：" + str(error.reason)
                ) from None
            self.policies[root] = parser
        if not self.policies[root].can_fetch(USER_AGENT, url):
            raise CrawlBlocked("robots.txt不允许抓取：" + url)

    def cache_path(self, url):
        """产品来源 URL 的 SHA-256 作为文件名，避免中文、问号等路径问题。"""
        return self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".json")

    def write_json(self, path, value):
        """先写同目录临时文件再替换，减少中断导致半个 JSON 的风险。"""
        path = Path(path)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    def read_json(self, path, default):
        """断点不存在时返回默认值；坏JSON记入失败项而不是假装成功。"""
        path = Path(path)
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError) as error:
            self.failure(path, "缓存无法读取：" + str(error), "checkpoint")
            return default

    def candidate_ids(self, url, seed_slugs):
        """Only observed taxonomy slugs identify candidates; never probe numeric IDs."""
        if not allowed_url(url) or not product_id(url):
            return set()
        path = urllib.parse.urlsplit(url).path
        prefix = "/cn-zh-cn/eshop/"
        if not path.startswith(prefix):
            return set()
        return set(seed_slugs.get(path[len(prefix) :].split("/", 1)[0], set()))

    def public_sitemap(self, url):
        # The custom redirect handler prevents sitemap requests from leaving the host.
        """在同站范围读取公开XML，限制大小并检查重定向；不跟随外站地址。"""

        class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if not allowed_url(newurl):
                    raise CrawlBlocked("公开sitemap重定向跨域，停止采集：" + newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        self.check_robots(url)
        self.throttle()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/xml,text/xml,application/gzip;q=0.8",
            },
        )
        try:
            with urllib.request.build_opener(SameOriginRedirect()).open(
                req, timeout=30
            ) as response:
                if not allowed_url(response.geturl()):
                    raise CrawlBlocked("公开sitemap重定向超出同域范围")
                body = response.read(20 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403, 429):
                raise CrawlBlocked(
                    "公开sitemap返回HTTP " + str(error.code) + "，停止采集"
                ) from None
            raise
        if len(body) > 20 * 1024 * 1024:
            raise ValueError("公开sitemap超过20 MiB读取上限，未确认覆盖")
        if body[:2] == b"\x1f\x8b":
            import gzip, io

            with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
                body = stream.read(20 * 1024 * 1024 + 1)
            if len(body) > 20 * 1024 * 1024:
                raise ValueError("公开sitemap解压后超过20 MiB读取上限")
        preview = body[:4000].decode("utf-8", errors="replace")
        if self.blocked_text(preview):
            raise CrawlBlocked("公开sitemap返回人工验证页，停止采集")
        return body

    def discover_sitemaps(self, seed_slugs, discovered, candidates, save):
        """读取真实存在的公开 sitemap 链接；分类 slug 仅产生候选归属。"""
        from xml.etree import ElementTree

        root = "https://www.bossard.com.cn"
        # /sitemap.xml was observed publicly; other addresses must be declared in robots or XML.
        queue = deque(
            dict.fromkeys(
                self.sitemap_pending + self.robots_sitemaps + [root + "/sitemap.xml"]
            )
        )
        queued = set(queue)
        failed_maps = []
        while queue and self.sitemap_requests < self.max_sitemap_pages:
            url = urllib.parse.urljoin(root + "/", queue.popleft())
            queued.discard(url)
            if not allowed_url(url):
                self.sitemap_results.append(
                    {"url": url, "status": "skipped_outside_origin"}
                )
                continue
            if url in self.sitemaps_done:
                continue
            self.sitemap_requests += 1
            try:
                body = self.public_sitemap(url)
                if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
                    raise ValueError("sitemap包含DTD/实体声明，未解析")
                document = ElementTree.fromstring(body)
                kind = document.tag.rsplit("}", 1)[-1]
                if kind not in ("sitemapindex", "urlset"):
                    raise ValueError("响应不是sitemapindex或urlset")
                found = 0
                for entry in document:
                    name = entry.tag.rsplit("}", 1)[-1]
                    if name != ("sitemap" if kind == "sitemapindex" else "url"):
                        continue
                    location = next(
                        (
                            clean(x.text)
                            for x in entry
                            if x.tag.rsplit("}", 1)[-1] == "loc"
                        ),
                        None,
                    )
                    if not location:
                        continue
                    target = urllib.parse.urljoin(url, location)
                    if not allowed_url(target):
                        continue
                    if kind == "sitemapindex":
                        if target not in self.sitemaps_done and target not in queued:
                            queue.append(target)
                            queued.add(target)
                    else:
                        target = canonical(target)
                        ids = self.candidate_ids(target, seed_slugs)
                        if ids:
                            discovered.setdefault(target, set())
                            candidates.setdefault(target, set()).update(ids)
                            self.sitemap_sources.setdefault(target, set()).add(url)
                            found += 1
                self.sitemaps_done.add(url)
                self.sitemap_results.append(
                    {
                        "url": url,
                        "status": "parsed",
                        "kind": kind,
                        "matched_standard_product_urls": found,
                    }
                )
            except CrawlBlocked:
                failed_maps.append(url)
                raise
            except urllib.error.HTTPError as error:
                if error.code in (404, 410):
                    self.sitemaps_done.add(url)
                    self.sitemap_results.append(
                        {"url": url, "status": "not_found", "http_status": error.code}
                    )
                else:
                    failed_maps.append(url)
                    self.failure(url, error, "sitemap")
            except Exception as error:
                failed_maps.append(url)
                self.failure(url, error, "sitemap")
            finally:
                self.sitemap_pending = list(dict.fromkeys(failed_maps + list(queue)))
                save()
        self.sitemap_pending = list(dict.fromkeys(failed_maps + list(queue)))
        if queue:
            self.failure(
                root + "/sitemap.xml",
                "达到公开sitemap页数上限，仍有"
                + str(len(queue))
                + "个明确列出的sitemap未处理",
                "sitemap_limit",
            )

    def guard_page(self, page):
        """浏览器请求受限或显示验证内容时停止，不尝试绕过。"""
        if self.browser_block:
            raise CrawlBlocked(self.browser_block)
        self.check_robots(page.url)
        if self.blocked_text(
            page.title() + " " + page.locator("body").inner_text()[:4000]
        ):
            raise CrawlBlocked("页面要求人工验证，停止采集")

    def navigate(self, page, url):
        """导航前检查范围、robots和间隔，导航后检查访问状态。"""
        self.check_robots(url)
        self.throttle()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            if self.browser_block:
                raise CrawlBlocked(self.browser_block) from None
            raise
        if response and response.status in (401, 403, 429):
            raise CrawlBlocked(
                "站点返回HTTP " + str(response.status) + "，停止采集，不尝试绕过"
            )
        if response and response.status >= 400:
            raise ValueError("公开页面返回HTTP " + str(response.status))
        page.wait_for_timeout(1200)
        self.guard_page(page)

    def links(self, page):
        """读取浏览器中实际存在的链接，用于发现分类和BN详情。"""
        return page.eval_on_selector_all(
            "a[href]",
            "els=>els.filter(a=>a.getClientRects().length&&getComputedStyle(a).visibility!=='hidden').map(a=>({url:a.href,text:(a.innerText||a.getAttribute('aria-label')||'').trim(),rel:a.rel}))",
        )

    def visible_button(self, page, pattern):
        """只寻找可见的翻页/加载按钮，不猜测内部私有接口。"""
        matches = page.get_by_role("button", name=re.compile(pattern, re.I))
        for index in range(matches.count()):
            button = matches.nth(index)
            if button.is_visible() and button.is_enabled():
                return button
        return None

    def state_key(self, page, links):
        """为当前页面和链接集合生成签名，识别分页是否真正推进。"""
        return (
            canonical(page.url),
            tuple(
                sorted(
                    {
                        canonical(x["url"])
                        for x in links
                        if allowed_url(x["url"]) and product_id(x["url"])
                    }
                )
            ),
        )

    def pagination_issue(self, url, base_url, reason):
        """把无法确认的分页记录在报告中，保留未完成事实。"""
        issue = {"url": url, "base_url": base_url, "reason": reason}
        if issue not in self.pagination_pending:
            self.pagination_pending.append(issue)

    def click_control(self, page, button):
        """对可见控制执行限速点击，随后检查是否遇到访问验证。"""
        self.guard_page(page)
        self.throttle()
        try:
            button.click()
        except Exception:
            if self.browser_block:
                raise CrawlBlocked(self.browser_block) from None
            raise
        page.wait_for_timeout(800)
        self.guard_page(page)

    def harvest(self, page, cid, categories, discovered, queue, queued):
        """收集页面真实链接并扩展队列；分类线索保留为候选。"""
        links = self.links(page)
        for link in links:
            candidate = canonical(link["url"])
            if not allowed_url(candidate):
                continue
            code = category_id(candidate)
            pid = product_id(candidate)
            if code and (code == ROOT_ID or code.startswith(ROOT_ID + ".")):
                if code not in categories:
                    label = re.sub(
                        r"\s*\d+\s*(产品|Products?)\s*$",
                        "",
                        clean(link["text"]),
                        flags=re.I,
                    )
                    if label:
                        categories[code] = {
                            "category_id": code,
                            "parent_id": code.rsplit(".", 1)[0],
                            "name": label,
                            "source_url": candidate,
                        }
                if (
                    candidate != canonical(page.url)
                    and candidate not in self.completed_categories
                    and candidate not in queued
                ):
                    queue.append(candidate)
                    queued.add(candidate)
            if pid and urllib.parse.urlsplit(candidate).path.startswith(
                "/cn-zh-cn/eshop/"
            ):
                # Ordinary anchors may be navigation or recommendations. Their placement is unverified.
                discovered.setdefault(candidate, set())
                self.link_candidates.setdefault(candidate, set()).add(cid)
                self.link_sources.setdefault(candidate, set()).add(canonical(page.url))
        return links

    def crawl_category(self, page, url, categories, discovered, queue, queued, save):
        """读取一个分类的可见列表与分页，遇上限或重复状态保留待处理项。"""
        base_url = url
        states = set()
        state_urls = set()
        self.navigate(page, url)
        while True:
            if self.category_views >= self.max_category_pages:
                self.pagination_issue(
                    canonical(page.url),
                    base_url,
                    "达到分类页面/Next翻页上限，分页覆盖待确认",
                )
                return False
            current = canonical(page.url)
            cid = category_id(current)
            if not cid or not (cid == ROOT_ID or cid.startswith(ROOT_ID + ".")):
                self.pagination_issue(
                    current, base_url, "下一页离开标准紧固件分类路径，未继续"
                )
                return False
            self.visited_categories.add(current)
            self.category_views += 1
            state_urls.add(current)
            print("分类页面", self.category_views, current, flush=True)
            for step in range(200):
                self.guard_page(page)
                page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
                page.wait_for_timeout(400)
                links = self.harvest(page, cid, categories, discovered, queue, queued)
                save()
                more = self.visible_button(
                    page,
                    r"^(?:加载更多|显示更多|顯示更多|載入更多|Load more|Show more)(?:\s*(?:显示更多|顯示更多))?$",
                )
                if more is None:
                    break
                previous = self.state_key(page, links)
                self.click_control(page, more)
                self.load_more_clicks += 1
                changed = self.links(page)
                for _ in range(3):
                    if self.state_key(page, changed) != previous:
                        break
                    page.wait_for_timeout(400)
                    self.guard_page(page)
                    changed = self.links(page)
                # Retain newly visible URLs before any stop, timeout or checkpoint.
                self.harvest(page, cid, categories, discovered, queue, queued)
                save()
                if self.state_key(page, changed) == previous:
                    self.pagination_issue(
                        current,
                        base_url,
                        "显示更多点击后未发现页面或产品链接变化，覆盖待确认",
                    )
                    return False
            else:
                self.pagination_issue(
                    current, base_url, "达到单页显示更多点击上限，覆盖待确认"
                )
                return False
            links = self.harvest(page, cid, categories, discovered, queue, queued)
            signature = self.state_key(page, links)
            save()
            if signature in states:
                self.pagination_issue(
                    current, base_url, "下一页出现重复页面状态，停止以避免循环"
                )
                return False
            states.add(signature)
            next_button = self.visible_button(
                page,
                r"^(?:下一页|下一頁|Next(?:\s+page)?|Go to next page)(?:\s*[›»→])?$",
            )
            if next_button is None:
                empty_leaf = not any(product_id(x["url"]) for x in links) and not any(
                    x.startswith(cid + ".") for x in categories
                )
                self.completed_categories.update(state_urls)
                self.pagination_pending = [
                    x
                    for x in self.pagination_pending
                    if x.get("base_url") != base_url and x.get("url") not in state_urls
                ]
                if empty_leaf:
                    self.pagination_issue(
                        current,
                        base_url,
                        "末级分类未显示任何产品链接，空类别或动态内容加载情况待确认",
                    )
                return True
            if self.category_views >= self.max_category_pages:
                self.pagination_issue(
                    current, base_url, "存在可见下一页按钮但已达到分类页面上限"
                )
                return False
            self.click_control(page, next_button)
            next_links = self.links(page)
            for _ in range(3):
                if self.state_key(page, next_links) != signature:
                    break
                page.wait_for_timeout(400)
                self.guard_page(page)
                next_links = self.links(page)
            if self.state_key(page, next_links) == signature:
                self.pagination_issue(
                    canonical(page.url),
                    base_url,
                    "下一页点击后页面状态未变化，分页待确认",
                )
                return False

    def needs_image(self, row):
        """已有 PNG 文件就跳过；文件丢失时即使状态写着 downloaded 也补采。"""
        return self.download_images and local_image(self.cache, row) is None

    def collect_image(self, page, row):
        """给一条产品补图，更新 row 并始终保存产品缓存。

        page 为 Playwright Page；仅旧缓存缺少 image_url 时需要它重读详情页。
        已有 image_url 时可传 None。403/429/robots 禁止会抛 CrawlBlocked，
        让整次采集停止；普通坏图记录 failed，不删除已成功的产品属性。
        """
        if not self.needs_image(row):
            return
        try:
            if not row.get("image_url"):
                if page is None:
                    raise ValueError("旧缓存缺少主图URL，需要重新读取产品详情页")
                self.navigate(page, row["source_url"])
                page.wait_for_timeout(700)
                self.guard_page(page)
                verified = parse_product(page.content(), row["source_url"])
                for key in (
                    "image_url",
                    "image_evidence",
                    "image_status",
                    "image_note",
                ):
                    row[key] = verified[key]
            url = row.get("image_url", "")
            if not url:
                row["image_status"] = "not_found"
                return
            if not allowed_image_url(url):
                raise ValueError("图片URL不是已允许的Bossard同站产品媒体路径")
            crawler = self

            class ImageRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    if not allowed_image_url(newurl):
                        raise ValueError("主图重定向离开已允许的媒体范围")
                    crawler.check_robots(newurl)
                    crawler.throttle()
                    return super().redirect_request(req, fp, code, msg, headers, newurl)

            self.check_robots(url)
            self.throttle()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Referer": row["source_url"],
                    "Accept": "image/webp,image/png,image/jpeg,image/*;q=0.8",
                },
            )
            with urllib.request.build_opener(ImageRedirect()).open(
                req, timeout=30
            ) as response:
                if not allowed_image_url(response.geturl()):
                    raise ValueError("主图最终地址超出允许范围")
                content = response.read(MAX_IMAGE_BYTES + 1)
            save_product_image(self.cache, row, content)
            row["image_fetched_at"] = now()
            self.new_image_count += 1
        except (CrawlBlocked, urllib.error.HTTPError) as error:
            blocked = isinstance(error, CrawlBlocked) or error.code in (401, 403, 429)
            row.update(
                image_status="blocked" if blocked else "failed",
                image_note=str(error)[:500],
            )
            if blocked:
                raise CrawlBlocked(
                    "主图访问受限，已保存元数据并停止采集：" + str(error)
                ) from None
            self.failure(
                row.get("image_url") or row["source_url"], error, "product_image"
            )
        except Exception as error:
            row.update(image_status="failed", image_note=str(error)[:500])
            self.failure(
                row.get("image_url") or row["source_url"], error, "product_image"
            )
        finally:
            self.write_json(self.cache_path(row["source_url"]), row)

    def crawl(self, categories, refresh=False):
        """从分类种子和已有断点采集，返回 (分类列表, 产品列表, 报告字典)。

        先恢复已成功产品，再联网；网站受限时仍返回这些数据供导出。
        refresh=True 重新读取属性页；补图模式不支持 refresh。
        各阶段错误和剩余项进入报告；complete_catalog 始终不自动宣称完整。
        """
        if self.images_only and refresh:
            raise ValueError("只补图模式不能与刷新缓存同用")
        categories = {x["category_id"]: dict(x) for x in categories}
        categories.setdefault(
            ROOT_ID,
            {"category_id": ROOT_ID, "name": "标准紧固件", "source_url": START_URL},
        )
        # Only the supplied, verified category seed is used for sitemap slug candidates.
        seed_slugs = {}
        for cid, row in categories.items():
            source = row.get("source_url", "")
            if cid != ROOT_ID and cid.startswith(ROOT_ID + ".") and allowed_url(source):
                parts = urllib.parse.urlsplit(source).path.strip("/").split("/")
                if "c" in parts and parts.index("c") > 0:
                    seed_slugs.setdefault(parts[parts.index("c") - 1], set()).add(cid)
        seed_paths = category_paths(list(categories.values()))
        products = {}
        discovered = {}
        candidates = {}
        queue = deque()
        queued = set()
        active = None
        invalid_cache_urls = set()
        saved = self.read_json(self.cache / "category-checkpoint.json", {})
        if not isinstance(saved, dict):
            saved = {}
        self.resumed = bool(saved)
        for row in saved.get("categories", []):
            cid = row.get("category_id", "")
            if cid == ROOT_ID or cid.startswith(ROOT_ID + "."):
                categories.setdefault(cid, row)

        def restore_urls(value, target):
            if isinstance(value, dict):
                for url, ids in value.items():
                    if allowed_url(url) and product_id(url):
                        target.setdefault(canonical(url), set()).update(
                            x for x in ids if x in categories
                        )

        # Legacy discovery IDs came from arbitrary anchors, so restore them as candidates only.
        restore_urls(saved.get("product_urls", {}), self.link_candidates)
        restore_urls(
            self.read_json(self.cache / "discovered-products.json", {}),
            self.link_candidates,
        )
        restore_urls(saved.get("link_category_candidates", {}), self.link_candidates)
        for url in self.link_candidates:
            discovered.setdefault(url, set())
        restore_urls(saved.get("sitemap_product_candidates", {}), candidates)
        for url in candidates:
            discovered.setdefault(url, set())
        # Sitemap sources are URLs rather than category IDs.
        for url, sources in saved.get("sitemap_product_sources", {}).items():
            if allowed_url(url):
                self.sitemap_sources[url] = {x for x in sources if allowed_url(x)}
        for url, sources in saved.get("link_category_sources", {}).items():
            if allowed_url(url):
                self.link_sources[url] = {x for x in sources if allowed_url(x)}
        if not refresh:
            self.completed_categories = {
                canonical(x)
                for x in saved.get("completed_category_pages", [])
                if allowed_url(x)
            }
            self.sitemaps_done = {
                x for x in saved.get("completed_sitemaps", []) if allowed_url(x)
            }
            self.sitemap_pending = [
                x for x in saved.get("pending_sitemaps", []) if allowed_url(x)
            ]
            self.pagination_pending = list(saved.get("pagination_unverified", []))
        initial = [] if refresh else saved.get("pending_category_urls", [])
        # Older checkpoints had no page frontier. All seed pages are safe restart points.
        initial = (
            list(initial)
            + [categories[ROOT_ID]["source_url"]]
            + [c.get("source_url", "") for c in categories.values()]
        )
        for url in initial:
            if (
                allowed_url(url)
                and category_id(url)
                and canonical(url) not in self.completed_categories
                and canonical(url) not in queued
            ):
                queue.append(canonical(url))
                queued.add(canonical(url))

        def save():
            pending = list(queue)
            if (
                active
                and category_id(active)
                and active not in self.completed_categories
                and active not in pending
            ):
                pending.insert(0, active)
            self.write_json(
                self.cache / "category-checkpoint.json",
                {
                    "version": 2,
                    "saved_at": now(),
                    "categories": list(categories.values()),
                    "product_urls": {k: sorted(v) for k, v in discovered.items()},
                    "sitemap_product_candidates": {
                        k: sorted(v) for k, v in candidates.items()
                    },
                    "sitemap_product_sources": {
                        k: sorted(v) for k, v in self.sitemap_sources.items()
                    },
                    "link_category_candidates": {
                        k: sorted(v) for k, v in self.link_candidates.items()
                    },
                    "link_category_sources": {
                        k: sorted(v) for k, v in self.link_sources.items()
                    },
                    "completed_category_pages": sorted(self.completed_categories),
                    "pending_category_urls": pending,
                    "completed_sitemaps": sorted(self.sitemaps_done),
                    "pending_sitemaps": self.sitemap_pending,
                    "pagination_unverified": self.pagination_pending,
                },
            )
            self.write_json(
                self.cache / "discovered-products.json",
                {k: sorted(v) for k, v in discovered.items()},
            )

        def decorate(row):
            pid = row["source_product_id"]
            previous_ids = set(row.get("category_ids", []))
            possibilities = {}
            verified = row.get("category_status") in (
                "public_breadcrumb_verified",
                "public_product_list_verified",
            )
            ids = previous_ids if verified else set()
            ids.intersection_update(categories)
            for url, members in candidates.items():
                if product_id(url) != pid:
                    continue
                for cid in members - ids:
                    possibilities[cid] = {
                        "category_code": cid,
                        "category_path": [],
                        "category_source_url": categories.get(cid, {}).get(
                            "source_url", ""
                        ),
                        "evidence": "公开sitemap产品URL分类slug与已核实分类种子一致；不是面包屑确认，待审核。",
                        "sitemap_source_urls": sorted(
                            self.sitemap_sources.get(url, set())
                        ),
                    }
            for url, members in self.link_candidates.items():
                if product_id(url) != pid:
                    continue
                for cid in members - ids:
                    item = possibilities.setdefault(
                        cid,
                        {
                            "category_code": cid,
                            "category_path": [],
                            "category_source_url": categories.get(cid, {}).get(
                                "source_url", ""
                            ),
                            "evidence": "",
                        },
                    )
                    item[
                        "evidence"
                    ] += " 公开分类页存在该产品链接；未验证链接属于产品列表，可能为导航或推荐，待审核。"
                    item["category_page_source_urls"] = sorted(
                        self.link_sources.get(url, set())
                    )
            if not verified:
                for cid in previous_ids - ids:
                    possibilities.setdefault(
                        cid,
                        {
                            "category_code": cid,
                            "category_path": [],
                            "category_source_url": categories.get(cid, {}).get(
                                "source_url", ""
                            ),
                            "evidence": "旧缓存分类没有明确面包屑或产品列表区域验证，降为候选待审核。",
                        },
                    )
            for cid, item in possibilities.items():
                item["category_path"] = seed_paths.get(cid, [])
            row["category_ids"] = sorted(ids)
            old = {
                x.get("category_code"): x
                for x in row.get("category_candidates", [])
                if x.get("category_code") not in ids
            }
            old.update(possibilities)
            row["category_candidates"] = list(old.values())
            row["category_status"] = (
                row.get("category_status")
                if ids and verified
                else "needs_review_public_links"
            )
            row["review_status"] = "待审核"
            row["import_approved"] = False
            return row

        # Read verified cached product rows before any network work, so a blocked resume retains them.
        if not refresh:
            for url in sorted(discovered):
                pid = product_id(url)
                cached = self.cache_path(url)
                if (
                    pid in products
                    or not cached.is_file()
                    or (self.max_products and len(products) >= self.max_products)
                ):
                    continue
                try:
                    row = normalise_input(json.loads(cached.read_text("utf-8")))
                    if row.get("source_product_id") != pid or not row.get("name"):
                        raise ValueError("缓存BN编号/产品名不匹配")
                    products[pid] = decorate(row)
                    self.cached_products += 1
                except Exception as error:
                    invalid_cache_urls.add(url)
                    self.failure(url, error, "product_cache")
        save()
        missing_images = sum(self.needs_image(row) for row in products.values())
        print(
            f"恢复缓存：{len(products)} 个产品；待补主图：{missing_images} 张。",
            flush=True,
        )
        try:
            self.runtime_phase = "robots"
            print("检查站点访问规则……", flush=True)
            self.check_robots(START_URL)
            if not self.images_only:
                self.runtime_phase = "sitemap_discovery"
                self.discover_sitemaps(seed_slugs, discovered, candidates, save)
            save()
            needs_browser = (
                any(self.needs_image(p) for p in products.values())
                or (not self.images_only and bool(queue))
                or (
                    not self.images_only
                    and (
                        not (self.max_products and len(products) >= self.max_products)
                        and any(product_id(url) not in products for url in discovered)
                    )
                )
            )
            if needs_browser:
                self.runtime_phase = "browser_import"
                print("加载浏览器采集依赖……", flush=True)
                from playwright.sync_api import sync_playwright

                with sync_playwright() as p:
                    launch = {"headless": True}
                    executable = self.executable or next(
                        (
                            shutil.which(x)
                            for x in (
                                "chromium",
                                "chromium-browser",
                                "google-chrome",
                                "msedge",
                            )
                            if shutil.which(x)
                        ),
                        None,
                    )
                    if executable:
                        launch["executable_path"] = executable
                    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get(
                        "https_proxy"
                    )
                    if proxy:
                        launch["proxy"] = {"server": proxy}
                    self.runtime_phase = "browser_launch"
                    print("启动采集浏览器……", flush=True)
                    browser = p.chromium.launch(**launch)
                    context = None
                    try:
                        self.runtime_phase = "browser_context"
                        context = browser.new_context(
                            user_agent=USER_AGENT, locale="zh-CN"
                        )
                        page = context.new_page()

                        def before_navigation(route):
                            request = route.request
                            if request.is_navigation_request():
                                try:
                                    self.check_robots(request.url)
                                except CrawlBlocked as error:
                                    self.browser_block = str(error)
                                    route.abort()
                                    return
                            route.continue_()

                        def response_seen(response):
                            if allowed_url(response.url) and response.status in (
                                401,
                                403,
                                429,
                            ):
                                self.browser_block = (
                                    "公开页面请求返回HTTP "
                                    + str(response.status)
                                    + "，停止采集："
                                    + response.url
                                )

                        context.route("**/*", before_navigation)
                        page.on("response", response_seen)
                        while (
                            not self.images_only
                            and queue
                            and self.category_views < self.max_category_pages
                        ):
                            self.runtime_phase = "category_collection"
                            url = queue.popleft()
                            queued.discard(url)
                            if url in self.completed_categories:
                                continue
                            active = url
                            completed = False
                            try:
                                completed = self.crawl_category(
                                    page,
                                    url,
                                    categories,
                                    discovered,
                                    queue,
                                    queued,
                                    save,
                                )
                            except CrawlBlocked:
                                raise
                            except Exception as error:
                                self.failure(url, error, "category")
                                self.pagination_issue(
                                    url, url, "分类页读取失败，发现范围待确认"
                                )
                            finally:
                                if not completed and url not in queued:
                                    queue.append(url)
                                    queued.add(url)
                                save()
                            active = None
                            # Unchanged controls must not cause repeated retries within this run.
                            if not completed:
                                break
                        active = None
                        self.runtime_phase = "cached_image_collection"
                        for item in list(products.values()):
                            if self.needs_image(item):
                                active = item["source_url"]
                                print("补采主图", item["source_product_id"], flush=True)
                                self.collect_image(page, item)
                                save()
                        active = None
                        self.runtime_phase = "product_collection"
                        for url, ids in sorted(discovered.items()):
                            if self.images_only:
                                break
                            pid = product_id(url)
                            if pid in products:
                                continue
                            if self.max_products and len(products) >= self.max_products:
                                break
                            active = url
                            self.visited_products.add(url)
                            try:
                                cached = self.cache_path(url)
                                if (
                                    cached.is_file()
                                    and url not in invalid_cache_urls
                                    and not refresh
                                ):
                                    row = normalise_input(
                                        json.loads(cached.read_text("utf-8"))
                                    )
                                    if row.get(
                                        "source_product_id"
                                    ) != pid or not row.get("name"):
                                        raise ValueError("缓存BN编号/产品名不匹配")
                                    self.cached_products += 1
                                else:
                                    print(
                                        "产品",
                                        len(products) + 1,
                                        "/",
                                        len({product_id(x) for x in discovered}),
                                        url,
                                        flush=True,
                                    )
                                    self.navigate(page, url)
                                    page.wait_for_timeout(700)
                                    self.guard_page(page)
                                    row = parse_product(
                                        page.content(), url, sorted(ids)
                                    )
                                    if not row.get("raw_attributes"):
                                        self.failure(
                                            url,
                                            "产品BN和名称已确认，但未解析到公开属性表；字段获取范围待确认",
                                            "product_attributes",
                                        )
                                row = decorate(row)
                                self.write_json(cached, row)
                                products[pid] = row
                                if self.download_images:
                                    self.collect_image(page, row)
                            except CrawlBlocked:
                                raise
                            except Exception as error:
                                self.failure(url, error, "product_parse")
                            finally:
                                save()
                    finally:
                        if context:
                            context.close()
                        browser.close()
        except CrawlBlocked as error:
            self.access_blocked = True
            self.failure(active or START_URL, error, "access_blocked")
            print(str(error), file=sys.stderr)
        except Exception as error:
            # 缓存能导出，不等于联网采集启动成功；启动异常必须返回失败。
            self.runtime_error = f"{type(error).__name__}: {error}"[:4000]
            self.failure(active or START_URL, error, "crawler")
            print(
                f"采集失败 [{self.runtime_phase}]：{self.runtime_error}\n"
                "已保留已有缓存，将导出报告供排查，本轮采集未正常完成。",
                file=sys.stderr,
                flush=True,
            )
            if isinstance(error, ImportError) and (
                getattr(error, "name", "") or ""
            ).startswith("playwright"):
                print_install_help()
            elif (
                self.runtime_phase == "browser_launch"
                and "Executable doesn't exist" in str(error)
            ):
                print_install_help()
        finally:
            save()
        # A seed is normally complete; exclude any orphan chain found in malformed public markup.
        valid_ids = set(categories)
        while True:
            next_ids = {
                cid
                for cid in valid_ids
                if cid == ROOT_ID
                or (
                    categories[cid].get("parent_id")
                    or categories[cid].get("parent_category_id")
                )
                in valid_ids
            }
            if next_ids == valid_ids:
                break
            valid_ids = next_ids
        if len(valid_ids) != len(categories):
            self.failure(
                START_URL,
                "部分发现分类缺少完整父级链，未导出这些分类",
                "category_structure",
            )
        valid_categories = [c for cid, c in categories.items() if cid in valid_ids]
        # Reapply listing evidence discovered after an early cache load.
        for pid, row in products.items():
            products[pid] = row = decorate(row)
            row["category_ids"] = [
                x for x in row.get("category_ids", []) if x in valid_ids
            ]
        discovered_bn = {product_id(x) for x in discovered}
        pending_bn = sorted(discovered_bn - set(products))
        remaining_categories = list(
            dict.fromkeys(x for x in queue if x not in self.completed_categories)
        )
        pending_images = [
            p["source_product_id"]
            for p in products.values()
            if local_image(self.cache, p) is None
        ]
        if self.access_blocked:
            status = "访问受限或站点禁止"
        elif self.runtime_error:
            status = "失败（采集启动或执行异常；已保留缓存）"
        elif not discovered_bn:
            status = "失败（未发现任何BN产品系列）"
        elif not products:
            status = "失败（已发现产品均未解析成功）"
        elif (
            self.failures
            or remaining_categories
            or pending_bn
            or self.pagination_pending
            or self.sitemap_pending
            or (self.download_images and pending_images)
        ):
            status = "部分采集（检查失败、待处理及分页项）"
        else:
            status = "已处理本次已发现BN公开页面；目录完整性仍需审核"
        report = {
            "toolkit_version": TOOLKIT_VERSION,
            "status": status,
            "complete_catalog": False,
            "start_url": START_URL,
            "resumed_checkpoint": self.resumed,
            "robots_status": self.robots_status,
            "visited_category_pages": len(self.visited_categories),
            "category_page_views_this_run": self.category_views,
            "category_page_limit": self.max_category_pages,
            "load_more_clicks": self.load_more_clicks,
            "discovered_product_urls": len(discovered),
            "discovered_unique_bn_count": len(discovered_bn),
            "exported_product_series": len(products),
            "cached_product_series_used": self.cached_products,
            "pending_product_ids": pending_bn,
            "remaining_category_urls": remaining_categories,
            "pagination_unverified": self.pagination_pending,
            "failed_or_unverified": self.failures,
            "runtime_error": self.runtime_error,
            "runtime_phase": self.runtime_phase,
            "sitemap_requests_this_run": self.sitemap_requests,
            "sitemap_page_limit": self.max_sitemap_pages,
            "sitemap_results": self.sitemap_results,
            "pending_sitemaps": self.sitemap_pending,
            "sitemap_candidate_product_count": len({product_id(x) for x in candidates}),
            "category_url_candidate_product_count": len(
                {product_id(x) for x in self.link_candidates}
            ),
            "download_images": self.download_images,
            "images_only": self.images_only,
            "downloaded_image_count": len(products) - len(pending_images),
            "new_image_count": self.new_image_count,
            "image_status_counts": dict(
                Counter(p.get("image_status", "pending") for p in products.values())
            ),
            "pending_image_ids": pending_images,
            "record_scope": "series",
            "completed_at": now(),
        }
        self.write_json(self.cache / "crawl-report.json", report)
        return valid_categories, list(products.values()), report


def main():
    """命令行接口：校验参数 → 采集或读JSON → 导出Excel → 返回退出码。

    0=正常返回（仍需检查是否部分采集），1=采集失败，2=访问受限或参数错误。
    默认拒绝覆盖审核表；命令示例和全部参数见配套指南。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--categories",
        type=Path,
        required=True,
        help="公开分类种子JSON（categories数组）",
    )
    parser.add_argument("--products", type=Path, help="导出已有采集JSON，不联网")
    parser.add_argument("--output", type=Path, required=True, help="审核Excel输出路径")
    parser.add_argument(
        "--crawl",
        action="store_true",
        help="遍历可发现的公开分类与BN系列；遵守robots，遇403或验证停止",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("work/bossard-cache"),
        help="断点、产品JSON、images/保存目录；续采必须沿用此目录",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="请求间隔秒数，最低1；robots要求更慢时服从站点规则",
    )
    parser.add_argument(
        "--max-products", type=int, default=0, help="0=不主动限制BN数量"
    )
    parser.add_argument(
        "--max-category-pages",
        type=int,
        default=1000,
        help="本次分类页面/可见Next翻页上限；达到后报告待确认",
    )
    parser.add_argument(
        "--max-sitemap-pages", type=int, default=200, help="本次公开同域sitemap读取上限"
    )
    parser.add_argument(
        "--browser-executable", help="可选Chrome/Chromium可执行文件路径"
    )
    parser.add_argument(
        "--skip-images", action="store_true", help="仅采集技术属性，不下载主图"
    )
    parser.add_argument(
        "--images-only",
        action="store_true",
        help="只给缓存中已有BN补采主图，不继续采集剩余产品详情",
    )
    parser.add_argument(
        "--image-root", type=Path, help="离线导出时包含 images 子目录的缓存根目录"
    )
    parser.add_argument(
        "--no-embed-images",
        action="store_true",
        help="不在Excel中嵌入缩略图，只保存图片路径和来源",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="重新发现分类/sitemap并读取已缓存产品公开页",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允许覆盖指定输出文件；请不要覆盖已人工审核的工作簿",
    )
    args = parser.parse_args()
    if args.refresh and args.images_only:
        parser.error("--images-only 不能与 --refresh 同用")
    if args.images_only and (not args.crawl or args.skip_images):
        parser.error("--images-only 需要 --crawl，且不能与 --skip-images 同用")
    if args.output.exists() and not args.overwrite:
        parser.error("输出文件已存在；请使用新文件名，或显式指定 --overwrite")
    source = json.loads(args.categories.read_text("utf-8"))
    categories = (
        source.get("categories", source) if isinstance(source, dict) else source
    )
    products = []
    report = {"status": "公开页面审核样本；不是完整实时采集", "complete_catalog": False}
    if args.products:
        content = json.loads(args.products.read_text("utf-8"))
        products = (
            content.get("products", content) if isinstance(content, dict) else content
        )
        if isinstance(content, dict):
            if "categories" in content:
                categories = content["categories"]
            report.update(content.get("report", {}))
            report.update(
                {
                    k: v
                    for k, v in content.items()
                    if k not in ("products", "categories", "report", "field_notes")
                }
            )
    if args.crawl:
        crawler = PublicCrawler(
            args.cache,
            args.delay,
            args.max_products,
            args.max_category_pages,
            executable=args.browser_executable,
            max_sitemap_pages=args.max_sitemap_pages,
            download_images=not args.skip_images,
            images_only=args.images_only,
        )
        categories, products, report = crawler.crawl(categories, args.refresh)
        (args.cache / "export-data.json").write_text(
            json.dumps(
                {"categories": categories, "products": products, "report": report},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    image_root = args.cache if args.crawl else args.image_root
    result = export_workbook(
        categories,
        products,
        args.output,
        report,
        image_root=image_root,
        embed_images=not args.no_embed_images,
    )
    print(json.dumps(result, ensure_ascii=False))
    if args.crawl:
        print("采集状态：" + report.get("status", "未知"), flush=True)
        print(
            f"图片：本次新下载 {report.get('new_image_count', 0)} 张，"
            f"本地已有 {report.get('downloaded_image_count', 0)} 张，"
            f"仍待补采 {len(report.get('pending_image_ids', []))} 张；"
            f"本份 Excel 嵌图 {result['embedded_images']} 张。",
            flush=True,
        )
        print("详细报告：" + str(args.cache / "crawl-report.json"), flush=True)
    if args.crawl and report.get("status", "").startswith("访问受限"):
        return 2
    if args.crawl and report.get("status", "").startswith("失败"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
