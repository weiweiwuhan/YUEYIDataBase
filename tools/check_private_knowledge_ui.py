"""Optional real-browser smoke check; all records/files live in a temporary DB.

Requires Playwright and Chromium, plus requirements-dev.txt for the PPT fixture.
Run: python tools/check_private_knowledge_ui.py --screenshots /tmp/private-ui
"""

import argparse
import io
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect
from pptx import Presentation
from test_assistant_http import PASSWORD
from test_private_knowledge_http import PrivateKnowledgeHTTPTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument(
        "--chromium",
        default=shutil.which("chromium") or shutil.which("chromium-browser"),
    )
    args = parser.parse_args()
    case = PrivateKnowledgeHTTPTests(
        "test_every_private_route_requires_live_administrator_permission"
    )
    case.setUp()
    try:
        image = Image.new("RGB", (800, 550), "#173746")
        draw = ImageDraw.Draw(image)
        draw.rectangle((160, 120, 640, 400), outline="#48d8c5", width=8)
        picture = io.BytesIO()
        image.save(picture, format="PNG")
        ppt = io.BytesIO()
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[0])
        slide.shapes.title.text = "PRIVATE TEST IMPLEMENTATION"
        presentation.save(ppt)
        files = [
            {
                "name": "技术实现图.png",
                "mimeType": "image/png",
                "buffer": picture.getvalue(),
            },
            {
                "name": "技术方案.pptx",
                "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "buffer": ppt.getvalue(),
            },
            {
                "name": "个人思考.md",
                "mimeType": "text/markdown",
                "buffer": "# PRIVATE_BROWSER_SENTINEL\n<script>window.privateXSS=true</script>".encode(),
            },
            {
                "name": "实验数据.csv",
                "mimeType": "text/csv",
                "buffer": b"voltage,result\n2.1,0.85\n",
            },
        ]
        errors = []
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000}, accept_downloads=True
            )
            assert context.request.post(
                case.base + "/api/auth/login",
                data={"username": "admin", "password": PASSWORD},
                headers={"X-AOI-Client": "local-v1"},
            ).ok
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(case.base)
            page.locator("[data-page=privateknowledge]").click()
            page.locator("#private-add").click()
            form = page.locator("dialog.private-editor form")
            form.locator("[name=title]").fill("个人技术实现与实验备份")
            form.locator("[name=category]").fill("实验数据")
            form.locator("[name=tags]").fill("自用 技术原理")
            form.locator("[name=content]").fill(
                "PRIVATE_BROWSER_SENTINEL：未公开实验思考 <script>window.privateXSS=true</script>"
            )
            form.locator("[data-private-files]").set_input_files(files)
            expect(form.locator(".private-queued")).to_have_count(4)
            form.get_by_role("button", name="保存资料与附件", exact=True).click()
            page.locator("dialog.private-editor").wait_for(state="hidden")
            expect(page.locator(".private-file-card")).to_have_count(4)
            assert page.evaluate("window.privateXSS") is None
            page.locator(
                '[data-private-view][data-file-name="技术实现图.png"]'
            ).first.click()
            expect(page.locator("dialog.private-viewer img")).to_be_visible()
            page.locator("dialog.private-viewer [data-close]").click()
            page.locator(
                '[data-private-view][data-file-name="个人思考.md"]'
            ).first.click()
            expect(page.locator("[data-private-text]")).to_contain_text(
                "<script>window.privateXSS=true</script>"
            )
            assert page.evaluate("window.privateXSS") is None
            page.locator("dialog.private-viewer [data-close]").click()
            page.locator(
                '[data-private-view][data-file-name="技术方案.pptx"]'
            ).first.click()
            expect(page.locator("dialog.private-viewer img")).to_be_visible()
            page.locator("dialog.private-viewer [data-close]").click()
            page.locator("#private-filter").fill("实验数据.csv")
            expect(page.locator(".private-entry")).to_have_count(1)
            page.locator("[data-private-edit]").click()
            form = page.locator("dialog.private-editor form")
            form.locator("[name=title]").fill("已更新的私人技术备份")
            form.get_by_role("button", name="保存资料与附件", exact=True).click()
            page.locator("dialog.private-editor").wait_for(state="hidden")
            expect(page.locator(".private-entry h2")).to_have_text(
                "已更新的私人技术备份"
            )
            page.on("dialog", lambda dialog: dialog.accept())
            page.locator("[data-private-delete]").click()
            expect(page.locator(".private-entry")).to_have_count(0)
            page.locator("#private-trash").click()
            page.locator("[data-private-restore]").click()
            expect(page.locator(".private-entry")).to_have_count(0)
            page.locator("#private-trash").click()
            expect(page.locator(".private-file-card")).to_have_count(4)
            with page.expect_download() as download:
                page.locator(".private-backup").click()
            assert download.value.failure() is None
            if args.screenshots:
                args.screenshots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(args.screenshots / "私人知识备份_桌面.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("[data-private-edit]").click()
            form = page.locator("dialog.private-editor form")
            expect(form).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            assert form.evaluate("el=>el.scrollWidth<=el.clientWidth+1")
            if args.screenshots:
                page.screenshot(
                    path=str(args.screenshots / "私人知识备份_手机录入.png")
                )
            form.locator("[data-close]").click()
            # An open preview and all private page data must disappear on logout.
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.locator(
                '[data-private-view][data-file-name="个人思考.md"]'
            ).first.click()
            expect(page.locator("[data-private-text]")).to_contain_text(
                "PRIVATE_BROWSER_SENTINEL"
            )
            assert context.request.post(
                case.base + "/api/auth/logout",
                data={},
                headers={"X-AOI-Client": "local-v1"},
            ).ok
            page.evaluate("refresh()")
            expect(page.locator("[data-page=privateknowledge]")).to_have_count(0)
            assert "PRIVATE_BROWSER_SENTINEL" not in page.content()
            assert page.locator("dialog.private-dialog").count() == 0
            assert page.evaluate("Object.keys(localStorage).length") == 0
            # Logging in while on the account page must also refresh navigation.
            page.locator("[data-page=accounts]").click()
            page.locator("#login").click()
            login = page.locator("dialog[open] form")
            login.locator("[name=username]").fill("admin")
            login.locator("[name=password]").fill(PASSWORD)
            login.get_by_role("button", name="登录", exact=True).click()
            expect(page.locator("[data-page=privateknowledge]")).to_have_count(1)
            page.locator("#logout").click()
            expect(page.locator("[data-page=privateknowledge]")).to_have_count(0)
            # Even forcibly navigating with client JS cannot display private data.
            page.evaluate("go('privateknowledge')")
            expect(page.locator(".private-entry")).to_have_count(0)
            context.close()
            context = browser.new_context()
            assert context.request.post(
                case.base + "/api/auth/login",
                data={"username": "editor", "password": PASSWORD},
                headers={"X-AOI-Client": "local-v1"},
            ).ok
            page = context.new_page()
            page.goto(case.base)
            expect(page.locator("#engine")).to_contain_text("张表")
            expect(page.locator("[data-page=privateknowledge]")).to_have_count(0)
            page.evaluate("go('privateknowledge')")
            assert "PRIVATE_BROWSER_SENTINEL" not in page.content()
            assert (
                context.request.get(case.base + "/api/private-knowledge/list").status
                == 403
            )
            browser.close()
        assert not errors, errors
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "files": 4,
                    "checks": [
                        "admin navigation",
                        "image/PPT/notes/CSV upload",
                        "image/text/PPT preview",
                        "escaped notes",
                        "search and edit",
                        "recycle and restore",
                        "backup download",
                        "mobile layout",
                        "logout clearing",
                        "guest/editor isolation",
                    ],
                    "javascript_errors": errors,
                },
                ensure_ascii=False,
            )
        )
    finally:
        case.doCleanups()


if __name__ == "__main__":
    main()
