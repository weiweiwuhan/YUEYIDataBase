import csv
import io
import unittest
import zipfile

import experience_import as importer


PROJECTS = [{"id": 1, "name": "圆环项目", "code": "P001"}]
PRODUCTS = [{"id": 2, "name": "圆环", "code": "R002"}]
DEFAULTS = {"project_id": 1, "product_id": 2}


def csv_bytes(headers, rows, encoding="utf-8-sig", delimiter=","):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode(encoding)


def prepare(content, filename="经验.csv", **kwargs):
    return importer.prepare_import(content, filename, kwargs.pop("projects", PROJECTS), kwargs.pop("products", PRODUCTS), kwargs.pop("existing", []), kwargs.pop("defaults", DEFAULTS), **kwargs)


class ExperienceImportTests(unittest.TestCase):
    def test_question_sheet_preserves_question_and_category(self):
        question = "如何处理圆环表面划伤？" * 40
        content = csv_bytes(["问题类型", "问题描述", "解决方案"], [["表面缺陷", question, "检查治具并调整曝光。"]])
        plan = prepare(content)
        self.assertEqual(plan["errors"], [])
        self.assertEqual(plan["valid_count"], 1)
        row = plan["rows"][0]
        self.assertEqual(row["row"], 2)
        self.assertEqual(row["record"]["name"], question[:191])
        self.assertEqual(row["record"]["symptom"], question)
        self.assertEqual(row["record"]["remark"], "问题类型：表面缺陷")
        self.assertEqual(row["record"]["status"], "已解决")
        self.assertEqual(row["record"]["project_id"], 1)
        self.assertEqual(row["record"]["product_id"], 2)

    def test_gb18030_semicolon_and_named_bindings(self):
        content = csv_bytes(["项目", "产品", "问题标题", "售后日期", "处理状态", "问题现象", "原因分析", "处理方案", "经验与预防措施", "备注"], [["P001", "圆环", "划伤", "2026/11/6", "处理中", "可见划痕", "治具磨损", "更换治具", "定期检查", "复查中"]], encoding="gb18030", delimiter=";")
        plan = prepare(content, defaults={})
        self.assertFalse(plan["errors"])
        self.assertEqual(plan["rows"][0]["record"]["service_date"], "2026-11-06")
        self.assertEqual(plan["rows"][0]["record"]["experience"], "定期检查")

    def test_tab_separated_and_blank_lines(self):
        content = b"\n\nquestion\tsolution\n\nQ\tA\n\t\n"
        plan = prepare(content)
        self.assertEqual(plan["total"], 1)
        self.assertEqual(plan["rows"][0]["row"], 5)

    def test_missing_and_invalid_bindings_never_guess(self):
        content = csv_bytes(["question", "solution"], [["Q", "A"]])
        missing = prepare(content, defaults={})
        self.assertIn("缺少项目", missing["errors"][0]["message"])
        invalid = prepare(content, defaults={"project_id": 999, "product_id": 2})
        self.assertIn("不存在", invalid["errors"][0]["message"])
        ambiguous = csv_bytes(["项目", "产品", "问题标题"], [["圆环项目", "圆环", "Q"]])
        plan = prepare(ambiguous, projects=PROJECTS + [{"id": 3, "name": "圆环项目", "code": "P003"}])
        self.assertIn("多条记录", plan["errors"][0]["message"])

    def test_deduplicates_existing_and_in_file_without_author_fields(self):
        content = csv_bytes(["question", "solution"], [["Q1", "A1"], ["Q1", "A1"], ["Q2", "A2"]])
        first = prepare(content)
        self.assertEqual(first["valid_count"], 2)
        self.assertEqual(first["duplicate_count"], 1)
        existing = dict(first["rows"][0]["record"], id=42, created_by="admin", created_at="2026-11-06")
        second = prepare(content, existing=[existing])
        self.assertEqual(second["valid_count"], 1)
        self.assertEqual(second["duplicate_count"], 2)
        self.assertEqual(second["rows"][0]["record"]["name"], "Q2")

    def test_invalid_rows_do_not_remove_other_preview_rows(self):
        content = csv_bytes(["问题标题", "售后日期", "状态"], [["有效", "2026-11-06", "待处理"], ["无效日期", "2026-02-30", "待处理"], ["无效状态", "", "完成"]])
        plan = prepare(content)
        self.assertEqual(plan["total"], 3)
        self.assertEqual(plan["valid_count"], 1)
        self.assertEqual([error["row"] for error in plan["errors"]], [3, 4])

    def test_explicit_title_and_cells_are_not_silently_truncated(self):
        title = csv_bytes(["问题标题"], [["长" * 192]])
        self.assertIn("191", prepare(title)["errors"][0]["message"])
        long_cell = csv_bytes(["question", "solution"], [["Q", "A" * 20001]])
        self.assertIn("20000", prepare(long_cell)["errors"][0]["message"])
        with self.assertRaisesRegex(ValueError, "第 2 行"):
            importer.parse_table(long_cell, "经验.csv")

    def test_duplicate_aliases_and_unknown_columns_are_rejected(self):
        for headers in (["项目", "project_id", "问题标题"], ["问题标题", "问题标题"], ["问题标题", "", "备注"]):
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                prepare(csv_bytes(headers, [["1", "2", "Q"]]))
        plan = prepare(csv_bytes(["question", "unexpected"], [["Q", "important data"]]))
        self.assertIn("不支持的列", plan["errors"][0]["message"])

    def test_exported_audit_columns_are_ignored_without_affecting_deduplication(self):
        for audit_headers in (["id", "created_by", "created_at", "updated_by", "updated_at"], ["编号", "录入作者", "录入时间", "最后修改人", "最后修改时间"]):
            with self.subTest(headers=audit_headers):
                headers = ["项目", "产品", "问题标题", "处理方案"] + audit_headers
                rows = [[1, 2, "划伤", "更换治具", 999, "伪造作者", "2000-01-01", "其他人", "2001-01-01"], [1, 2, "划伤", "更换治具", 1000, "另一作者", "2002-01-01", "又一个人", "2003-01-01"]]
                plan = prepare(csv_bytes(headers, rows))
                self.assertEqual(plan["errors"], [])
                self.assertEqual(plan["valid_count"], 1)
                self.assertEqual(plan["duplicate_count"], 1)
                record = plan["rows"][0]["record"]
                self.assertEqual(set(record), set(importer.RECORD_FIELDS))
                self.assertTrue(importer.IGNORED_READONLY_FIELDS.isdisjoint(record))
                without_audit = prepare(csv_bytes(headers[:4], [rows[0][:4]]))
                self.assertEqual(record, without_audit["rows"][0]["record"])

    def test_empty_unsupported_oversized_and_malformed_files(self):
        for content, filename in ((b"", "a.csv"), (b"x", "a.xls"), (b"x" * (importer.MAX_UPLOAD_BYTES + 1), "a.csv"), (b"Q\x00,A", "a.csv"), (b'question,solution\n"Q,A', "a.csv")):
            with self.subTest(filename=filename, size=len(content)), self.assertRaises(ValueError):
                importer.parse_table(content, filename)
        too_many = csv_bytes(["question", "solution"], [[str(i), "A"] for i in range(5001)])
        with self.assertRaisesRegex(ValueError, "5000"):
            prepare(too_many)

    def test_knowledge_documents_require_no_project_and_have_stable_ids(self):
        content = csv_bytes(["问题类型", "问题描述", "解决方案"], [["表面", "如何处理划痕？", "更换治具。"], ["表面", "如何处理划痕？", "更换治具。"]])
        first = importer.knowledge_documents(content, "原始.csv")
        second = importer.knowledge_documents(content, "重命名.csv")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["source_id"], first[0]["id"])
        self.assertEqual(first[0]["source_type"], "knowledge")
        self.assertIn("如何处理划痕？", first[0]["text"])
        self.assertIn("更换治具。", first[0]["text"])
        with self.assertRaisesRegex(ValueError, "第 2 行"):
            importer.knowledge_documents(csv_bytes(["question"], [["只有问题"]]), "bad.csv")

    def test_question_and_explicit_symptom_are_both_preserved(self):
        plan = prepare(csv_bytes(["问题描述", "问题现象", "解决方案"], [["设备检不出？", "光源闪烁", "检查供电"]]))
        self.assertIn("设备检不出？", plan["rows"][0]["record"]["symptom"])
        self.assertIn("光源闪烁", plan["rows"][0]["record"]["symptom"])

    def test_xlsx_expansion_bomb_is_rejected_before_openpyxl(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("oversized", b"0" * (importer.MAX_XLSX_UNCOMPRESSED_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "50 MB"):
            importer.parse_table(stream.getvalue(), "bomb.xlsx")


try:
    import openpyxl
except ImportError:
    openpyxl = None


@unittest.skipIf(openpyxl is None, "openpyxl is not installed")
class XlsxExperienceImportTests(unittest.TestCase):
    @staticmethod
    def workbook_bytes(rows):
        workbook = openpyxl.Workbook()
        for row in rows:
            workbook.active.append(row)
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()
        return stream.getvalue()

    def test_xlsx_question_sheet_and_excel_dates(self):
        from datetime import datetime
        content = self.workbook_bytes([["问题描述", "解决方案", "售后日期"], ["Q", "A", datetime(2026, 11, 6)]])
        plan = prepare(content, "经验.xlsx")
        self.assertFalse(plan["errors"])
        self.assertEqual(plan["rows"][0]["record"]["service_date"], "2026-11-06")

    def test_xlsx_formula_and_error_cells_are_rejected(self):
        for value in ("=1+1", "#DIV/0!"):
            with self.subTest(value=value):
                content = self.workbook_bytes([["问题描述", "解决方案"], ["Q", value]])
                with self.assertRaisesRegex(ValueError, "第 2 行"):
                    prepare(content, "经验.xlsx")

    def test_sparse_far_column_is_rejected(self):
        workbook = openpyxl.Workbook()
        workbook.active.append(["问题描述", "解决方案"])
        workbook.active.append(["Q", "A"])
        workbook.active["XFD2"] = "隐藏的额外数据"
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()
        with self.assertRaisesRegex(ValueError, "100 列"):
            prepare(stream.getvalue(), "经验.xlsx")


if __name__ == "__main__":
    unittest.main()
