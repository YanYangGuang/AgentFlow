import os
import atexit
import tempfile
import uuid
import time
import unittest
from unittest.mock import patch

# Keep route tests isolated from the user's persistent SQLite database.
_test_db_path = os.path.join(tempfile.gettempdir(), f"agentflow_test_{uuid.uuid4().hex}.db")
os.environ["AGENTFLOW_DATABASE_URL"] = f"sqlite:///{_test_db_path.replace(os.sep, '/')}"

from fastapi.testclient import TestClient
from app.main import app
from app.db import engine

def _cleanup_test_database():
    engine.dispose()
    try:
        os.remove(_test_db_path)
    except FileNotFoundError:
        pass

atexit.register(_cleanup_test_database)


class LiveRouteGuardTests(unittest.TestCase):
    def test_disabled_and_enabled_without_key_are_distinguished(self):
        with patch.dict(os.environ, {
            "AGENTFLOW_LLM_API_KEY": "",
            "AGENTFLOW_ENABLE_LIVE_EXECUTION": "false",
        }, clear=False), TestClient(app) as client:
            settings = client.get("/api/v1/models").json()
            self.assertFalse(settings["live_enabled"])
            self.assertFalse(settings["configured"])
            self.assertEqual(client.post("/api/v1/models/test").json()["error"]["code"], "LIVE_EXECUTION_DISABLED")
            self.assertEqual(client.post("/api/v1/workflows/workflow_demo_default/runs", json={
                "title": "guard test", "mode": "live",
            }).json()["error"]["code"], "LIVE_EXECUTION_DISABLED")

        with patch.dict(os.environ, {
            "AGENTFLOW_LLM_API_KEY": "",
            "AGENTFLOW_ENABLE_LIVE_EXECUTION": "true",
        }, clear=False), TestClient(app) as client:
            settings = client.get("/api/v1/models").json()
            self.assertTrue(settings["live_enabled"])
            self.assertFalse(settings["configured"])
            self.assertEqual(client.post("/api/v1/models/test").status_code, 409)
            self.assertEqual(client.post("/api/v1/workflows/workflow_demo_default/runs", json={
                "title": "missing key test", "mode": "live",
            }).status_code, 409)

    def test_workflow_with_multiple_inputs_and_outputs_runs_and_aggregates_outputs(self):
        nodes = [
            {"id": "in_a", "type": "input", "label": "输入 A", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "in_b", "type": "input", "label": "输入 B", "position": {"x": 0, "y": 100}, "config": {}},
            {"id": "llm_a", "type": "llm", "label": "处理 A", "position": {"x": 200, "y": 0}, "config": {}},
            {"id": "tool_b", "type": "tool", "label": "处理 B", "position": {"x": 200, "y": 100}, "config": {"tool_name": "text_summary"}},
            {"id": "out_a", "type": "output", "label": "输出 A", "position": {"x": 400, "y": 0}, "config": {}},
            {"id": "out_b", "type": "output", "label": "输出 B", "position": {"x": 400, "y": 100}, "config": {}},
        ]
        edges = [
            {"id": "e1", "source": "in_a", "target": "llm_a"},
            {"id": "e2", "source": "llm_a", "target": "out_a"},
            {"id": "e3", "source": "in_b", "target": "tool_b"},
            {"id": "e4", "source": "tool_b", "target": "out_b"},
        ]
        with patch.dict(os.environ, {"AGENTFLOW_ENABLE_LIVE_EXECUTION": "false"}, clear=False), TestClient(app) as client:
            created = client.post("/api/v1/workflows", json={"name": "multi input output", "nodes": nodes, "edges": edges})
            self.assertEqual(created.status_code, 201)
            workflow_id = created.json()["id"]
            validation = client.post(f"/api/v1/workflows/{workflow_id}/validate", json={"nodes": nodes, "edges": edges})
            self.assertTrue(validation.json()["valid"], validation.json()["errors"])
            started = client.post(f"/api/v1/workflows/{workflow_id}/runs", json={"title": "aggregation check", "mode": "demo"})
            self.assertEqual(started.status_code, 202)
            run_id = started.json()["id"]
            record = None
            for _ in range(80):
                record = client.get(f"/api/v1/runs/{run_id}").json()
                if record["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.1)
            self.assertEqual(record["status"], "succeeded")
            self.assertIn("aggregation check", record["output_text"])

    def test_evaluation_batch_persists_scores_and_keeps_evaluation_tasks_out_of_task_center(self):
        with patch.dict(os.environ, {"AGENTFLOW_ENABLE_LIVE_EXECUTION": "false"}, clear=False), TestClient(app) as client:
            before = client.get("/api/v1/tasks").json()["total"]
            dataset = client.post("/api/v1/evaluations/datasets", json={
                "name": "本地评测用例", "description": "DAG 批量运行检查", "cases": [
                    {"title": "可匹配用例", "input": "请总结发布内容", "expected_contains": ["演示模型输出"]},
                    {"title": "不可匹配用例", "input": "请总结其他内容", "expected_contains": ["预期中不存在的短语"]},
                ],
            })
            self.assertEqual(dataset.status_code, 201, dataset.text)
            started = client.post(f"/api/v1/evaluations/datasets/{dataset.json()['id']}/runs", json={
                "workflow_id": "workflow_demo_default", "mode": "demo",
            })
            self.assertEqual(started.status_code, 202, started.text)
            evaluation_id = started.json()["id"]
            record = started.json()
            for _ in range(100):
                record = client.get(f"/api/v1/evaluations/{evaluation_id}").json()
                if record["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.1)
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["case_count"], 2)
            self.assertEqual(record["passed_count"], 1)
            self.assertEqual(record["score"], 0.5)
            self.assertEqual([item["passed"] for item in record["results"]], [True, False])
            self.assertTrue(all(item["run_id"] for item in record["results"]))
            self.assertEqual(client.get("/api/v1/tasks").json()["total"], before)

    def test_live_evaluation_respects_disabled_execution_guard(self):
        with patch.dict(os.environ, {"AGENTFLOW_ENABLE_LIVE_EXECUTION": "false"}, clear=False), TestClient(app) as client:
            dataset = client.post("/api/v1/evaluations/datasets", json={
                "name": "真实模式开关", "cases": [{"title": "用例", "input": "内容", "expected_contains": []}],
            }).json()
            response = client.post(f"/api/v1/evaluations/datasets/{dataset['id']}/runs", json={
                "workflow_id": "workflow_demo_default", "mode": "live",
            })
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "LIVE_EXECUTION_DISABLED")

    def test_global_runtime_mode_and_workflow_lifecycle_are_persistent(self):
        with patch.dict(os.environ, {"AGENTFLOW_ENABLE_LIVE_EXECUTION": "false"}, clear=False), TestClient(app) as client:
            runtime = client.get("/api/v1/system/runtime").json()
            self.assertEqual(runtime["mode"], "demo")
            blocked = client.put("/api/v1/system/runtime/mode", json={"mode": "live"})
            self.assertEqual(blocked.status_code, 403)
            saved = client.put("/api/v1/system/runtime/mode", json={"mode": "demo"})
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(client.get("/api/v1/system/runtime").json()["mode"], "demo")

            initial = client.get("/api/v1/workflows").json()
            original_default = next(item for item in initial if item["is_default"])
            nodes = [
                {"id": "input", "type": "input", "label": "输入", "position": {"x": 0, "y": 0}, "config": {}},
                {"id": "llm", "type": "llm", "label": "模型", "position": {"x": 100, "y": 0}, "config": {}},
                {"id": "output", "type": "output", "label": "输出", "position": {"x": 200, "y": 0}, "config": {}},
            ]
            edges = [{"id": "a", "source": "input", "target": "llm"}, {"id": "b", "source": "llm", "target": "output"}]
            created = client.post("/api/v1/workflows", json={"name": "可切换默认流程", "nodes": nodes, "edges": edges}).json()
            promoted = client.put(f"/api/v1/workflows/{created['id']}/default")
            self.assertEqual(promoted.status_code, 200)
            self.assertTrue(promoted.json()["is_default"])
            self.assertEqual(client.delete(f"/api/v1/workflows/{original_default['id']}").status_code, 204)
            self.assertNotIn(original_default["id"], [item["id"] for item in client.get("/api/v1/workflows").json()])
            protected = client.delete(f"/api/v1/workflows/{created['id']}")
            self.assertEqual(protected.status_code, 409)


if __name__ == "__main__":
    unittest.main()
