#!/usr/bin/env python3
"""Query the existing case RAG and independent experience RAG concurrently."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
EXPERIENCE = ROOT / "experience_rag.py"
SCHEMA = "mandifuel-dual-rag.v1"


def default_case_query() -> Path:
    plugin_root = os.environ.get("MANDIFUEL_PLUGIN_ROOT")
    if plugin_root:
        return Path(plugin_root) / "rag" / "query.py"
    return ROOT.parent / "query.py"


def run_json(command: list[str], timeout: int) -> dict:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "message": str(exc)}
    raw = proc.stdout if proc.returncode == 0 else proc.stderr
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"status": "error", "exit_code": proc.returncode,
                "message": "Retriever returned non-JSON output"}
    if not isinstance(payload, dict):
        return {"status": "error", "exit_code": proc.returncode,
                "message": "Retriever returned a non-object JSON value"}
    if proc.returncode != 0 or payload.get("status") != "ok":
        return {"status": "error", "exit_code": proc.returncode,
                "message": str(payload.get("message", "Retriever failed"))}
    return {"status": "ok", "output": payload}


def query_both(
    request: str, *, case_query: Path | None = None, case_limit: int = 5,
    experience_limit: int = 5, purpose: str = "solve", arm: str | None = None,
    task_status: str | None = None, review_status: str | None = None,
    source_run: str | None = None, adjacent: int = 1,
    include_case_examples: bool = False, case_library_root: Path | None = None,
    labels_json: str | None = None, timeout: int = 250, case_mode: str | None = None,
) -> dict:
    if not isinstance(request, str) or not request.strip() or "\x00" in request or len(request) > 8000:
        raise ValueError("Query must contain 1–8000 characters without NUL")
    if not 1 <= case_limit <= 20 or not 1 <= experience_limit <= 20 or not 1 <= timeout <= 600:
        raise ValueError("Limits must be 1–20 and timeout 1–600 seconds")
    original = Path(case_query) if case_query else default_case_query()
    # The case CLI is invoked unchanged; no scores or corpus are merged.
    case_cmd = [sys.executable, "-B", str(original), f"--query={request}",
                "--limit", str(case_limit), "--compact"]
    if case_mode is not None:
        case_cmd.extend(("--mode", case_mode))
    if case_library_root:
        case_cmd.extend(("--case-library-root", str(case_library_root)))
    if labels_json:
        case_cmd.extend(("--labels-json", labels_json))
    experience_cmd = [
        sys.executable, "-I", "-B", str(EXPERIENCE), "query", f"--query={request}",
        "--purpose", purpose, "--limit", str(experience_limit), "--adjacent", str(adjacent),
        "--compact",
    ]
    for option, value in (("--arm", arm), ("--task-status", task_status),
                          ("--review-status", review_status), ("--source-run", source_run)):
        if value:
            experience_cmd.extend((option, value))
    if include_case_examples:
        experience_cmd.append("--include-case-examples")
    with ThreadPoolExecutor(max_workers=2) as pool:
        case_future = pool.submit(run_json, case_cmd, timeout)
        experience_future = pool.submit(run_json, experience_cmd, timeout)
        case_result = case_future.result()
        experience_result = experience_future.result()
    return dual_result(case_result, experience_result)


def dual_result(case_result: dict, experience_result: dict) -> dict:
    success_count = sum(x["status"] == "ok" for x in (case_result, experience_result))
    return {
        "status": "ok" if success_count == 2 else ("partial" if success_count == 1 else "error"),
        "interface": SCHEMA,
        "retrievers": {"case_rag": case_result, "experience_rag": experience_result},
        "notes": [
            "The two corpora, scores, indexes, and failures remain separate.",
            "Experience filters apply only to the experience RAG, not to case-card retrieval.",
            "Retrieved historical knowledge is a conditional reference, not the current answer.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--query")
    src.add_argument("--query-file", type=Path)
    parser.add_argument("--case-query", type=Path, help="Existing case RAG query.py path")
    parser.add_argument("--case-library-root", type=Path)
    parser.add_argument("--case-mode", choices=("local","semantic"))
    parser.add_argument("--labels-json")
    parser.add_argument("--case-limit", type=int, default=5)
    parser.add_argument("--experience-limit", type=int, default=5)
    parser.add_argument("--purpose", choices=("solve", "troubleshoot"), default="solve")
    parser.add_argument("--arm", choices=("bare", "skill"))
    parser.add_argument("--task-status", choices=("completed", "prepared", "incomplete"))
    parser.add_argument("--review-status", choices=("all", "pass", "troubleshooting_only"))
    parser.add_argument("--source-run")
    parser.add_argument("--adjacent", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--include-case-examples", action="store_true")
    parser.add_argument("--timeout", type=int, default=250)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = args.query_file.read_text(encoding="utf-8") if args.query_file else args.query
        result = query_both(
            request, case_query=args.case_query, case_limit=args.case_limit,
            experience_limit=args.experience_limit, purpose=args.purpose, arm=args.arm,
            task_status=args.task_status, review_status=args.review_status,
            source_run=args.source_run, adjacent=args.adjacent,
            include_case_examples=args.include_case_examples,
            case_library_root=args.case_library_root, labels_json=args.labels_json,
            timeout=args.timeout, case_mode=args.case_mode,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "interface": SCHEMA, "message": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False,
                     separators=(",", ":") if args.compact else None,
                     indent=None if args.compact else 2))
    return 0 if result["status"] in {"ok", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
