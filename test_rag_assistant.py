"""Offline RAG checks: temporary data and a local fake model, no paid calls."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rag_assistant import RagAssistant


ADMIN = {"id": 1, "username": "admin", "role": "admin"}
EDITOR = {"id": 2, "username": "engineer", "role": "editor"}
DOCUMENTS = [
    {"id": "sale:1", "title": "相机触发后不拍照", "text": "现象：相机触发后没有图像。处理经验：先检查触发接线及电平，再检查光源和曝光。适用条件：设备已停机。",
     "source_type": "after_sales", "source_id": 1, "category": "fault_fix", "created_by": "engineer"},
    {"id": "kb:2", "title": "AI 训练显存不足", "text": "训练时报 CUDA out of memory，减小 batch_size，并关闭占用显卡的其他进程。",
     "source_type": "knowledge", "source_id": 2, "category": "ai_platform", "source_filename": "经验.csv"},
    {"id": "kb:3", "title": "检测数据导出", "text": "在软件批次管理中选择批次，点击数据导出，保存 CSV 记录。",
     "source_type": "knowledge", "source_id": 3, "category": "AOI_platform"},
]


class RagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {
            "AOI_RAG_API_KEY": "", "AOI_RAG_BASE_URL": "https://api.deepseek.com",
            "AOI_RAG_MODEL": "deepseek-chat", "AOI_RAG_LOCAL": "0",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.rag = RagAssistant(self.temp.name)
        self.rag.rebuild(DOCUMENTS)

    def test_chinese_and_english_retrieval_and_metadata(self):
        self.assertEqual(self.rag.retrieve("相机不拍照，触发线怎么检查？")[0]["id"], "sale:1")
        result = self.rag.retrieve("CUDA out of memory batch_size")
        self.assertEqual(result[0]["id"], "kb:2")
        self.assertEqual(result[0]["source_filename"], "经验.csv")
        self.assertEqual(self.rag.retrieve("相机")[0]["created_by"], "engineer")
        self.assertEqual(self.rag.retrieve("今天天气怎么样？"), [])

    def test_rebuild_persistence_removes_deleted_sources(self):
        original = self.rag.status()["version"]
        self.rag.rebuild(DOCUMENTS[1:])
        reloaded = RagAssistant(self.temp.name)
        self.assertNotEqual(original, reloaded.status()["version"])
        self.assertEqual(reloaded.status()["documents"], 2)
        self.assertFalse(any(source["id"] == "sale:1" for source in reloaded.retrieve("相机触发不拍照")))
        self.assertEqual(reloaded.retrieve("显存不足")[0]["id"], "kb:2")

    def test_failed_rebuild_preserves_previous_snapshot(self):
        version = self.rag.status()["version"]
        with self.assertRaises(ValueError):
            self.rag.rebuild(DOCUMENTS + [DOCUMENTS[0]])
        with patch("rag_assistant.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.rag.rebuild([])
        self.assertEqual(self.rag.status()["version"], version)
        self.assertEqual(RagAssistant(self.temp.name).status()["version"], version)
        self.assertFalse(list(Path(self.temp.name, "rag").glob(".index-*.tmp")))

    def test_retrieval_only_honest_and_full_answer_persisted(self):
        with patch.object(self.rag, "_generate", side_effect=AssertionError("must stay local")):
            result = self.rag.chat(EDITOR, "相机不拍照怎么办")
        self.assertEqual(result["mode"], "retrieval_only")
        self.assertIn("未经大模型分析", result["warning"])
        self.assertIn("[1]", result["answer"])
        self.assertIn("触发接线", result["answer"])
        self.assertEqual(result["model"], "")
        saved = RagAssistant(self.temp.name).history(EDITOR, result["conversation_id"])["messages"][0]
        self.assertEqual(saved["answer"], result["answer"])
        self.assertEqual(saved["sources"], result["sources"])

    def test_no_evidence_does_not_call_provider(self):
        with patch.dict(os.environ, {"AOI_RAG_API_KEY": "unit-test-placeholder"}), \
                patch.object(self.rag, "_generate", side_effect=AssertionError("no evidence")):
            result = self.rag.chat(EDITOR, "今天天气怎么样")
        self.assertEqual(result["mode"], "insufficient_evidence")
        self.assertEqual(result["sources"], [])
        self.assertIn("没有足够依据", result["answer"])

    def test_conversations_and_feedback_owner_isolation(self):
        result = self.rag.chat(EDITOR, "相机不拍照")
        self.assertEqual(self.rag.history(ADMIN)["conversations"], [])
        for action in (
            lambda: self.rag.history(ADMIN, result["conversation_id"]),
            lambda: self.rag.chat(ADMIN, "继续", result["conversation_id"]),
            lambda: self.rag.feedback(ADMIN, result["question_id"], "up"),
        ):
            with self.assertRaises(PermissionError):
                action()
        self.rag.feedback(EDITOR, result["question_id"], "down", "这条经验不适用")
        self.rag.feedback(EDITOR, result["question_id"], "helpful", "已确认")
        row = self.rag.history(EDITOR, result["conversation_id"])["messages"][0]
        self.assertEqual(row["feedback"], {"rating": "helpful", "comment": "已确认"})
        self.assertEqual(self.rag.status()["documents"], 3, "feedback must not silently become knowledge")
        with self.assertRaises(PermissionError):
            self.rag.chat(None, "相机")

    def test_model_failure_is_explicit_and_retains_sources(self):
        key = "unit-test-placeholder"
        with patch.dict(os.environ, {"AOI_RAG_API_KEY": key}), \
                patch.object(self.rag, "_generate", side_effect=RuntimeError("模型服务返回 HTTP 503")):
            result = self.rag.chat(EDITOR, "相机不拍照")
        self.assertEqual(result["mode"], "service_error")
        self.assertIn("503", result["warning"])
        self.assertGreater(len(result["sources"]), 0)
        self.assertNotIn(key, json.dumps(result, ensure_ascii=False))
        self.assertEqual(self.rag.history(EDITOR, result["conversation_id"])["messages"][0]["mode"], "service_error")

    def test_private_context_is_bounded_and_followup_resolves(self):
        captured = []
        def generate(messages):
            captured.append(messages)
            return "先检查触发接线，并确认停机条件。[1]"
        with patch.dict(os.environ, {"AOI_RAG_API_KEY": "unit-test-placeholder"}), \
                patch.object(self.rag, "_generate", side_effect=generate):
            first = self.rag.chat(EDITOR, "相机不拍照")
            for _ in range(4):
                latest = self.rag.chat(EDITOR, "相机触发怎么检查", first["conversation_id"])
            followup = self.rag.chat(EDITOR, "具体如何处理？", first["conversation_id"])
            unrelated = self.rag.chat(EDITOR, "今天北京天气？", first["conversation_id"])
        self.assertEqual(latest["mode"], "model")
        self.assertEqual(followup["mode"], "model")
        self.assertEqual(len(captured[-1]), 8, "system + last 6 messages + current question")
        self.assertEqual(unrelated["mode"], "insufficient_evidence")

    def test_configuration_is_secret_free_and_local_is_loopback_only(self):
        with patch.dict(os.environ, {"AOI_RAG_API_KEY": "unit-test-secret"}):
            status = self.rag.status()
        self.assertTrue(status["configured"])
        self.assertEqual(status["provider"], "deepseek")
        self.assertNotIn("unit-test-secret", json.dumps(status))
        self.assertNotIn(self.temp.name, json.dumps(status))
        for address, local in (("http://example.com/v1", "1"), ("http://127.0.0.1:8000/v1", "0"),
                               ("https://user:secret@example.com/v1", "0"), ("http://[invalid", "1")):
            with patch.dict(os.environ, {"AOI_RAG_BASE_URL": address, "AOI_RAG_LOCAL": local}):
                self.assertFalse(self.rag.status()["configured"])
                self.assertTrue(self.rag.status()["warning"])
        with patch.dict(os.environ, {"AOI_RAG_BASE_URL": "http://127.0.0.1:8000/v1", "AOI_RAG_LOCAL": "1"}):
            self.assertTrue(self.rag.status()["configured"])

    def test_openai_compatible_transport_request_and_response(self):
        captured = []
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit):
                return json.dumps({"choices": [{"message": {"content": "检查触发接线和电平。[1]"}}]}, ensure_ascii=False).encode()
        class Transport:
            def open(self, request, timeout):
                captured.append((request.full_url, json.loads(request.data), request.get_header("Authorization"), timeout))
                return Response()
        # Mock only network I/O; exercise real payload construction and parsing.
        with patch.dict(os.environ, {"AOI_RAG_LOCAL": "1", "AOI_RAG_MODEL": "local-model",
                "AOI_RAG_BASE_URL": "http://127.0.0.1:11434/v1"}), \
                patch("rag_assistant.urllib.request.build_opener", return_value=Transport()):
            result = self.rag.chat(EDITOR, "相机触发不拍照")
        self.assertEqual(result["mode"], "model")
        self.assertEqual(result["model"], "local-model")
        self.assertEqual(captured[0][0], "http://127.0.0.1:11434/v1/chat/completions")
        self.assertIsNone(captured[0][2], "explicit local mode needs no API credential")
        self.assertEqual(captured[0][3], 60)
        self.assertFalse(captured[0][1]["stream"])
        self.assertIn("[1]", captured[0][1]["messages"][-1]["content"])
        self.assertEqual(self.rag.history(EDITOR, result["conversation_id"])["messages"][0]["answer"], result["answer"])
        with patch.dict(os.environ, {"AOI_RAG_API_KEY": "unit-test-placeholder"}), \
                patch("rag_assistant.urllib.request.build_opener", return_value=Transport()):
            self.rag.chat(EDITOR, "相机触发不拍照")
        self.assertEqual(captured[-1][0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured[-1][2], "Bearer unit-test-placeholder")

    def test_corrupt_index_reports_recovery_without_losing_chat(self):
        result = self.rag.chat(EDITOR, "相机触发")
        Path(self.temp.name, "rag", "index.json").write_text("broken index", encoding="utf-8")
        reloaded = RagAssistant(self.temp.name)
        self.assertIn("重新同步", reloaded.status()["warning"])
        self.assertEqual(reloaded.history(EDITOR, result["conversation_id"])["messages"][0]["answer"], result["answer"])
        reloaded.rebuild(DOCUMENTS)
        self.assertEqual(reloaded.status()["documents"], 3)
        self.assertNotIn("重新同步", reloaded.status()["warning"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
