"""主图选择、缓存恢复、下载失败和含图片 Excel 的离线回归；不访问网站。"""

import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from lxml import html
from openpyxl import load_workbook
from PIL import Image

from bossard_catalog import (
    PublicCrawler,
    CrawlBlocked,
    START_URL,
    export_workbook,
    parse_product,
)
from bossard_images import (
    allowed_image_url,
    select_product_image,
    save_product_image,
    local_image,
)

PRODUCT_URL = "https://www.bossard.com.cn/cn-zh-cn/eshop/bolts/example/p/2/"
PHOTO = "https://www.bossard.com.cn/eshopmedia/00002_ph_05_ne&w=760&h=570"
CATEGORIES = [{"category_id": "01.100", "name": "标准紧固件", "source_url": START_URL}]


def photo_bytes(color="navy"):
    stream = io.BytesIO()
    Image.new("RGB", (160, 120), color).save(stream, "WEBP")
    return stream.getvalue()


def product():
    return parse_product("<h1>内六角圆柱头螺钉</h1><p>BN 2</p>", PRODUCT_URL)


class GallerySelectionTests(unittest.TestCase):
    def test_main_photo_wins_over_technical_thumbnail_and_recommendation(self):
        doc = html.fromstring(
            """<main>
        <img src="/eshopmedia/logo.png">
        <img data-testid="product-gallery-image-thumbnail" alt="带尺寸的技术图" src="/eshopmedia/00002_zv_01.png">
        <img data-testid="product-gallery-image" alt="产品图片：螺钉"
          src="/eshopmedia/00002_ph_05_ne&amp;w=455&amp;h=341"
          srcset="/eshopmedia/00002_ph_05_ne&amp;w=296&amp;h=222 296w, /eshopmedia/00002_ph_05_ne&amp;w=760&amp;h=570 760w">
        <aside><img src="/eshopmedia/BN4_ph_recommend.png" width="2000"></aside></main>"""
        )
        row = select_product_image(doc, PRODUCT_URL)
        self.assertEqual(row["image_url"], PHOTO)
        self.assertEqual(row["image_status"], "pending")

    def test_only_confirmed_gallery_photograph_is_a_fallback(self):
        doc = html.fromstring("""<main>
        <img data-testid="product-gallery-image" alt="技术图" src="/eshopmedia/00002_zv_01.png">
        <img data-testid="product-gallery-image-thumbnail" alt="产品图片：螺钉" data-src="/eshopmedia/shared_ph_01.webp">
        </main>""")
        result = select_product_image(doc, PRODUCT_URL)
        self.assertIn("shared_ph_01", result["image_url"])
        self.assertIn("缩略图", result["image_evidence"])

    def test_logo_recommendations_and_drawing_do_not_fill_missing_photo(self):
        for markup in (
            '<img src="/eshopmedia/2_ph_recommend.png">',
            '<img data-testid="product-gallery-image-thumbnail" alt="图示" src="/eshopmedia/2_zv_01.png">',
            '<img data-testid="product-gallery-image" alt="logo" src="/eshopmedia/logo.png">',
            '<img data-testid="product-gallery-image" src="https://example.com/photo.jpg">',
        ):
            with self.subTest(markup=markup):
                result = select_product_image(html.fromstring(markup), PRODUCT_URL)
                self.assertEqual(result["image_status"], "not_found")
                self.assertFalse(result["image_url"])

    def test_media_url_scope_and_actual_query_are_preserved(self):
        url = PHOTO + "?format=webp&quality=75"
        doc = html.fromstring(
            '<img data-testid="product-gallery-image" src="' + url + '">'
        )
        self.assertEqual(select_product_image(doc, PRODUCT_URL)["image_url"], url)
        for unsafe in (
            "http://www.bossard.com.cn/eshopmedia/a.png",
            "https://example.com/eshopmedia/a.png",
            "https://www.bossard.com.cn:444/eshopmedia/a.png",
            "https://a@www.bossard.com.cn/eshopmedia/a.png",
            "https://www.bossard.com.cn/account/a.png",
            "https://www.bossard.com.cn:bad/eshopmedia/a.png",
        ):
            with self.subTest(url=unsafe):
                self.assertFalse(allowed_image_url(unsafe))


class ImageStorageTests(unittest.TestCase):
    def test_original_bytes_png_and_checksum_survive_copying_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "cache"
            row = product()
            content = photo_bytes()
            save_product_image(cache, row, content)
            self.assertEqual(row["image_status"], "downloaded")
            self.assertEqual((cache / row["image_original_path"]).read_bytes(), content)
            self.assertEqual(row["image_sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(row["image_width"], 160)
            self.assertEqual(row["image_path"], "images/BN2.png")
            with Image.open(local_image(cache, row)) as image:
                self.assertEqual(image.format, "PNG")
            self.assertFalse(list(cache.rglob("*.tmp")))

    def test_invalid_content_does_not_replace_a_good_photo(self):
        with tempfile.TemporaryDirectory() as temp:
            row = product()
            save_product_image(temp, row, photo_bytes())
            before = local_image(temp, row).read_bytes()
            with self.assertRaises(Exception):
                save_product_image(temp, row, b"<html>access denied</html>")
            self.assertEqual(local_image(temp, row).read_bytes(), before)
            for field, value in (("source_product_id", "../escape"),):
                with self.assertRaises(ValueError):
                    save_product_image(temp, {field: value}, photo_bytes())

    def test_pixel_limit_and_path_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("bossard_images.MAX_IMAGE_PIXELS", 100), self.assertRaises(
                ValueError
            ):
                save_product_image(temp, product(), photo_bytes())
            outside = Path(temp) / "outside.png"
            outside.write_bytes(photo_bytes())
            root = Path(temp) / "cache"
            root.mkdir()
            self.assertIsNone(local_image(root, {"image_path": "../outside.png"}))
            self.assertIsNone(local_image(root, {"image_path": str(outside)}))

    def test_saved_status_without_file_is_downloaded_again(self):
        with tempfile.TemporaryDirectory() as temp:
            row = product()
            save_product_image(temp, row, photo_bytes())
            crawler = PublicCrawler(temp)
            self.assertFalse(crawler.needs_image(row))
            local_image(temp, row).unlink()
            self.assertTrue(crawler.needs_image(row))
            self.assertFalse(
                PublicCrawler(temp, download_images=False).needs_image(row)
            )


class DownloadTests(unittest.TestCase):
    def crawler(self, temp):
        crawler = PublicCrawler(temp)
        crawler.check_robots = Mock()
        crawler.throttle = Mock()
        return crawler

    def test_403_stops_and_keeps_metadata_in_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            crawler = self.crawler(temp)
            row = {**product(), "image_url": PHOTO, "material": "钢"}
            error = urllib.error.HTTPError(PHOTO, 403, "Forbidden", {}, None)
            with patch("urllib.request.build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(CrawlBlocked):
                    crawler.collect_image(None, row)
            saved = json.loads(crawler.cache_path(PRODUCT_URL).read_text())
            self.assertEqual(saved["material"], "钢")
            self.assertEqual(saved["image_status"], "blocked")
            self.assertFalse(local_image(temp, saved))

    def test_bad_image_is_failed_and_no_external_redirect_is_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            crawler = self.crawler(temp)
            row = {**product(), "image_url": PHOTO}
            with patch("urllib.request.build_opener") as opener:
                response = opener.return_value.open.return_value.__enter__.return_value
                response.geturl.return_value = PHOTO
                response.read.return_value = b"<html>not an image</html>"
                crawler.collect_image(None, row)
                handler = opener.call_args.args[0]
                with self.assertRaises(ValueError):
                    handler.redirect_request(
                        Mock(), None, 302, "", {}, "https://example.com/private.png"
                    )
            self.assertEqual(row["image_status"], "failed")
            self.assertTrue(crawler.failures)

    def test_old_cache_rechecks_matching_bn_before_saving_picture(self):
        with tempfile.TemporaryDirectory() as temp:
            crawler = self.crawler(temp)
            crawler.navigate = Mock()
            crawler.guard_page = Mock()
            page = Mock()
            page.content.return_value = '<h1>其他产品</h1>BN 999<img data-testid="product-gallery-image" src="/eshopmedia/999_ph_a.webp">'
            row = product()
            with patch("urllib.request.build_opener") as opener:
                crawler.collect_image(page, row)
                opener.assert_not_called()
            self.assertEqual(row["image_status"], "failed")
            self.assertIn("BN", row["image_note"])

    def test_images_only_preserves_category_frontier_and_does_not_discover(self):
        with tempfile.TemporaryDirectory() as temp:
            crawler = self.crawler(temp)
            crawler.images_only = True
            row = {**product(), "image_url": PHOTO}
            crawler.write_json(crawler.cache_path(PRODUCT_URL), row)
            crawler.write_json(
                crawler.cache / "category-checkpoint.json",
                {
                    "categories": CATEGORIES,
                    "product_urls": {PRODUCT_URL: []},
                    "pending_category_urls": [START_URL],
                },
            )
            crawler.discover_sitemaps = Mock()
            crawler.crawl_category = Mock()

            def collect(page, value):
                save_product_image(temp, value, photo_bytes())
                crawler.write_json(crawler.cache_path(PRODUCT_URL), value)

            crawler.collect_image = Mock(side_effect=collect)
            with patch("playwright.sync_api.sync_playwright"):
                _, products, report = crawler.crawl(CATEGORIES)
            crawler.discover_sitemaps.assert_not_called()
            crawler.crawl_category.assert_not_called()
            self.assertEqual(len(products), 1)
            self.assertEqual(report["downloaded_image_count"], 1)
            checkpoint = json.loads(
                (Path(temp) / "category-checkpoint.json").read_text()
            )
            self.assertIn(START_URL, checkpoint["pending_category_urls"])
            self.assertNotIn(PRODUCT_URL, checkpoint["pending_category_urls"])


class ImageWorkbookTests(unittest.TestCase):
    def test_embedded_images_follow_sorted_bn_and_importer_ignores_auxiliary_columns(
        self,
    ):
        from catalog_import import _xlsx

        with tempfile.TemporaryDirectory() as temp:
            row = product()
            save_product_image(temp, row, photo_bytes())
            rows = [{**product(), "source_product_id": "BN10", "name": "其他产品"}, row]
            output = Path(temp) / "review.xlsx"
            result = export_workbook(CATEGORIES, rows, output, image_root=temp)
            self.assertEqual(result["embedded_images"], 1)
            book = load_workbook(output)
            sheet = book["产品审核"]
            headers = [cell.value for cell in sheet[1]]
            self.assertEqual(sheet.cell(2, 3).value, "BN2")
            self.assertEqual(len(sheet._images), 1)
            self.assertEqual(sheet._images[0].anchor._from.row, 1)
            self.assertEqual(
                sheet._images[0].anchor._from.col, headers.index("产品图片")
            )
            self.assertIn("未找到", sheet.cell(3, headers.index("产品图片") + 1).value)
            self.assertEqual(sheet.cell(2, 1).value, "待审核")
            parsed = _xlsx(output.read_bytes(), "review.xlsx")
            self.assertEqual(len(parsed["products"]), 2)
            self.assertNotIn("image_path", parsed["products"][0]["values"])
            self.assertEqual(
                parsed["products"][0]["values"]["source_product_id"], "BN2"
            )
            book.close()

    def test_no_embed_mode_keeps_local_file_path(self):
        with tempfile.TemporaryDirectory() as temp:
            row = product()
            save_product_image(temp, row, photo_bytes())
            output = Path(temp) / "paths.xlsx"
            result = export_workbook(
                CATEGORIES, [row], output, image_root=temp, embed_images=False
            )
            self.assertEqual(result["embedded_images"], 0)
            book = load_workbook(output)
            sheet = book["产品审核"]
            headers = [cell.value for cell in sheet[1]]
            self.assertIn(
                "images/BN2.png", sheet.cell(2, headers.index("产品图片") + 1).value
            )
            self.assertFalse(sheet._images)
            book.close()


if __name__ == "__main__":
    unittest.main()
