"""启动失败不能被缓存导出伪装成成功；覆盖缺依赖和浏览器启动异常。"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch

from openpyxl import load_workbook
from bossard_catalog import PublicCrawler, START_URL, main, parse_product

URL = "https://www.bossard.com.cn/cn-zh-cn/eshop/example/p/2/"
CATEGORIES = [{"category_id": "01.100", "name": "标准紧固件", "source_url": START_URL}]


def seed_cache(folder):
    crawler = PublicCrawler(folder, images_only=True)
    row = parse_product("<h1>螺钉</h1><p>BN 2</p>", URL)
    crawler.write_json(crawler.cache_path(URL), row)
    crawler.write_json(
        crawler.cache / "category-checkpoint.json",
        {
            "categories": CATEGORIES,
            "product_urls": {URL: []},
            "pending_category_urls": [START_URL],
        },
    )
    crawler.check_robots = Mock()
    return crawler


class RuntimeFailureTests(unittest.TestCase):
    def test_missing_playwright_keeps_cache_but_reports_failure_and_install_command(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            crawler = seed_cache(temp)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err), patch.dict(
                sys.modules, {"playwright.sync_api": None}
            ):
                _, products, report = crawler.crawl(CATEGORIES)
            self.assertEqual(len(products), 1)
            self.assertTrue(report["status"].startswith("失败"))
            self.assertEqual(report["runtime_phase"], "browser_import")
            self.assertIn("ModuleNotFoundError", report["runtime_error"])
            self.assertEqual(report["new_image_count"], 0)
            self.assertEqual(report["pending_image_ids"], ["BN2"])
            self.assertIn("pip install -r", err.getvalue())
            self.assertIn("playwright install chromium", err.getvalue())
            self.assertIn("恢复缓存：1", out.getvalue())
            self.assertTrue(crawler.cache_path(URL).is_file())
            saved = json.loads((Path(temp) / "crawl-report.json").read_text())
            self.assertEqual(saved["runtime_phase"], "browser_import")

    def test_browser_launch_failure_is_fatal_and_preserves_frontier(self):
        with tempfile.TemporaryDirectory() as temp:
            crawler = seed_cache(temp)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err), patch(
                "playwright.sync_api.sync_playwright"
            ) as playwright:
                playwright.return_value.__enter__.return_value.chromium.launch.side_effect = RuntimeError(
                    "browser did not start"
                )
                _, products, report = crawler.crawl(CATEGORIES)
            self.assertTrue(report["status"].startswith("失败"))
            self.assertEqual(report["runtime_phase"], "browser_launch")
            self.assertIn("browser did not start", err.getvalue())
            self.assertEqual(len(products), 1)
            checkpoint = json.loads(
                (Path(temp) / "category-checkpoint.json").read_text()
            )
            self.assertIn(START_URL, checkpoint["pending_category_urls"])
            self.assertNotIn(URL, checkpoint["pending_category_urls"])

    def test_cli_returns_one_even_when_cached_workbook_was_exported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seed_cache(root / "cache")
            categories = root / "categories.json"
            categories.write_text(
                json.dumps({"categories": CATEGORIES}), encoding="utf-8"
            )
            output = root / "review.xlsx"
            argv = [
                "bossard_catalog.py",
                "--categories",
                str(categories),
                "--output",
                str(output),
                "--crawl",
                "--images-only",
                "--cache",
                str(root / "cache"),
            ]
            out, err = io.StringIO(), io.StringIO()
            with patch.object(sys, "argv", argv), patch.object(
                PublicCrawler, "check_robots"
            ), patch.dict(sys.modules, {"playwright.sync_api": None}), redirect_stdout(
                out
            ), redirect_stderr(
                err
            ):
                code = main()
            self.assertEqual(code, 1)
            self.assertTrue(output.is_file())
            book = load_workbook(output)
            self.assertEqual(book["产品审核"].cell(2, 3).value, "BN2")
            book.close()
            self.assertIn("本次新下载 0 张", out.getvalue())
            self.assertIn("仍待补采 1 张", out.getvalue())
            self.assertIn("采集状态：失败", out.getvalue())


if __name__ == "__main__":
    unittest.main()
