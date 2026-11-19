#!/usr/bin/env python3
"""Broader retrieval, source isolation and failure-handling checks; no solver calls."""
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2] / "rag" / "experience"
sys.path.insert(0, str(ROOT))
import dual_query  # noqa: E402
import experience_rag as exp  # noqa: E402


def check_result(result: dict, parents: dict, children: dict, *, purpose: str,
                 arm: str | None, task_status: str | None,
                 review_status: str | None, adjacent: int) -> int:
    inspected = 0
    for row in result["results"]:
        primary = row["child"]
        base = children[primary["id"]]
        parent = row["parent_context"]
        assert parent["id"] == base["parent_id"]
        assert parent["context"] == parents[parent["id"]]["context"]
        assert not {"answers", "question", "text"}.intersection(parent)
        groups = {g["group_id"] for g in primary["source_groups"]}
        for child in [primary, *row["adjacent_children"]]:
            inspected += 1
            original = children[child["id"]]
            assert child["parent_id"] == parent["id"]
            assert child["text"] == original["text"]
            assert "original_reviewed_text" not in child
            assert child["role"] != "case_example"
            assert child["review_status"] == original["review_status"]
            if purpose == "solve":
                assert child["review_status"] == "pass"
            if review_status in {"pass", "troubleshooting_only"}:
                assert child["review_status"] == review_status
            assert child["source_groups"]
            for group in child["source_groups"]:
                assert any(group["group_id"] == origin["group_id"]
                           for origin in original["source_groups"])
                assert arm is None or group["arm"] == arm
                assert task_status is None or group["task_status"] == task_status
                assert purpose != "solve" or group["task_status"] in {"completed", "prepared"}
            if child is not primary:
                assert 0 < abs(original["position"] - base["position"]) <= adjacent
                assert groups.intersection(g["group_id"] for g in child["source_groups"])
    return inspected


def main() -> int:
    parents, children = exp.validate_corpus(exp._read(exp.DEFAULT_CORPUS))
    queries = ("fuelRodGap gapGas", "燃料冷态直径 GapCold", "coolantPressureList", "Cs 扩散库存")
    checks = inspected = 0
    for query, purpose, arm, status, adjacent in itertools.product(
        queries, ("solve", "troubleshoot"), (None, "bare", "skill"),
        (None, "completed", "prepared", "incomplete"), (0, 1, 2)
    ):
        reviews = (None, "pass", "all") if purpose == "solve" else (
            None, "pass", "troubleshooting_only"
        )
        for review in reviews:
            result = exp.query_experience(query, purpose=purpose, arm=arm,
                                          task_status=status, review_status=review,
                                          adjacent=adjacent, limit=5)
            inspected += check_result(result, parents, children, purpose=purpose, arm=arm,
                                      task_status=status, review_status=review, adjacent=adjacent)
            if purpose == "solve" and status == "incomplete":
                assert result["results"] == []
            checks += 1
    print(f"PASS filter_matrix: {checks} queries, {inspected} returned child/adjacent records checked")

    for child in children.values():
        purpose = "solve" if child["review_status"] == "pass" else "troubleshoot"
        result = exp.query_experience(child["text"], purpose=purpose,
                                      review_status=child["review_status"], limit=20,
                                      adjacent=0, include_case_examples=True)
        assert child["id"] in {row["child"]["id"] for row in result["results"]}, child["id"]
    print(f"PASS reviewed_child_discoverability: {len(children)}/{len(children)} exact-text queries")

    for query in ("nonsensequasarzz", "🍋", "", "x" * 8001, "hello\0world"):
        try:
            result = exp.query_experience(query)
        except exp.ExperienceError:
            assert not query or len(query) > 8000 or "\0" in query
        else:
            assert not result["results"], query
    unknown = exp.query_experience("fuelRodGap", purpose="troubleshoot",
                                   source_run="nonexistent-run-xyz")
    assert not unknown["results"]
    print("PASS invalid_empty_and_unknown_sources")

    baseline = exp.query_experience("燃料棒 冷态间隙 GapCold", limit=5)
    with ThreadPoolExecutor(max_workers=8) as pool:
        copies = list(pool.map(lambda _: exp.query_experience("燃料棒 冷态间隙 GapCold", limit=5),
                               range(40)))
    assert all(item == baseline for item in copies)
    print("PASS concurrency_and_repeatability: 40 simultaneous identical queries")

    with tempfile.TemporaryDirectory(prefix="experience-query-input-") as tmp:
        tmp_path = Path(tmp)
        marker = tmp_path / "must-not-exist"
        request = f"fuelRodGap; touch {marker}"
        result = dual_query.query_both(request)
        assert result["retrievers"]["case_rag"]["status"] == "ok"
        assert result["retrievers"]["experience_rag"]["status"] == "ok"
        assert not marker.exists(), "Query text was executed as a shell command"
        query_file = tmp_path / "query.txt"
        query_file.write_text("冷态间隙 GapCold\n", encoding="utf-8")
        proc = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "experience_rag.py"),
                               "query", "--query-file", str(query_file), "--compact"],
                              capture_output=True, text=True, encoding="utf-8", check=True)
        assert json.loads(proc.stdout)["status"] == "ok"
    print("PASS query_file_and_literal_shell_metacharacters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
