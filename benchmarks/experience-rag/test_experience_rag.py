#!/usr/bin/env python3
"""Behavioral tests for retrieval safety, source filters and dual-RAG isolation."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2] / "rag" / "experience"
sys.path.insert(0, str(ROOT))
import dual_query  # noqa: E402
import experience_rag as exp  # noqa: E402


class ExperienceRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="experience-rag-test-")
        cls.index = Path(cls.temp.name) / "index.json"
        exp.build_index(exp.DEFAULT_CORPUS, cls.index)
        cls.corpus = exp._read(exp.DEFAULT_CORPUS)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def query(self, text: str, **kwargs):
        return exp.query_experience(text, index_path=self.index, **kwargs)

    def test_review_completeness_and_no_unreviewed_source(self):
        parents, children = exp.validate_corpus(self.corpus)
        self.assertEqual((len(parents), len(children)), (14, 59))
        self.assertEqual(sum(c["review_status"] == "pass" for c in children.values()), 46)
        self.assertEqual(sum(c["review_status"] == "troubleshooting_only" for c in children.values()), 13)
        self.assertEqual(sum(c.get("role") == "case_example" for c in children.values()), 3)

    def test_shipped_index_matches_clean_rebuild(self):
        self.assertEqual(exp.DEFAULT_INDEX.read_bytes(), self.index.read_bytes())

    def test_neighbor_does_not_quote_comparison_with_only_one_source(self):
        primary = "knowledge:K14_M01:02"
        text = next(c["text"] for c in self.corpus["children"] if c["id"] == primary)
        hits = self.query(text, include_case_examples=True, adjacent=2)["results"]
        row = next(hit for hit in hits if hit["child"]["id"] == primary)
        ids = {c["id"] for c in row["adjacent_children"]}
        self.assertIn("knowledge:K14_M01:03", ids)
        self.assertNotIn("knowledge:K14_M01:04", ids)

    def test_chinese_query_finds_cold_gap(self):
        result = self.query("燃料棒冷态直径与冷态间隙如何同步", limit=10)
        self.assertTrue(any(x["child"]["parent_id"] == "knowledge:K01_P02" for x in result["results"]))
        child = next(x["child"] for x in result["results"]
                     if x["child"]["id"] == "knowledge:K01_P02:02")
        self.assertIn("GapCold = 2*(r_clad_in - r_fuel)", child["text"])
        self.assertEqual(result["network_requests"], 0)

    def test_specific_identifier_is_not_fabricated_by_chinese_alias(self):
        result = self.query("fuelRodGap", limit=3)
        self.assertTrue(result["results"])
        self.assertEqual(result["results"][0]["child"]["id"],
                         "knowledge:K08_C08_RECOVERY:02")
        reviewed_text = result["results"][0]["child"]["text"]
        self.assertIn("mechanicsSolver 的值为 constant", reviewed_text)
        self.assertIn("gapGas 模型为 FRAPCON", reviewed_text)

    def test_tangential_average_is_not_confused_with_spherical_symmetry(self):
        result = self.query("球坐标 应力张量 投影 径向应力", limit=10)
        child = next(x["child"] for x in result["results"]
                     if x["child"]["id"] == "knowledge:K13_G02:02")
        self.assertIn("平均公式本身不要求剪切为零", child["text"])
        self.assertIn("确认两切向正应力相等", child["text"])

    def test_default_result_never_leaks_diagnostic_or_raw_parent_answers(self):
        result = self.query("燃料间隙 fuelRodGap 气体模型 mechanicsSolver none", limit=20)
        self.assertTrue(result["results"])
        for item in result["results"]:
            self.assertEqual(item["score"], item["child"]["score"])
            self.assertNotIn("answers", item["parent_context"])
            self.assertNotIn("text", item["parent_context"])
            for child in [item["child"]] + item["adjacent_children"]:
                self.assertEqual(child["review_status"], "pass")
                self.assertNotEqual(child["role"], "case_example")
                self.assertNotIn("original_reviewed_text", child)
                self.assertTrue(all(g["task_status"] in {"completed", "prepared"}
                                    for g in child["source_groups"]))

    def test_incomplete_sources_only_in_explicit_troubleshooting(self):
        regular = self.query("fuelRodGap gapGas none", arm="skill",
                             task_status="incomplete", purpose="solve", limit=20)
        self.assertEqual(regular["candidate_count"], 0)
        diagnostic = self.query(
            "fuelRodGap gapGas none 初始化失败",
            purpose="troubleshoot", review_status="troubleshooting_only",
            arm="skill", task_status="incomplete",
            source_run="generalization-pairs-20261114-01", limit=20,
        )
        self.assertTrue(any(x["child"]["id"] == "knowledge:K07_C08_LIMITED:02"
                            for x in diagnostic["results"]))
        for item in diagnostic["results"]:
            for child in [item["child"]] + item["adjacent_children"]:
                self.assertEqual(child["review_status"], "troubleshooting_only")
                for group in child["source_groups"]:
                    self.assertEqual(group["arm"], "skill")
                    self.assertEqual(group["task_status"], "incomplete")
                    self.assertEqual(group["run"], "generalization-pairs-20261114-01")

    def test_reject_diagnostic_filter_for_normal_solution(self):
        with self.assertRaises(exp.ExperienceError):
            self.query("燃料棒", purpose="solve", review_status="troubleshooting_only")

    def test_neighbors_share_filtered_source_group(self):
        result = self.query("冷态直径 gap cold 准备输入", arm="skill",
                            task_status="prepared", adjacent=2, limit=20)
        self.assertTrue(result["results"])
        for item in result["results"]:
            base_groups = {g["group_id"] for g in item["child"]["source_groups"]}
            for neighbor in item["adjacent_children"]:
                self.assertTrue(base_groups.intersection(
                    g["group_id"] for g in neighbor["source_groups"]
                ))
                self.assertTrue(all(g["arm"] == "skill" and g["task_status"] == "prepared"
                                    for g in neighbor["source_groups"]))

    def test_case_numbers_require_explicit_opt_in(self):
        query = "M01 30000 0.2459467 0.2460665 释放分数"
        normal = self.query(query, limit=20)
        self.assertFalse(any(x["child"]["role"] == "case_example" for x in normal["results"]))
        detailed = self.query(query, limit=20, include_case_examples=True)
        self.assertTrue(any(x["child"]["id"] == "knowledge:K14_M01:04"
                            for x in detailed["results"]))
        single_arm = self.query(query, limit=20, include_case_examples=True, arm="bare")
        self.assertFalse(any(x["child"]["id"] == "knowledge:K14_M01:04"
                             for x in single_arm["results"]))

    def test_no_match_returns_empty(self):
        self.assertEqual(self.query("zebraquantumzz nonexistentprotocolxyz")["candidate_count"], 0)

    def test_parent_context_is_expanded_only_after_child_match(self):
        corpus = json.loads(json.dumps(self.corpus, ensure_ascii=False))
        corpus["parents"][0]["context"] += " parentonlycontextzz"
        with tempfile.TemporaryDirectory() as tmp:
            corpus_file = Path(tmp) / "corpus.json"
            index_file = Path(tmp) / "index.json"
            corpus_file.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
            exp.build_index(corpus_file, index_file)
            result = exp.query_experience("parentonlycontextzz", corpus_path=corpus_file,
                                          index_path=index_file)
            self.assertEqual(result["candidate_count"], 0)

    def test_stale_index_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus.json"
            index = Path(tmp) / "index.json"
            shutil.copyfile(exp.DEFAULT_CORPUS, corpus)
            exp.build_index(corpus, index)
            with corpus.open("ab") as f:
                f.write(b" ")
            with self.assertRaises(exp.ExperienceError):
                exp.query_experience("燃料间隙", corpus_path=corpus, index_path=index)

    def test_index_with_other_engine_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            exp.build_index(exp.DEFAULT_CORPUS, index_path)
            index = exp._read(index_path)
            index["engine_version"] = "old-engine"
            index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(exp.ExperienceError):
                exp.query_experience("fuelRodGap", index_path=index_path)

    def test_unfiltered_parent_answer_is_rejected(self):
        corpus = json.loads(json.dumps(self.corpus, ensure_ascii=False))
        corpus["parents"][0]["answers"] = [{"answer": "must not leak"}]
        with self.assertRaises(exp.ExperienceError):
            exp.validate_corpus(corpus)

    def test_failed_existing_rag_does_not_break_experience_result(self):
        result = dual_query.query_both("燃料棒冷态间隙 GapCold",
                                       case_query=Path(self.temp.name) / "not-installed.py")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["retrievers"]["case_rag"]["status"], "error")
        self.assertEqual(result["retrievers"]["experience_rag"]["status"], "ok")

    def test_slow_or_malformed_case_rag_preserves_experience_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "case_query.py"
            fake.write_text("import time\ntime.sleep(4)\n", encoding="utf-8")
            slow = dual_query.query_both("fuelRodGap", case_query=fake, timeout=1)
            self.assertEqual(slow["status"], "partial")
            self.assertEqual(slow["retrievers"]["case_rag"]["status"], "error")
            self.assertEqual(slow["retrievers"]["experience_rag"]["status"], "ok")
            fake.write_text("print('not json')\n", encoding="utf-8")
            malformed = dual_query.query_both("fuelRodGap", case_query=fake)
            self.assertEqual(malformed["status"], "partial")
            self.assertEqual(malformed["retrievers"]["case_rag"]["status"], "error")
            self.assertEqual(malformed["retrievers"]["experience_rag"]["status"], "ok")

    def test_failed_experience_rag_does_not_break_existing_case_result(self):
        case_query = ROOT.parent / "query.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shutil.copyfile(ROOT / "dual_query.py", tmp_path / "dual_query.py")
            shutil.copyfile(ROOT / "experience_rag.py", tmp_path / "experience_rag.py")
            proc = subprocess.run(
                [sys.executable, "-I", "-B", str(tmp_path / "dual_query.py"),
                 "--case-query", str(case_query), "--query", "hollow spherical shell pressure", "--compact"],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["retrievers"]["case_rag"]["status"], "ok")
            self.assertEqual(result["retrievers"]["experience_rag"]["status"], "error")

    def test_slow_experience_rag_preserves_case_result(self):
        case_query = ROOT.parent / "query.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shutil.copyfile(ROOT / "dual_query.py", tmp_path / "dual_query.py")
            (tmp_path / "experience_rag.py").write_text("import time\ntime.sleep(4)\n",
                                                         encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-I", "-B", str(tmp_path / "dual_query.py"),
                 "--case-query", str(case_query), "--query", "hollow spherical shell pressure",
                 "--timeout", "1", "--compact"],
                capture_output=True, text=True, encoding="utf-8", check=True, timeout=10,
            )
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["retrievers"]["case_rag"]["status"], "ok")
            self.assertEqual(result["retrievers"]["experience_rag"]["status"], "error")

    def test_existing_case_output_unchanged_through_dual_wrapper(self):
        case_query = ROOT.parent / "query.py"
        request = "hollow spherical shell pressure"
        direct = subprocess.run(
            [sys.executable, "-B", str(case_query), "--query", request, "--limit", "5", "--compact"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        )
        result = dual_query.query_both(request, case_query=case_query)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["retrievers"]["case_rag"]["output"], json.loads(direct.stdout))
        self.assertEqual(result["retrievers"]["experience_rag"]["status"], "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
