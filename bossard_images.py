"""Bossard 主产品照片的定位、保存和 Excel 缩略图接口。

本模块不发现产品链接，也不发起 HTTP 请求；只处理采集器交给它的 HTML、
图片字节和本地路径。调用顺序：选图 → 下载 → 保存 → 嵌入审核 Excel。
完整参数和数据结构见 BOSSARD_COLLECTOR_GUIDE.md。
"""

from __future__ import annotations

import hashlib
import io
import re
import urllib.parse
from pathlib import Path
from typing import Any

# 同时限制实际响应字节和解码后的像素，不依赖可能缺失的 Content-Length。
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


def allowed_image_url(url: str) -> bool:
    """只接受 Bossard 中国站 HTTPS 媒体路径；初始请求和重定向都要检查。"""
    try:
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "www.bossard.com.cn"
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
            and parsed.path.startswith(("/eshopmedia/", "/medias/"))
        )
    except (ValueError, TypeError):
        return False


def image_url(value: str | None, page_url: str) -> str:
    """将相对图片地址转绝对地址，拒绝范围外地址；失败返回空字符串。

    图片地址里的 &w=760、&h=570 可能属于路径。不能套用产品页的
    canonical()，也不自己拼接高清尺寸；保留网页实际提供的地址。
    """
    try:
        result = urllib.parse.urljoin(page_url, (value or "").strip())
        parsed = urllib.parse.urlsplit(result)
        result = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
        )
    except (ValueError, TypeError):
        return ""
    return result if allowed_image_url(result) else ""


def is_drawing(element: Any, url: str) -> bool:
    """根据 alt 文本和源站文件名排除技术图、标志及占位图。"""
    label = (element.get("alt", "") + " " + urllib.parse.unquote(url)).casefold()
    return bool(
        re.search(
            r"技术图|工程图|尺寸图|technical|drawing|(?:_|/)zv_|logo|placeholder", label
        )
    )


def select_product_image(doc: Any, page_url: str) -> dict[str, str]:
    """从 lxml HTML 文档定位一张主产品照片，不联网。

    返回 image_url、image_evidence、image_status、image_note 四个字段。
    优先精确标记 product-gallery-image；主图缺失时才检查同画廊明确标为
    “产品图片”的缩略图。srcset 中选择网页实际提供的最大版本。
    不扫描任意 img，不从推荐商品、og:image 或工程图凑一张图片。
    """
    primary = doc.xpath('//img[@data-testid="product-gallery-image"]')
    thumbnails = doc.xpath('//img[@data-testid="product-gallery-image-thumbnail"]')
    groups = (
        (primary, "产品详情主画廊 product-gallery-image", False),
        (thumbnails, "产品详情画廊照片缩略图，非技术图", True),
    )
    for elements, evidence, thumbnail_only in groups:
        for element in elements:
            options = []
            for attribute in ("srcset", "data-srcset"):
                for entry in (element.get(attribute) or "").split(","):
                    parts = entry.strip().rsplit(None, 1)
                    if len(parts) == 2 and re.fullmatch(r"\d+(?:\.\d+)?[wx]", parts[1]):
                        url = image_url(parts[0], page_url)
                        if url and not is_drawing(element, url):
                            options.append((float(parts[1][:-1]), url))
            for attribute in ("data-src", "src"):
                url = image_url(element.get(attribute), page_url)
                if url and not is_drawing(element, url):
                    options.append((0, url))
            if thumbnail_only:
                options = [
                    pair
                    for pair in options
                    if re.search(
                        r"产品图片|product image|_ph_",
                        element.get("alt", "") + " " + urllib.parse.unquote(pair[1]),
                        re.I,
                    )
                ]
            if options:
                return {
                    "image_url": max(options, key=lambda pair: pair[0])[1],
                    "image_evidence": evidence,
                    "image_status": "pending",
                    "image_note": "",
                }
    return {
        "image_url": "",
        "image_evidence": "",
        "image_status": "not_found",
        "image_note": "未找到可确认的产品画廊照片；未使用标志、推荐商品或技术图代替",
    }


def save_product_image(cache: str | Path, row: dict, content: bytes) -> None:
    """校验图片并保存；成功后原地更新 row 的路径、尺寸、SHA-256 和状态。

    输入：缓存根目录、至少含 source_product_id=BN数字 的记录、响应字节。
    输出：cache/images/BN2.source.webp 等原始字节文件和 BN2.png 查看副本。
    扩展名来自 Pillow 检测的真实格式，不能直接相信 URL 或 Content-Type。
    无效内容抛出异常；校验失败不会覆盖已有图片。GIF/TIFF 的 PNG 取首帧。
    """
    from PIL import Image

    cache = Path(cache)
    pid = row.get("source_product_id", "")
    if not re.fullmatch(r"BN\d+", pid):
        raise ValueError("无效BN编号，不能保存图片")
    if not 0 < len(content) <= MAX_IMAGE_BYTES:
        raise ValueError("图片为空或超过15 MiB")
    with Image.open(io.BytesIO(content)) as source:
        if source.width * source.height > MAX_IMAGE_PIXELS:
            raise ValueError("图片超过2000万像素")
        if source.format not in ("JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"):
            raise ValueError("不支持的图片格式")
        fmt = source.format
        source.verify()
    with Image.open(io.BytesIO(content)) as source:
        source.seek(0)
        normalized = source.convert("RGBA" if "A" in source.getbands() else "RGB")
        width, height = normalized.size
    suffix = {
        "JPEG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
        "GIF": ".gif",
        "BMP": ".bmp",
        "TIFF": ".tiff",
    }[fmt]
    folder = cache / "images"
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / (pid + ".source" + suffix)
    preview = folder / (pid + ".png")
    original_temp = original.with_name(original.name + ".tmp")
    preview_temp = preview.with_name(preview.name + ".tmp")
    try:
        original_temp.write_bytes(content)
        normalized.save(preview_temp, format="PNG")
        original_temp.replace(original)
        preview_temp.replace(preview)
    finally:
        original_temp.unlink(missing_ok=True)
        preview_temp.unlink(missing_ok=True)
    row.update(
        image_path=preview.relative_to(cache).as_posix(),
        image_original_path=original.relative_to(cache).as_posix(),
        image_sha256=hashlib.sha256(content).hexdigest(),
        image_width=width,
        image_height=height,
        image_status="downloaded",
        image_note="",
    )


def local_image(root: str | Path | None, row: dict) -> Path | None:
    """将 image_path 解析为缓存内的现有文件；缺失或越界返回 None。"""
    if root is None or not row.get("image_path"):
        return None
    base = Path(root).resolve()
    path = (base / row["image_path"]).resolve()
    return path if path.is_relative_to(base) and path.is_file() else None


def add_workbook_images(
    sheet: Any,
    products: list[dict],
    image_column: int,
    image_root: str | Path | None,
    embed: bool = True,
) -> int:
    """按产品行顺序插入最大140×105像素缩略图，返回实际嵌图数量。

    image_column 从1开始；products 必须与工作表排序一致。embed=False 时只写
    路径；缺图写原因。Excel 用浮动图片显示，原图仍保存在 cache/images 中。
    """
    from PIL import Image
    from openpyxl.drawing.image import Image as ExcelImage

    embedded = 0
    for number, row in enumerate(products, 2):
        cell = sheet.cell(number, image_column)
        path = local_image(image_root, row)
        if path is None:
            cell.value = (
                "未下载：请本地运行 --crawl --images-only 补采主图"
                if row.get("image_status") not in ("not_found", "failed", "blocked")
                else row.get("image_note") or row["image_status"]
            )
            continue
        if not embed:
            cell.value = "已保存：" + row["image_path"]
            continue
        try:
            with Image.open(path) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("图片尺寸过大")
                # 源站主图常有透明背景；Excel 缩略图铺白，避免透明区域变黑。
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                thumb = Image.alpha_composite(background, rgba).convert("RGB")
                thumb.thumbnail((140, 105))
                data = io.BytesIO()
                thumb.save(data, format="PNG")
                data.seek(0)
            picture = ExcelImage(data)
            sheet.add_image(picture, cell.coordinate)
            sheet.row_dimensions[number].height = 86
            cell.value = ""
            embedded += 1
        except Exception as error:
            cell.value = "缩略图生成失败：" + str(error)[:150]
    return embedded
