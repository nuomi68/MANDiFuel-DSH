#!/usr/bin/env python3
"""Offline reviewed child-chunk retrieval with filtered parent expansion."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = ROOT / "data" / "reviewed_corpus.json"
DEFAULT_INDEX = ROOT / "data" / "experience_index.json"
SCHEMA = "mandifuel-experience-rag.v1"
INDEX_SCHEMA = "mandifuel-experience-index.v1"
ENGINE_VERSION = "child-bm25-v5"

# Small, transparent bilingual vocabulary; it does not invoke a model or network.
ALIASES = {
    "冷态间隙": "GapCold cold gap",
    "直径间隙": "GapCold diametral gap",
    "燃料直径": "DiamCold fuel diameter",
    "续算": "restart continuation",
    "重启": "restart continuation",
    "交接": "checkpoint handover",
    "腐蚀": "oxidation corrosion oxideThickness",
    "氧化": "oxideThickness corrosion",
    "气隙": "gap",
    "热流": "heat flux conservation",
    "功率": "power lhgr",
    "球壳": "hollow spherical shell",
    "圆筒": "cylinder cylindrical",
    "蠕变": "creep epsilonCreep",
    "裂变产物": "fission products transport",
    "铯": "Cs cesium",
    "扩散": "diffusion FpDiffusion diffCs",
    "材料区": "cellZone zone",
    "耦合": "coupled interface",
    "报错": "error failure",
    "异常": "error failure",
    "超时": "timeout",
    "未完成": "incomplete",
    "求解": "solve solver",
    "提取": "extract",
    "cold gap": "冷态间隙 GapCold",
    "cladding oxidation": "包壳 氧化 腐蚀 oxideThickness",
    "oxide thickness": "氧化层厚度 oxideThickness",
    "heat flux": "热流 通量",
    "spherical shell": "球壳 球坐标",
    "stress projection": "应力 张量 投影",
    "fuel creep": "燃料 蠕变 epsilonCreep",
    "restart": "续算 交接 checkpoint",
    "cesium diffusion": "铯 扩散 Cs FpDiffusion",
    "天还是秒": "时间 单位 userTime 86400",
    "thermal resistance": "热阻",
    "cylindrical": "圆柱",
    "gas conduction": "气隙 热导",
    "continuation": "续算 交接",
    "checkpoint": "交接 状态",
    "zero power": "零功率",
    "table end point": "时间表 最后点",
    "cylinder": "圆筒 圆柱",
    "pressure": "压力",
    "interface": "界面",
    "cell values": "单元中心值",
    "annular gas": "圆柱 气隙 热导",
    "constant conductivity": "恒定 热导率",
    "程序成功": "退出码 正常终止标记 结果场",
    "spherical radial stress": "球坐标 径向应力",
    "cylindrical tensor": "柱坐标 张量",
}
STOP = {
    "的", "了", "和", "与", "是", "在", "为", "对", "以", "及", "将", "或",
    "本题", "本次", "需要", "必须", "要求", "当前", "相关", "实际", "根据",
    "两个", "一个", "结果", "情况", "问题", "条件", "以及", "进行", "使用",
    "任务", "是否", "如何", "这些", "可以", "应该", "先后", "保留", "检查",
    "the", "and", "for", "with", "from", "this", "that", "how", "what",
    "case", "offbeat", "dsh", "skill", "use", "using", "please", "model",
}
VALID_REVIEWS = {"pass", "troubleshooting_only"}
VALID_TASK_STATUSES = {"completed", "prepared", "incomplete"}


class ExperienceError(ValueError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ExperienceError(f"Expected JSON object: {path}")
    return value


def tokens(value: str, *, expand_aliases: bool = False) -> list[str]:
    expanded = value
    if expand_aliases:
        lowered = value.lower()
        for key, addition in ALIASES.items():
            if key.lower() in lowered:
                expanded += " " + addition
    result: list[str] = []
    pattern = r"[A-Za-z][A-Za-z0-9_]*|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]+"
    for match in re.finditer(pattern, expanded):
        word = match.group(0)
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            for size in (2, 3):
                result.extend(
                    part for i in range(len(word) - size + 1)
                    if (part := word[i:i + size]) not in STOP
                )
        else:
            whole = word.lower()
            if len(whole) >= 2 and whole not in STOP:
                result.append(whole)
            pieces = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", word).replace("_", " ").split()
            if len(pieces) > 1:
                result.extend(p.lower() for p in pieces if len(p) >= 2 and p.lower() not in STOP)
    return result


def validate_corpus(corpus: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    if corpus.get("schema_version") != "mandifuel-experience-corpus.v1":
        raise ExperienceError("Unsupported experience corpus schema")
    parents = corpus.get("parents")
    children = corpus.get("children")
    if not isinstance(parents, list) or not isinstance(children, list):
        raise ExperienceError("Corpus must contain parent and child arrays")
    parent_map: dict[str, dict] = {}
    child_map: dict[str, dict] = {}
    for parent in parents:
        pid = parent.get("id")
        if not isinstance(pid, str) or not pid or pid in parent_map:
            raise ExperienceError("Missing or duplicate parent id")
        if parent.get("record_type") != "parent" or parent.get("approved_for_rag") is not False:
            raise ExperienceError(f"Parent must be context-only: {pid}")
        if any(key in parent for key in ("answers", "question", "text")):
            raise ExperienceError(f"Unfiltered historical answer in parent: {pid}")
        if not isinstance(parent.get("context"), str) or not parent["context"].strip():
            raise ExperienceError(f"Missing parent context: {pid}")
        parent_map[pid] = parent
    for child in children:
        cid = child.get("id")
        if not isinstance(cid, str) or not cid or cid in child_map:
            raise ExperienceError("Missing or duplicate child id")
        if child.get("parent_id") not in parent_map or child.get("record_type") != "child":
            raise ExperienceError(f"Invalid child parent: {cid}")
        verdict = child.get("review_status")
        if verdict not in VALID_REVIEWS:
            raise ExperienceError(f"Unreviewed or invalid child: {cid}")
        if verdict == "pass" and child.get("approved_for_rag") is not True:
            raise ExperienceError(f"Passed child is not marked approved: {cid}")
        if verdict == "troubleshooting_only" and (
            child.get("approved_for_rag") is not False
            or child.get("diagnostic_eligible") is not True
        ):
            raise ExperienceError(f"Diagnostic child has unsafe approval: {cid}")
        if not isinstance(child.get("position"), int) or child["position"] < 1:
            raise ExperienceError(f"Invalid position: {cid}")
        if not isinstance(child.get("text"), str) or not child["text"].strip():
            raise ExperienceError(f"Missing reviewed child text: {cid}")
        groups = child.get("source_groups")
        if not isinstance(groups, list) or not groups:
            raise ExperienceError(f"Missing source groups: {cid}")
        for group in groups:
            if (
                not isinstance(group, dict)
                or group.get("arm") not in {"bare", "skill"}
                or group.get("task_status") not in VALID_TASK_STATUSES
                or not group.get("run")
                or not group.get("group_id")
            ):
                raise ExperienceError(f"Invalid source group: {cid}")
        child_map[cid] = child
    positions: set[tuple[str, int]] = set()
    for child in child_map.values():
        position = (child["parent_id"], child["position"])
        if position in positions:
            raise ExperienceError(f"Duplicate sibling position: {position}")
        positions.add(position)
    return parent_map, child_map


def build_index(corpus_path: Path = DEFAULT_CORPUS, index_path: Path = DEFAULT_INDEX) -> dict:
    corpus = _read(corpus_path)
    parents, children = validate_corpus(corpus)
    records = []
    doc_frequency: Counter[str] = Counter()
    for cid, child in sorted(children.items()):
        # Rank the short reviewed child itself; expand its parent only after a hit.
        text = " ".join((child.get("kind", ""), child["text"]))
        frequencies = Counter(tokens(text))
        doc_frequency.update(frequencies.keys())
        records.append({"id": cid, "length": sum(frequencies.values()), "terms": dict(frequencies)})
    index = {
        "schema_version": INDEX_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "corpus_sha256": _sha(corpus_path),
        "document_count": len(records),
        "average_length": sum(r["length"] for r in records) / max(1, len(records)),
        "document_frequency": dict(doc_frequency),
        "records": records,
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd, temp = tempfile.mkstemp(prefix=".experience-index-", dir=index_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temp, index_path)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise
    return {"status": "ok", "index": str(index_path), "documents": len(records),
            "parents": len(parents), "corpus_sha256": index["corpus_sha256"]}


def _filter_groups(child: dict, *, arm: str | None, task_status: str | None,
                   source_run: str | None, purpose: str) -> list[dict]:
    result = []
    for group in child["source_groups"]:
        if arm and group["arm"] != arm:
            continue
        if task_status and group["task_status"] != task_status:
            continue
        if source_run and group["run"] != source_run:
            continue
        # A failed source is useful for diagnostics but never for a normal solution.
        if purpose == "solve" and group["task_status"] not in {"completed", "prepared"}:
            continue
        result.append(group)
    # Historical numeric examples may compare arms or runs in one sentence.
    # Do not return a comparison when a filter would hide some of its sources.
    if child.get("role") == "case_example" and len(result) != len(child["source_groups"]):
        return []
    return result


def _allowed(child: dict, *, purpose: str, review_status: str,
             include_case_examples: bool) -> bool:
    if purpose == "solve" and child["review_status"] != "pass":
        return False
    if review_status != "all" and child["review_status"] != review_status:
        return False
    if child.get("role") == "case_example" and not include_case_examples:
        return False
    return True


def _public_group(group: dict) -> dict:
    return {key: group.get(key) for key in (
        "group_id", "run", "arm", "task_status", "session_status", "source_session"
    )}


def _public_child(child: dict, groups: list[dict], score: float | None = None) -> dict:
    result = {
        "id": child["id"],
        "parent_id": child["parent_id"],
        "kind": child.get("kind"),
        "text": child["text"],
        "review_status": child["review_status"],
        "review_reason": child.get("review_reason"),
        "role": child.get("role", "guidance"),
        "source_groups": [_public_group(g) for g in groups],
    }
    if score is not None:
        result["score"] = round(score, 6)
    return result


def query_experience(
    request: str, *, corpus_path: Path = DEFAULT_CORPUS, index_path: Path = DEFAULT_INDEX,
    purpose: str = "solve", limit: int = 5, arm: str | None = None,
    task_status: str | None = None, source_run: str | None = None,
    review_status: str | None = None, adjacent: int = 1,
    include_case_examples: bool = False,
) -> dict:
    if not isinstance(request, str) or not request.strip() or "\x00" in request or len(request) > 8000:
        raise ExperienceError("Query must contain 1–8000 characters without NUL")
    if purpose not in {"solve", "troubleshoot"} or not 1 <= limit <= 20 or not 0 <= adjacent <= 2:
        raise ExperienceError("Invalid purpose, result limit, or adjacent count")
    if arm not in {None, "bare", "skill"} or task_status not in VALID_TASK_STATUSES | {None}:
        raise ExperienceError("Invalid source group or task status")
    if review_status is None:
        review_status = "pass" if purpose == "solve" else "all"
    if review_status not in {"all", "pass", "troubleshooting_only"}:
        raise ExperienceError("Invalid review status filter")
    if purpose == "solve" and review_status == "troubleshooting_only":
        raise ExperienceError("Troubleshooting-only content requires purpose=troubleshoot")

    corpus = _read(corpus_path)
    parents, children = validate_corpus(corpus)
    index = _read(index_path)
    if (index.get("schema_version") != INDEX_SCHEMA
            or index.get("engine_version") != ENGINE_VERSION
            or index.get("corpus_sha256") != _sha(corpus_path)):
        raise ExperienceError("Experience index is missing, stale or belongs to another corpus; rebuild it")
    records = index.get("records")
    if not isinstance(records, list) or len(records) != len(children):
        raise ExperienceError("Experience index record count differs from corpus")
    indexed_ids = [r.get("id") for r in records if isinstance(r, dict)]
    if len(indexed_ids) != len(set(indexed_ids)) or set(indexed_ids) != set(children):
        raise ExperienceError("Experience index IDs do not match corpus")

    terms = set(tokens(request, expand_aliases=True))
    n_docs = max(1, index["document_count"])
    avg_length = max(float(index.get("average_length", 0)), 1.0)
    frequencies = index["document_frequency"]
    scored = []
    for record in records:
        child = children[record["id"]]
        if not _allowed(child, purpose=purpose, review_status=review_status,
                        include_case_examples=include_case_examples):
            continue
        groups = _filter_groups(child, arm=arm, task_status=task_status,
                                source_run=source_run, purpose=purpose)
        if not groups:
            continue
        score = 0.0
        for term in terms:
            count = record["terms"].get(term, 0)
            if count:
                doc_freq = frequencies.get(term, 0)
                idf = math.log(1 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))
                denom = count + 1.2 * (0.25 + 0.75 * record["length"] / avg_length)
                score += idf * count * 2.2 / denom
        if score > 0:
            scored.append((score, child, groups))
    scored.sort(key=lambda row: (-row[0], row[1]["id"]))

    by_parent: dict[str, dict[int, dict]] = {}
    for child in children.values():
        by_parent.setdefault(child["parent_id"], {})[child["position"]] = child
    results = []
    for score, child, groups in scored[:limit]:
        parent = parents[child["parent_id"]]
        matching_group_ids = {g["group_id"] for g in groups}
        neighbors = []
        for position in range(child["position"] - adjacent, child["position"] + adjacent + 1):
            if position == child["position"]:
                continue
            neighbor = by_parent.get(parent["id"], {}).get(position)
            if not neighbor or not _allowed(
                neighbor, purpose=purpose, review_status=review_status,
                include_case_examples=include_case_examples
            ):
                continue
            neighbor_groups = [
                g for g in _filter_groups(neighbor, arm=arm, task_status=task_status,
                                           source_run=source_run, purpose=purpose)
                if g["group_id"] in matching_group_ids
            ]
            if neighbor.get("role") == "case_example" and len(neighbor_groups) != len(neighbor["source_groups"]):
                continue
            if neighbor_groups:
                neighbors.append(_public_child(neighbor, neighbor_groups))
        results.append({
            "score": round(score, 6),
            "child": _public_child(child, groups, score),
            "parent_context": {
                "id": parent["id"], "question_parent_id": parent.get("question_parent_id"),
                "title": parent["title"], "context": parent["context"],
                "source_question_server": parent.get("source_question_server"),
            },
            "adjacent_children": neighbors,
        })
    return {
        "status": "ok", "interface": SCHEMA, "mode": "local_bm25",
        "query": request, "network_requests": 0,
        "filters": {
            "purpose": purpose, "review_status": review_status, "arm": arm,
            "task_status": task_status, "source_run": source_run,
            "adjacent": adjacent, "include_case_examples": include_case_examples,
        },
        "candidate_count": len(results), "results": results,
        "warnings": [
            "Scores are lexical relevance only, not proof of physical applicability.",
            "Historical examples are not current task inputs or answers.",
            "Check version, source model, geometry, boundary conditions and actual fields.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Build only the independent experience index")
    build.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    build.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    query = sub.add_parser("query", help="Search reviewed short child chunks")
    source = query.add_mutually_exclusive_group(required=True)
    source.add_argument("--query")
    source.add_argument("--query-file", type=Path)
    query.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    query.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    query.add_argument("--purpose", choices=("solve", "troubleshoot"), default="solve")
    query.add_argument("--limit", type=int, default=5)
    query.add_argument("--arm", choices=("bare", "skill"))
    query.add_argument("--task-status", choices=("completed", "prepared", "incomplete"))
    query.add_argument("--source-run")
    query.add_argument("--review-status", choices=("all", "pass", "troubleshooting_only"))
    query.add_argument("--adjacent", type=int, choices=(0, 1, 2), default=1)
    query.add_argument("--include-case-examples", action="store_true")
    query.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build_index(args.corpus, args.index)
        else:
            request = args.query_file.read_text(encoding="utf-8") if args.query_file else args.query
            result = query_experience(
                request, corpus_path=args.corpus, index_path=args.index, purpose=args.purpose,
                limit=args.limit, arm=args.arm, task_status=args.task_status,
                source_run=args.source_run, review_status=args.review_status,
                adjacent=args.adjacent, include_case_examples=args.include_case_examples,
            )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "interface": SCHEMA, "message": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False,
                     separators=(",", ":") if getattr(args, "compact", False) else None,
                     indent=None if getattr(args, "compact", False) else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
