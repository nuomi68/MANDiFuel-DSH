"""Single read-only retrieval request for the DSH host. Python starts in isolated mode."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys

# Only the host's startup copy of these modules is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.experience.dual_query import dual_result
from rag.experience.experience_rag import query_experience
from rag.query import MAX_SEMANTIC_QUERY_CHARS, default_mode, query


def retrieve(operation, *args, **kwargs):
    try:
        return {"status": "ok", "output": operation(*args, **kwargs)}
    except (OSError, ValueError, RuntimeError) as error:
        return {"status": "error", "message": str(error)}


def joint_query(request):
    if not isinstance(request, dict):
        raise ValueError("检索请求须为 JSON 对象")
    text = request.get("query")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_SEMANTIC_QUERY_CHARS or "\0" in text:
        raise ValueError("检索短句须为 1–1200 字符")
    case_limit = request.get("case_limit", 5)
    experience_limit = request.get("experience_limit", 3)
    if any(type(n) is not int or not 1 <= n <= 10 for n in (case_limit, experience_limit)):
        raise ValueError("候选数量须为 1–10 的整数")
    labels = None
    if default_mode() == "local" and request.get("labels_json"):
        labels = json.loads(request["labels_json"])
    options = {key: request[key] for key in ("purpose", "arm", "source_run", "task_status",
                                             "review_status", "include_case_examples") if key in request}
    root = os.environ.get("MANDIFUEL_CASE_LIBRARY_ROOT")
    with ThreadPoolExecutor(max_workers=2) as pool:
        cases = pool.submit(retrieve, query, text, case_library_root=Path(root) if root else None,
                            limit=case_limit, labels=labels)
        experience = pool.submit(retrieve, query_experience, text, limit=experience_limit, **options)
    return dual_result(cases.result(), experience.result())


if __name__ == "__main__":
    try:
        result = joint_query(json.load(sys.stdin))
    except (TypeError, ValueError) as error:
        result = {"status": "error", "message": str(error)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
