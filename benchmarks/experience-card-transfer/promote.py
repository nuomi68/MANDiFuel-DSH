"""Verify the twenty source records and merge their method cards into the default corpus."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile

from materials import REPO, TRAIN, cards, save
from experience_rag import build_index, validate_corpus


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def promote(source, destination):
    # Re-extract from reviewed records rather than trusting the exported candidate.
    with tempfile.TemporaryDirectory(prefix="mandifuel-card-review-") as tmp:
        plugin = Path(tmp)
        (plugin / "rag/experience/data").mkdir(parents=True)
        audit = cards(plugin)
        candidate_path = plugin / "rag/experience/data/reviewed_corpus.json"
        candidate = json.loads(candidate_path.read_text())
        if candidate != json.loads((source / "new_cards/plugin/rag/experience/data/reviewed_corpus.json").read_text()):
            raise ValueError("Candidate cards differ from the previously tested cards")
        if audit != json.loads((source / "card-audit.json").read_text()):
            raise ValueError("Source traces or submitted answers have changed since review")
    old_path = destination / "reviewed_corpus.json"
    corpus = json.loads(old_path.read_text())
    validate_corpus(corpus)
    old_parents = {p["id"]: p for p in corpus["parents"]}
    old_children = {c["id"]: c for c in corpus["children"]}
    for key in ("parents", "children"):
        known = {item["id"]: item for item in corpus[key]}
        for item in candidate[key]:
            if item["id"] in known:
                if item != known[item["id"]]:
                    raise ValueError(f"Conflicting existing card: {item['id']}")
            else:
                corpus[key].append(item)
    parents, children = validate_corpus(corpus)
    assert all(parents[k] == v for k, v in old_parents.items())
    assert all(children[k] == v for k, v in old_children.items())
    if (len(parents), len(children)) != (34, 79):
        raise ValueError("Unexpected merged corpus coverage")
    corpus["review"].update(
        reviewed_at=date.today().isoformat(), parent_count=len(parents), child_count=len(children),
        pass_count=sum(c["review_status"] == "pass" for c in children.values()),
        troubleshooting_only_count=sum(c["review_status"] == "troubleshooting_only" for c in children.values()),
        case_example_count=sum(c.get("role") == "case_example" for c in children.values()),
        method_card_review="data/card_transfer_review.json",
    )
    decisions_path = destination / "review_decisions.json"
    decisions = json.loads(decisions_path.read_text())
    known = {p["id"] for p in decisions["cards"]}
    for parent, child, evidence in zip(candidate["parents"], candidate["children"], audit):
        identifier = parent["id"].split(":", 1)[1]
        if identifier not in known:
            decisions["cards"].append(dict(id=identifier, runtime_scope=parent["context"],
                decisions=[dict(verdict="pass", reason=child["review_reason"], runtime_text=child["text"])],
                evidence=evidence))
    decisions["reviewed_at"] = date.today().isoformat()
    save(old_path, corpus)
    save(decisions_path, decisions)
    review = dict(schema_version="mandifuel-card-transfer-review.v1", source_run=TRAIN.name,
        transfer_run=source.name, candidate_sha256=hashlib.sha256(candidate_path_bytes(candidate)).hexdigest(),
        policy="保留旧卡全部内容与审核边界；新增20张条件化方法卡，不录入历史答案数值。原题复跑单独报告。",
        cards=audit)
    save(destination / "card_transfer_review.json", review)
    build_index(old_path, destination / "experience_index.json")
    print(json.dumps(dict(parents=len(parents), children=len(children),
        normal_solve_children=sum(c["review_status"] == "pass" and c.get("role") != "case_example" for c in children.values()),
        corpus_sha256=digest(old_path)), ensure_ascii=False))


def candidate_path_bytes(candidate):
    return (json.dumps(candidate, ensure_ascii=False, indent=2) + "\n").encode()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=REPO / "runs/card-transfer-20261119-01")
    parser.add_argument("--data-dir", type=Path, default=REPO / "rag/experience/data")
    args = parser.parse_args()
    promote(args.source.resolve(), args.data_dir.resolve())
