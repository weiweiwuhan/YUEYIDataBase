"""Real HTTP privacy boundaries and durable backups, using isolated data only."""

import io
import json
from pathlib import Path
import sqlite3
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlencode
import zipfile

from PIL import Image
import test_assistant_http as harness
from private_knowledge import PrivateKnowledge, MAX_FILE


class PrivateKnowledgeHTTPTests(unittest.TestCase):
    setUp = harness.AssistantHTTPTests.setUp
    stop_server = harness.AssistantHTTPTests.stop_server
    client = staticmethod(harness.AssistantHTTPTests.client)
    api = harness.AssistantHTTPTests.api
    rejected = harness.AssistantHTTPTests.rejected

    def create(self, **changes):
        record = dict(
            title="PRIVATE_SENTINEL_技术实现",
            category="实验数据",
            tags="自用原理",
            content="PRIVATE_SENTINEL_未公开的实验结论 <script>secret</script>",
        )
        record.update(changes)
        return self.api(self.admin, "/api/private-knowledge/save", {"record": record})[
            "detail"
        ]

    def version(self, entry):
        return {"id": entry["id"], "expected_updated_at": entry["updated_at"]}

    def upload(
        self,
        entry,
        name="PRIVATE_SENTINEL_实验数据.csv",
        raw=b"voltage,result\n2.1,0.85\n",
    ):
        q = urlencode({**self.version(entry), "name": name})
        return self.api(self.admin, "/api/private-knowledge/upload?" + q, raw=raw)[
            "detail"
        ]

    def detail(self, entry):
        return self.api(
            self.admin, "/api/private-knowledge/detail?id=" + str(entry["id"])
        )

    def raw(self, opener, url):
        with opener.open(self.base + url, timeout=30) as response:
            return response.read(), dict(response.headers)

    def test_every_private_route_requires_live_administrator_permission(self):
        entry = self.upload(self.create())
        fid = entry["files"][0]["id"]
        gets = ["/list", "/detail?id=" + str(entry["id"]), "/backup"] + [
            "/file?" + urlencode({"id": fid, "mode": mode})
            for mode in ("original", "view", "preview")
        ]
        posts = [
            ("/save", {"record": {"title": "blocked"}}),
            ("/delete", self.version(entry)),
            ("/restore", self.version(entry)),
            ("/file-delete", {**self.version(entry), "file_id": fid}),
        ]
        for opener in (self.guest, self.editor, self.other):
            for path in gets:
                self.rejected(403, opener, "/api/private-knowledge" + path)
            for path, body in posts:
                self.rejected(403, opener, "/api/private-knowledge" + path, body)
            self.rejected(
                403,
                opener,
                "/api/private-knowledge/upload?"
                + urlencode({**self.version(entry), "name": "hidden.txt"}),
                raw=b"secret",
            )
        self.api(self.admin, "/api/auth/logout", {})
        for path in gets:
            self.rejected(403, self.admin, "/api/private-knowledge" + path)

    def test_private_content_never_enters_public_state_graph_rag_or_generic_exports(
        self,
    ):
        before = self.api(self.guest, "/api/state")["data"]
        entry = self.upload(self.create())
        for opener in (self.guest, self.editor, self.admin):
            state = self.api(opener, "/api/state")
            self.assertEqual(state["data"], before)
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(state, ensure_ascii=False))
        graph = self.api(self.guest, "/api/knowledge/graph")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(graph, ensure_ascii=False))
        answer = self.api(
            self.editor,
            "/api/assistant/chat",
            {"question": "PRIVATE_SENTINEL_技术实现的未公开实验结论是什么"},
        )
        self.assertFalse(answer["sources"])
        status = self.api(self.editor, "/api/assistant/status")
        self.assertEqual(status["documents"], 0)
        sql, _ = self.raw(self.admin, "/api/sql?data=1")
        self.assertNotIn(b"PRIVATE_SENTINEL", sql)
        self.assertNotIn(b"private_entries", sql)
        for table in ("private_entries", "private_files"):
            self.rejected(400, self.editor, "/api/records?table=" + table)
            self.rejected(
                400,
                self.editor,
                "/api/save",
                {"table": table, "record": {"title": "bad"}},
            )
            self.rejected(400, self.admin, "/api/import", {"data": {table: [entry]}})
        # Private IDs have no mapping in the public resource namespace.
        fid = entry["files"][0]["id"]
        for path in (
            "/api/media?id=" + str(fid) + "&mode=original",
            "/api/preview?table=private_files&id=" + str(fid),
            "/private_knowledge/vault.sqlite3",
            "/private_knowledge/files/",
        ):
            with self.assertRaises(urllib.error.HTTPError):
                self.raw(self.guest, path)

    def test_images_documents_data_and_active_content_have_safe_delivery(self):
        entry = self.create()
        image = io.BytesIO()
        Image.new("RGB", (100, 70), "blue").save(image, format="PNG")
        for name, data in [
            ("技术实现.png", image.getvalue()),
            ("思考.md", "# 思考\n<script>alert(1)</script>".encode()),
            ("实验.xlsx", b"opaque-spreadsheet"),
            ("页面.html", b"<script>alert(1)</script>"),
        ]:
            entry = self.upload(entry, name, data)
            f = entry["files"][-1]
            self.assertEqual(f["created_by"], "admin")
            result, headers = self.raw(
                self.admin, "/api/private-knowledge/file?id=" + str(f["id"])
            )
            self.assertEqual(result, data)
            self.assertIn("attachment", headers["Content-Disposition"])
            self.assertEqual(headers["Content-Type"], "application/octet-stream")
            self.assertIn("no-store", headers["Cache-Control"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        image_id = entry["files"][0]["id"]
        for mode in ("view", "preview"):
            data, headers = self.raw(
                self.admin,
                "/api/private-knowledge/file?"
                + urlencode({"id": image_id, "mode": mode}),
            )
            with Image.open(io.BytesIO(data)) as picture:
                self.assertGreater(picture.width, 0)
            self.assertIn("no-store", headers["Cache-Control"])
        md_id = entry["files"][1]["id"]
        text, headers = self.raw(
            self.admin, "/api/private-knowledge/file?id=" + str(md_id) + "&mode=view"
        )
        self.assertIn(b"<script>", text)
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        self.assertIn("sandbox", headers["Content-Security-Policy"])
        self.rejected(
            400,
            self.admin,
            "/api/private-knowledge/file?id="
            + str(entry["files"][-1]["id"])
            + "&mode=view",
        )

    def test_bad_uploads_and_stale_versions_do_not_leave_files_or_lose_notes(self):
        entry = self.create()
        root = self.data / "private_knowledge" / "files"
        for name, data in [
            ("bad.png", b"invalid-image"),
            ("../leak.txt", b"private"),
            ("empty.txt", b""),
        ]:
            self.rejected(
                400,
                self.admin,
                "/api/private-knowledge/upload?"
                + urlencode({**self.version(entry), "name": name}),
                raw=data,
            )
        self.assertFalse(list(root.iterdir()))
        old = entry
        entry = self.upload(entry)
        before = set(root.iterdir())
        self.rejected(
            409,
            self.admin,
            "/api/private-knowledge/save",
            {**self.version(old), "record": {"title": "stale"}},
        )
        self.rejected(
            409,
            self.admin,
            "/api/private-knowledge/upload?"
            + urlencode({**self.version(old), "name": "stale.txt"}),
            raw=b"dont save",
        )
        self.rejected(
            409, self.admin, "/api/private-knowledge/delete", self.version(old)
        )
        self.assertEqual(set(root.iterdir()), before)
        self.assertEqual(self.detail(entry), entry)
        other = self.create(title="另一条私人资料")
        self.rejected(
            400,
            self.admin,
            "/api/private-knowledge/file-delete",
            {**self.version(other), "file_id": entry["files"][0]["id"]},
        )
        self.rejected(
            400,
            self.admin,
            "/api/private-knowledge/save",
            {"record": {"title": "bad", "storage_path": "../../public"}},
        )
        store = PrivateKnowledge(self.data)
        with self.assertRaises(ValueError):
            store.upload(
                {"id": [str(entry["id"])], "name": ["huge.bin"]},
                io.BytesIO(b"x"),
                MAX_FILE + 1,
                {"username": "admin"},
                lambda name: name,
            )

    def test_search_edit_recycle_restore_and_complete_backup_are_durable(self):
        entry = self.upload(
            self.create(), "技术实现.pptx", b"original-presentation-backup"
        )
        first = entry["files"][0]
        entry = self.upload(entry)
        removed = entry["files"][-1]
        self.api(
            self.admin,
            "/api/private-knowledge/file-delete",
            {**self.version(entry), "file_id": removed["id"]},
        )
        entry = self.detail(entry)
        self.rejected(
            400, self.admin, "/api/private-knowledge/file?id=" + str(removed["id"])
        )
        record = {k: entry[k] for k in ("title", "category", "tags", "content")}
        record["title"] = "更新后的敏感方案"
        entry = self.api(
            self.admin,
            "/api/private-knowledge/save",
            {**self.version(entry), "record": record},
        )["detail"]
        for term in ("敏感方案", "实验数据", "技术实现.pptx", "未公开"):
            found = self.api(
                self.admin, "/api/private-knowledge/list?" + urlencode({"q": term})
            )
            self.assertEqual(found["total"], 1)
        self.api(self.admin, "/api/private-knowledge/delete", self.version(entry))
        self.assertEqual(
            self.api(self.admin, "/api/private-knowledge/list")["total"], 0
        )
        self.rejected(
            400, self.admin, "/api/private-knowledge/file?id=" + str(first["id"])
        )
        trash = self.api(self.admin, "/api/private-knowledge/list?trash=1")["data"][0]
        self.api(self.admin, "/api/private-knowledge/restore", self.version(trash))
        restored = self.detail(entry)
        self.assertEqual(restored["files"][0]["id"], first["id"])
        archive, headers = self.raw(self.admin, "/api/private-knowledge/backup")
        self.assertIn("no-store", headers["Cache-Control"])
        backup_dir = self.data / "restored"
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            self.assertEqual(len([n for n in bundle.namelist() if "/files/" in n]), 2)
            bundle.extractall(backup_dir)
        vault = backup_dir / "private_knowledge" / "vault.sqlite3"
        with sqlite3.connect(vault) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                db.execute("SELECT title FROM private_entries").fetchone()[0],
                record["title"],
            )
        # A restored standalone store retains metadata, original files and deleted history.
        store = PrivateKnowledge(backup_dir)
        self.assertEqual(store.detail(entry["id"])["files"], restored["files"])
        self.assertEqual(
            store.file(first["id"])[1].read_bytes(), b"original-presentation-backup"
        )
        self.assertFalse(list((self.data / "private_knowledge").glob("backup-*")))

    def test_private_files_cannot_be_reached_via_public_storage_path(self):
        entry = self.upload(self.create(), "private.txt", b"PRIVATE_SENTINEL_BYTES")
        with sqlite3.connect(self.data / "private_knowledge" / "vault.sqlite3") as db:
            stored = db.execute("SELECT stored_name FROM private_files").fetchone()[0]
        public = self.api(
            self.editor, "/api/upload?name=public.txt", raw=b"public only"
        )
        state = self.api(self.guest, "/api/state")["data"]
        asset = next(r for r in state["assets"] if r["id"] == public["asset_id"])
        self.rejected(
            400,
            self.editor,
            "/api/save",
            {
                "table": "assets",
                "id": asset["id"],
                "record": {
                    **asset,
                    "relative_path": "../private_knowledge/files/" + stored,
                },
            },
        )
        data, _ = self.raw(
            self.guest, "/api/media?id=" + str(asset["id"]) + "&mode=original"
        )
        self.assertEqual(data, b"public only")


if __name__ == "__main__":
    unittest.main()
