"""Dictionary maintenance through isolated HTTP; no business database is touched."""

import io
import unittest
from urllib.parse import urlencode
from PIL import Image
import test_assistant_http as harness_module


class DictionaryMaintenanceHTTPTests(unittest.TestCase):
    setUp = harness_module.AssistantHTTPTests.setUp
    stop_server = harness_module.AssistantHTTPTests.stop_server
    client = staticmethod(harness_module.AssistantHTTPTests.client)
    api = harness_module.AssistantHTTPTests.api
    rejected = harness_module.AssistantHTTPTests.rejected

    def save(self, table, record, rid=None):
        return self.api(
            self.editor, "/api/save", {"table": table, "record": record, "id": rid}
        )["id"]

    def state(self):
        return self.api(self.guest, "/api/state")["data"]

    def record(self, table, rid):
        return next(row for row in self.state()[table] if row["id"] == rid)

    def graph(self, table, rid):
        return self.api(
            self.guest,
            "/api/knowledge/graph?"
            + urlencode({"table": table, "id": rid, "depth": 1}),
        )

    def binding(self, table, rid, product_id=1):
        return next(
            edge["binding"]
            for edge in self.graph(table, rid)["edges"]
            if edge.get("binding") and edge["source"] == "products:" + str(product_id)
        )

    def unlink(self, binding, opener=None):
        return self.api(
            opener or self.admin,
            "/api/knowledge/unlink-binding",
            {
                **binding,
                "expected_updated_at": binding["updated_at"],
            },
        )

    def delete(self, table, rid):
        return self.api(self.admin, "/api/delete", {"table": table, "id": rid})

    def attach_material(self, material, product_id=1):
        self.save(
            "products",
            {**self.record("products", product_id), "material_id": material},
            product_id,
        )

    def test_material_cleanup_keeps_products_files_and_other_dictionary_values(self):
        material = self.save("materials", {"name": "录错材质"})
        correct = self.save("materials", {"name": "正确材质"})
        self.attach_material(material)
        second = self.save(
            "products",
            {"name": "另一个产品", "material_id": material, "spec_text": "M6x20"},
        )
        self.save("project_products", {"project_id": 1, "product_id": 1})
        out = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(out, format="PNG")
        uploaded = self.api(
            self.editor,
            "/api/upload?"
            + urlencode({"name": "保留的产品图.png", "image_only": 1, "product_id": 1}),
            raw=out.getvalue(),
        )
        before = self.state()
        asset = next(r for r in before["assets"] if r["id"] == uploaded["asset_id"])
        image_path = self.data / "uploads" / asset["relative_path"]
        image_bytes = image_path.read_bytes()
        experience = self.save(
            "technical_experiences",
            {"name": "待修正适用范围", "content": "经验正文保留"},
        )
        link = self.save(
            "knowledge_links",
            {
                "source_table": "technical_experiences",
                "source_id": experience,
                "relation": "适用于",
                "target_table": "materials",
                "target_id": material,
                "confirmation_status": "待验证",
            },
        )
        self.save(
            "entity_aliases",
            {"entity_table": "materials", "entity_id": material, "name": "错材质别名"},
        )
        error = self.rejected(
            400, self.admin, "/api/delete", {"table": "materials", "id": material}
        )
        self.assertIn("2 个产品", error["error"])
        self.assertIn("1 条知识关联", error["error"])
        self.unlink(self.binding("materials", material, 1))
        self.unlink(self.binding("materials", material, second))
        self.rejected(
            400, self.admin, "/api/delete", {"table": "materials", "id": material}
        )
        self.delete("knowledge_links", link)
        self.delete("materials", material)
        after = self.state()
        self.assertIsNone(self.record("products", 1)["material_id"])
        self.assertIsNone(self.record("products", second)["material_id"])
        self.assertEqual(self.record("products", second)["spec_text"], "M6x20")
        self.assertEqual(
            self.record("products", 1)["created_by"],
            before["products"][0]["created_by"],
        )
        self.assertEqual(self.record("products", 1)["updated_by"], "admin")
        self.assertEqual(self.record("materials", correct)["name"], "正确材质")
        for table in (
            "assets",
            "images",
            "project_products",
            "asset_products",
            "technical_experiences",
        ):
            self.assertEqual(
                len(after[table]),
                len(before[table]) + (1 if table == "technical_experiences" else 0),
            )
        self.assertEqual(image_path.read_bytes(), image_bytes)
        self.assertFalse(
            [
                r
                for r in after["entity_aliases"]
                if r["entity_table"] == "materials" and r["entity_id"] == material
            ]
        )
        audit = self.api(self.admin, "/api/audit")
        self.assertTrue(
            any(
                r["action"] == "/api/knowledge/unlink-binding" and r["actor"] == "admin"
                for r in audit
            )
        )

    def test_process_cleanup_removes_only_the_selected_product_relation(self):
        process = self.save("process_types", {"name": "错工艺"})
        keep = self.save("process_types", {"name": "保留工艺"})
        second = self.save("products", {"name": "产品二"})
        first = self.save("product_processes", {"product_id": 1, "process_id": process})
        kept_link = self.save(
            "product_processes", {"product_id": 1, "process_id": keep}
        )
        self.save("product_processes", {"product_id": second, "process_id": process})
        self.rejected(
            400, self.admin, "/api/delete", {"table": "process_types", "id": process}
        )
        self.unlink(self.binding("process_types", process, 1))
        state = self.state()
        self.assertFalse(any(r["id"] == first for r in state["product_processes"]))
        self.assertEqual(
            self.record("product_processes", kept_link)["process_id"], keep
        )
        self.rejected(
            400, self.admin, "/api/delete", {"table": "process_types", "id": process}
        )
        self.unlink(self.binding("process_types", process, second))
        self.delete("process_types", process)
        self.assertEqual(len(self.state()["products"]), 2)
        self.assertEqual(
            self.state()["product_processes"],
            [self.record("product_processes", kept_link)],
        )

    def test_only_administrators_can_unlink_and_unknown_binding_kinds_are_rejected(
        self,
    ):
        material = self.save("materials", {"name": "材质"})
        process = self.save("process_types", {"name": "工艺"})
        self.attach_material(material)
        self.save("product_processes", {"product_id": 1, "process_id": process})
        for table, rid in [("materials", material), ("process_types", process)]:
            binding = self.binding(table, rid)
            for opener in (self.guest, self.editor):
                self.rejected(
                    403,
                    opener,
                    "/api/knowledge/unlink-binding",
                    {**binding, "expected_updated_at": binding["updated_at"]},
                )
                self.rejected(403, opener, "/api/delete", {"table": table, "id": rid})
        before = self.state()
        self.rejected(
            400,
            self.admin,
            "/api/knowledge/unlink-binding",
            {"kind": "products", "id": 1, "target_id": material},
        )
        self.assertEqual(self.state(), before)

    def test_stale_or_retargeted_bindings_are_not_cleared(self):
        material = self.save("materials", {"name": "旧材质"})
        correct = self.save("materials", {"name": "新材质"})
        self.attach_material(material)
        old = self.binding("materials", material)
        self.attach_material(correct)
        before = self.record("products", 1)
        self.rejected(
            409,
            self.admin,
            "/api/knowledge/unlink-binding",
            {**old, "expected_updated_at": old["updated_at"]},
        )
        self.rejected(
            409,
            self.admin,
            "/api/knowledge/unlink-binding",
            {**old, "expected_updated_at": before["updated_at"]},
        )
        self.assertEqual(self.record("products", 1), before)
        process = self.save("process_types", {"name": "旧工艺"})
        replacement = self.save("process_types", {"name": "新工艺"})
        relation = self.save(
            "product_processes", {"product_id": 1, "process_id": process}
        )
        old = self.binding("process_types", process)
        self.save(
            "product_processes", {"product_id": 1, "process_id": replacement}, relation
        )
        self.rejected(
            409,
            self.admin,
            "/api/knowledge/unlink-binding",
            {**old, "expected_updated_at": old["updated_at"]},
        )
        self.assertEqual(
            self.record("product_processes", relation)["process_id"], replacement
        )
        current = self.record("materials", material)
        self.save("materials", {**current, "name": "已由他人更名"}, material)
        self.rejected(
            409,
            self.admin,
            "/api/delete",
            {
                "table": "materials",
                "id": material,
                "expected_updated_at": current["updated_at"],
            },
        )
        self.assertEqual(self.record("materials", material)["name"], "已由他人更名")

    def test_verified_experience_scope_is_checked_and_failed_unlinks_roll_back(self):
        material = self.save("materials", {"name": "已验证材质"})
        process = self.save("process_types", {"name": "已验证工艺"})
        self.attach_material(material)
        self.save("product_processes", {"product_id": 1, "process_id": process})
        test = self.save(
            "model_tests",
            {
                "name": "范围验证",
                "model_name": "测试模型",
                "product_id": 1,
                "test_count": 100,
            },
        )
        experience = self.api(
            self.editor,
            "/api/knowledge/save",
            {
                "table": "technical_experiences",
                "record": {
                    "name": "有测试依据的经验",
                    "content": "保留已验证适用范围",
                    "confirmation_status": "已验证",
                },
                "links": [
                    {
                        "relation": "测试依据",
                        "target_table": "model_tests",
                        "target_id": test,
                    }
                ]
                + [
                    {
                        "relation": "适用于",
                        "target_table": table,
                        "target_id": rid,
                        "confirmation_status": "已验证",
                        "evidence_test_id": test,
                    }
                    for table, rid in [
                        ("materials", material),
                        ("process_types", process),
                    ]
                ],
            },
        )["id"]
        replacement = self.save("process_types", {"name": "不同的替代工艺"})
        before = self.state()
        for table, rid in [("materials", material), ("process_types", process)]:
            binding = self.binding(table, rid)
            self.rejected(
                400,
                self.admin,
                "/api/knowledge/unlink-binding",
                {**binding, "expected_updated_at": binding["updated_at"]},
            )
            self.assertEqual(self.state(), before)
        # The normal record editor and relation table must enforce the same scope.
        self.rejected(
            400,
            self.editor,
            "/api/save",
            {
                "table": "products",
                "id": 1,
                "record": {**self.record("products", 1), "material_id": None},
            },
        )
        self.assertEqual(self.state(), before)
        relation = next(
            r for r in before["product_processes"] if r["process_id"] == process
        )
        self.rejected(
            400,
            self.admin,
            "/api/delete",
            {
                "table": "product_processes",
                "id": relation["id"],
            },
        )
        self.assertEqual(self.state(), before)
        self.rejected(
            400,
            self.editor,
            "/api/save",
            {
                "table": "product_processes",
                "id": relation["id"],
                "record": {**relation, "process_id": replacement},
            },
        )
        self.assertEqual(self.state(), before)
        links = [
            r
            for r in self.state()["knowledge_links"]
            if r["source_id"] == experience and r["relation"] == "适用于"
        ]
        for link in links:
            self.delete("knowledge_links", link["id"])
        self.unlink(self.binding("materials", material))
        self.unlink(self.binding("process_types", process))
        self.assertIsNone(self.record("products", 1)["material_id"])
        self.assertFalse(self.state()["product_processes"])
        self.assertEqual(len(self.state()["technical_experiences"]), 1)


if __name__ == "__main__":
    unittest.main()
