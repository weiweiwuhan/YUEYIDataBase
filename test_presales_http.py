"""Pre-sales validation, uploads, permissions and migration on isolated databases."""

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlencode
from PIL import Image
import test_assistant_http as harness


def image_bytes(color="green"):
    stream = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(stream, format="PNG")
    return stream.getvalue()


def payload(count=2):
    return {
        "record": {
            "name": "双相机售前方案",
            "camera_count": count,
            "remark": "方案原始备注",
        },
        "stations": [
            {
                "name": "工位" + str(i),
                "resolution": "2448×2048 / 500万像素",
                "camera_model": "CAM-" + str(i),
                "lens_model": "LENS-" + str(i),
                "lighting_method": "倾斜打光" if i == 1 else "平视打光",
                "lighting_angle_deg": 30 if i == 1 else None,
                "use_prism": "是" if i == 1 else "否",
                "light_source_type": "环形光",
                "light_source_model": "LIGHT-" + str(i),
            }
            for i in range(1, count + 1)
        ],
    }


class PresalesHTTPTests(unittest.TestCase):
    setUp = harness.AssistantHTTPTests.setUp
    stop_server = harness.AssistantHTTPTests.stop_server
    client = staticmethod(harness.AssistantHTTPTests.client)
    api = harness.AssistantHTTPTests.api
    rejected = harness.AssistantHTTPTests.rejected

    def state(self):
        return self.api(self.guest, "/api/state")["data"]

    def draft(self, data=None):
        return self.api(self.editor, "/api/presales/save", data or payload())["detail"]

    def get(self, rid):
        return self.api(self.guest, "/api/presales/plan?id=" + str(rid))

    def version(self, d):
        return {"id": d["plan"]["id"], "expected_updated_at": d["plan"]["updated_at"]}

    def upload(self, d, station=None, raw=None, opener=None):
        q = {
            "plan_id": d["plan"]["id"],
            "name": "实验室效果图.png",
            "kind": "presales_station" if station else "presales_product",
            "expected_updated_at": d["plan"]["updated_at"],
        }
        if station:
            q["station_id"] = station["id"]
        return self.api(
            opener or self.editor,
            "/api/upload?" + urlencode(q),
            raw=raw or image_bytes(),
        )["detail"]

    def finish(self, d):
        return self.api(self.editor, "/api/presales/complete", self.version(d))[
            "detail"
        ]

    def complete_plan(self, count=2):
        d = self.draft(payload(count))
        d = self.upload(d)
        for index in range(count):
            d = self.upload(
                d, d["stations"][index], image_bytes("blue" if index else "red")
            )
        return self.finish(d)

    def edit_payload(self, d):
        return {**self.version(d), "record": d["plan"], "stations": d["stations"]}

    def test_complete_requires_original_photo_and_one_image_for_every_camera(self):
        d = self.draft()
        self.assertEqual(d["plan"]["status"], "草稿")
        self.assertEqual(len(d["stations"]), 2)
        self.rejected(400, self.editor, "/api/presales/complete", self.version(d))
        d = self.upload(d)
        self.rejected(400, self.editor, "/api/presales/complete", self.version(d))
        d = self.upload(d, d["stations"][0])
        error = self.rejected(
            400, self.editor, "/api/presales/complete", self.version(d)
        )
        self.assertIn("相机2", error["error"])
        d = self.upload(d, d["stations"][1], image_bytes("blue"))
        d = self.finish(d)
        self.assertEqual(d["plan"]["status"], "已完成")
        self.assertEqual(d["plan"]["camera_count"], len(d["stations"]))
        self.assertEqual(len(d["photos"]), 1)
        self.assertNotEqual(
            d["stations"][0]["image_asset_id"], d["stations"][1]["image_asset_id"]
        )
        self.assertEqual(d["plan"]["created_by"], "editor")
        for asset in d["assets"].values():
            self.assertEqual(asset["created_by"], "editor")
            path = self.data / "uploads" / asset["relative_path"]
            self.assertTrue(path.is_file())
            self.assertTrue(path.parts[-3] == "images")
        self.assertFalse(
            self.state()["images"],
            "pre-sales photos should not enter the inspection-image library",
        )
        graph = self.api(
            self.guest,
            "/api/knowledge/graph?table=presales_plans&id="
            + str(d["plan"]["id"])
            + "&depth=1",
        )
        self.assertTrue(
            {"产品原始照片", "实验室效果图"}
            <= {edge["relation"] for edge in graph["edges"]}
        )

    def test_angle_and_camera_count_are_enforced_on_the_server(self):
        variants = []
        for angle in (None, 0, -1, 91, "NaN"):
            bad = payload()
            bad["stations"][0]["lighting_angle_deg"] = angle
            variants.append(bad)
        bad = payload()
        bad["stations"][1]["lighting_angle_deg"] = 20
        variants.append(bad)
        for count in (0, 65, 1.5, True):
            bad = payload()
            bad["record"]["camera_count"] = count
            variants.append(bad)
        bad = payload()
        bad["stations"].pop()
        variants.append(bad)
        bad = payload()
        bad["stations"][0]["use_prism"] = "也许"
        variants.append(bad)
        bad = payload()
        bad["stations"][0]["camera_model"] = ""
        variants.append(bad)
        for bad in variants:
            with self.subTest(data=bad):
                self.rejected(400, self.editor, "/api/presales/save", bad)
        self.assertFalse(self.state()["presales_plans"])
        self.assertFalse(self.state()["presales_stations"])

    def test_bad_images_and_foreign_station_uploads_roll_back_files_and_records(self):
        first = self.draft(payload(1))
        second = self.draft(payload(1))
        before = self.state()
        files = set((self.data / "uploads").rglob("*"))
        for raw in (b"not an image", b"%PDF-pretend-image"):
            query = {
                "kind": "presales_station",
                "plan_id": first["plan"]["id"],
                "station_id": first["stations"][0]["id"],
                "name": "bad.png",
                "expected_updated_at": first["plan"]["updated_at"],
            }
            self.rejected(400, self.editor, "/api/upload?" + urlencode(query), raw=raw)
        query = {
            "kind": "presales_station",
            "plan_id": first["plan"]["id"],
            "station_id": second["stations"][0]["id"],
            "name": "wrong.png",
            "expected_updated_at": first["plan"]["updated_at"],
        }
        self.rejected(
            400, self.editor, "/api/upload?" + urlencode(query), raw=image_bytes()
        )
        self.assertEqual(self.state(), before)
        self.assertEqual(set((self.data / "uploads").rglob("*")), files)

    def test_roles_and_whole_plan_revision_protect_metadata_and_uploads(self):
        for path, data in [
            ("/api/presales/save", payload()),
            ("/api/presales/complete", {"id": 1}),
            ("/api/presales/delete", {"id": 1}),
        ]:
            self.rejected(403, self.guest, path, data)
        d = self.draft()
        old = copy.deepcopy(d)
        d = self.upload(d)
        self.rejected(409, self.editor, "/api/presales/save", self.edit_payload(old))
        self.rejected(409, self.editor, "/api/presales/complete", self.version(old))
        query = {
            "kind": "presales_station",
            "plan_id": old["plan"]["id"],
            "station_id": old["stations"][0]["id"],
            "name": "stale.png",
            "expected_updated_at": old["plan"]["updated_at"],
        }
        before = self.state()
        self.rejected(
            409, self.editor, "/api/upload?" + urlencode(query), raw=image_bytes()
        )
        self.assertEqual(self.state(), before)
        self.rejected(403, self.editor, "/api/presales/delete", self.version(d))
        self.rejected(
            403,
            self.editor,
            "/api/presales/photo-delete",
            {**self.version(d), "photo_id": d["photos"][0]["id"]},
        )
        changed = self.edit_payload(d)
        changed["stations"] = changed["stations"][:1]
        changed["record"] = {**changed["record"], "camera_count": 1}
        self.rejected(403, self.editor, "/api/presales/save", changed)
        for table in ("presales_plans", "presales_stations", "presales_product_photos"):
            self.rejected(
                400, self.editor, "/api/save", {"table": table, "record": {}, "id": 1}
            )
            self.rejected(400, self.admin, "/api/delete", {"table": table, "id": 1})

    def test_image_replacement_keeps_old_file_and_deletion_keeps_all_assets(self):
        d = self.complete_plan(1)
        old = d["stations"][0]["image_asset_id"]
        asset = d["assets"][str(old)]
        path = self.data / "uploads" / asset["relative_path"]
        content = path.read_bytes()
        d = self.upload(d, d["stations"][0], image_bytes("navy"))
        self.assertNotEqual(d["stations"][0]["image_asset_id"], old)
        self.assertEqual(d["plan"]["status"], "已完成")
        self.assertEqual(path.read_bytes(), content)
        self.rejected(
            400,
            self.admin,
            "/api/presales/photo-delete",
            {**self.version(d), "photo_id": d["photos"][0]["id"]},
        )
        d = self.upload(d)
        photo = d["photos"][0]
        d = self.api(
            self.admin,
            "/api/presales/photo-delete",
            {**self.version(d), "photo_id": photo["id"]},
        )["detail"]
        self.assertEqual(len(d["photos"]), 1)
        before = self.state()
        paths = [(self.data / "uploads" / a["relative_path"]) for a in before["assets"]]
        self.api(self.admin, "/api/presales/delete", self.version(d))
        after = self.state()
        self.assertFalse(after["presales_plans"])
        self.assertFalse(after["presales_stations"])
        self.assertFalse(after["presales_product_photos"])
        self.assertEqual(before["assets"], after["assets"])
        self.assertTrue(all(p.is_file() for p in paths))
        self.assertTrue(
            any(
                r["action"] == "/api/presales/delete" and r["actor"] == "admin"
                for r in self.api(self.admin, "/api/audit")
            )
        )

    def test_generic_asset_edit_cannot_break_an_already_completed_plan(self):
        d = self.complete_plan(1)
        asset = next(iter(d["assets"].values()))
        before = self.state()
        self.rejected(
            400,
            self.editor,
            "/api/save",
            {
                "table": "assets",
                "id": asset["id"],
                "record": {**asset, "asset_type": "document"},
            },
        )
        self.assertEqual(self.state(), before)
        self.assertEqual(self.get(d["plan"]["id"])["plan"]["status"], "已完成")


class PresalesMigrationTests(unittest.TestCase):
    def test_additive_upgrade_preserves_older_records_and_can_run_twice(self):
        script = """
import app
app.initialize();c=app.connect();app.save(c,'products',{'id':12,'name':'旧产品保留'})
for table in ('presales_product_photos','presales_stations','presales_plans'):c.execute('DROP TABLE '+table)
c.commit();c.close();app.initialize();app.initialize();c=app.connect()
assert c.execute('SELECT name FROM products WHERE id=12').fetchone()[0]=='旧产品保留'
for table in ('presales_plans','presales_stations','presales_product_photos'):assert c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
assert not c.execute('PRAGMA foreign_key_check').fetchall();c.close()
"""
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).parent,
                env=dict(
                    os.environ,
                    AOI_DATA=temp,
                    DB_ENGINE="sqlite",
                    PYTHONDONTWRITEBYTECODE="1",
                ),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
