"""Exercise production retrieval entry points with deterministic HTTP provider responses."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rag.query import query, QueryError

REQUEST = "空心球壳内外受压，提取径向位移和环向应力"
REWRITE = "radial displacement and hoop stress of a pressurized hollow spherical shell"


class SemanticRetrievalTests(unittest.TestCase):
    def setUp(self):
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.mapping = {"mapped_labels": {"geometry": "1D_spherical"},
                        "confidence": {"geometry": 1}, "query_rewrite_for_embedding": REWRITE}
        records = json.loads((ROOT / "rag/index/description_embeddings.json").read_text())["records"]
        self.vector = next(r["embedding"] for r in records if r["card_path"].endswith("/hollowsphere_1D"))
        self.requests = []
        fixture = self

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.requests.append((self.path, payload))
                if self.path == "/chat/completions":
                    data = {"choices": [{"message": {"content": json.dumps(fixture.mapping)}}]}
                elif self.path == "/embeddings":
                    data = {"data": [{"index": 0, "embedding": fixture.vector}]}
                else:
                    self.send_error(404)
                    return
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        env = {"MANDIFUEL_RAG_CACHE_DIR": cache.name, "NO_PROXY": "127.0.0.1"}
        for role in ("MAPPING", "EMBEDDING"):
            env["MANDIFUEL_RAG_" + role + "_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
            env["MANDIFUEL_RAG_" + role + "_API_KEY_ENV"] = "TEST_PROVIDER_KEY"
        env["TEST_PROVIDER_KEY"] = "fixture"
        self.enterContext(patch.dict(os.environ, env))
        for key in ("MANDIFUEL_TASK_OFFLINE", "DSH_MANDIFUEL_TASK_OFFLINE", "MANDIFUEL_RAG_MODE"):
            os.environ.pop(key, None)

    def host_query(self, **arguments):
        run = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "rag/host_retrieval.py")],
                             input=json.dumps({"query": REQUEST, **arguments}), text=True, capture_output=True, check=True)
        return json.loads(run.stdout)

    def test_host_default_fuses_both_scores_and_cache_replays_without_requests(self):
        joint = self.host_query()
        self.assertEqual(joint["status"], "ok")
        case = joint["retrievers"]["case_rag"]["output"]
        self.assertEqual(case["mode"], "semantic")
        self.assertTrue(case["fusion"]["embedding_used"])
        self.assertTrue(joint["retrievers"]["experience_rag"]["output"]["results"])
        self.assertTrue(case["candidates"][0]["card_path"].endswith("/hollowsphere_1D"))
        self.assertEqual(case["query_mapping"]["mapped_labels"]["geometry"], "1D_spherical")
        self.assertEqual(case["provider_telemetry"]["network_requests"], 2)
        for row in case["candidates"]:
            scores = row["score_components"]
            self.assertAlmostEqual(row["score"], .35 * scores["embedding"] + .65 * scores["taxonomy"], delta=2e-6)
        self.assertEqual([p for p, _ in self.requests], ["/chat/completions", "/embeddings"])
        self.assertIn(REQUEST, self.requests[0][1]["messages"][1]["content"])
        self.assertEqual(self.requests[1][1]["input"], [REWRITE])

        overridden = query(REQUEST, labels={"driving_condition": "constant_pressure"})
        self.assertEqual(overridden["query_mapping"]["explicit_labels"]["driving_condition"], ["constant_pressure"])
        replay = self.host_query()["retrievers"]["case_rag"]["output"]
        self.assertEqual(replay["candidates"], case["candidates"])
        self.assertEqual(replay["query_mapping"], case["query_mapping"])
        self.assertEqual(replay["provider_telemetry"]["network_requests"], 0)
        self.assertEqual(len(self.requests), 2)

    def test_invalid_embedding_preserves_experience_and_retries_only_embedding(self):
        self.vector[0] = float("nan")
        joint = self.host_query()
        self.assertEqual(joint["status"], "partial")
        self.assertEqual(joint["retrievers"]["case_rag"]["status"], "error")
        self.assertTrue(joint["retrievers"]["experience_rag"]["output"]["results"])
        self.vector[0] = 0.1
        case = self.host_query()["retrievers"]["case_rag"]["output"]
        self.assertEqual(case["provider_telemetry"]["network_requests"], 1)
        self.assertEqual([p for p, _ in self.requests].count("/chat/completions"), 1)

    def test_missing_rewrite_does_not_forward_original_request_to_embedding(self):
        self.mapping.pop("query_rewrite_for_embedding")
        joint = self.host_query()
        self.assertEqual(joint["status"], "partial")
        self.assertEqual([p for p, _ in self.requests], ["/chat/completions"])

    def test_offline_and_explicit_local_paths_make_no_provider_calls(self):
        with patch.dict(os.environ, {"MANDIFUEL_TASK_OFFLINE": "1", "MANDIFUEL_RAG_MODE": "semantic"}):
            self.assertEqual(query("shell pressure")["mode"], "local")
            with self.assertRaisesRegex(QueryError, "offline"):
                query(REQUEST, mode="semantic")
        with patch.dict(os.environ, {"MANDIFUEL_RAG_MODE": "local"}):
            local = self.host_query(labels_json='{"geometry":"1D_spherical"}')["retrievers"]["case_rag"]["output"]
            self.assertEqual(local["mode"], "local")
            self.assertEqual(local["query_mapping"]["mapped_labels"]["geometry"], ["1D_spherical"])
        with self.assertRaises(QueryError):
            query("a" * 1201)
        self.assertFalse(self.requests)


if __name__ == "__main__":
    unittest.main()
