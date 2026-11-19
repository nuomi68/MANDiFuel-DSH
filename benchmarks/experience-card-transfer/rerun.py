"""Run the original twenty tasks once with merged cards or the twenty sourced cards only."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys

from materials import HERE, REPO, TRAIN, cards, pairs, save
import run as previous
from tasks import TASKS


def freeze_learned20(root):
    plugin = root / "frozen-plugin"
    shutil.copytree(TRAIN / "frozen-plugin", plugin)
    (plugin / "rag/experience/data/review_decisions.json").unlink()
    audit = cards(plugin)
    tested = REPO / "runs/card-transfer-20261119-01"
    if audit != json.loads((tested / "card-audit.json").read_text()):
        raise ValueError("Sourced records changed since the twenty cards were reviewed")
    data = plugin / "rag/experience/data"
    for name in ("reviewed_corpus.json", "experience_index.json"):
        if (data / name).read_bytes() != (tested / "new_cards/plugin/rag/experience/data" / name).read_bytes():
            raise ValueError(f"Previously reviewed card material differs: {name}")
    corpus = json.loads((data / "reviewed_corpus.json").read_text())
    expected = {f"knowledge:K{i}" for i in range(21, 41)}
    if ({p["id"] for p in corpus["parents"]} != expected
            or len(corpus["children"]) != 20
            or {p.name for p in data.iterdir()} != {"reviewed_corpus.json", "experience_index.json"}):
        raise ValueError("Unexpected old-library content in the learned-only snapshot")
    save(root / "card-audit.json", audit)
    full, current, baseline = [pairs.hashes(p) for p in (TRAIN / "frozen-plugin", plugin, TRAIN / "skills-without-experience")]
    changed = sorted(k for k in set(full) | set(current) if full.get(k) != current.get(k))
    if changed != sorted(["rag/experience/data/review_decisions.json",
                          "rag/experience/data/reviewed_corpus.json", "rag/experience/data/experience_index.json"]):
        raise ValueError(f"Unexpected changes to the historical software: {changed}")
    shared = {k for k in set(current) | set(baseline)
              if not k.startswith("rag/experience/") and k != "dsh/run-assistant-persona.md"}
    differences = [k for k in shared if current.get(k) != baseline.get(k)]
    if differences:
        raise ValueError(f"Shared Skill software differs from group B: {differences}")
    if not (plugin / "dsh/run-assistant-persona.md").read_text().startswith(
            (TRAIN / "skills-without-experience/dsh/run-assistant-persona.md").read_text()):
        raise ValueError("Group C persona no longer extends the frozen group B persona")
    return plugin, dict(shared_skill_identical_to_B=True, software_differences_from_frozen_rag=changed,
                        learned_parent_count=20, learned_child_count=20, old_library_included=False)


def launch(root, workers, timeout, library="merged_default"):
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    compatibility = {}
    if library == "learned20":
        plugin, compatibility = freeze_learned20(root)
        shutil.copytree(TRAIN / "calibration", root / "calibration")
        shutil.copyfile(TRAIN / "calibration.json", root / "calibration.json")
        save(root / "calibration-provenance.json", dict(source=str(TRAIN), reused=True,
            source_inputs_identical=True, files_sha256=pairs.hashes(root / "calibration"),
            calibration_sha256=pairs.sha(root / "calibration.json")))
    else:
        plugin = pairs.freeze(root)
        shutil.copyfile(REPO / "rag/experience/data/card_transfer_review.json",
                        plugin / "rag/experience/data/card_transfer_review.json")
        config = plugin / "configs/launcher.env"
        config.write_text("\n".join(line for line in config.read_text().splitlines()
                                    if not line.startswith("MANDIFUEL_RUNS_ROOT=")) + "\n")
        persona = plugin / "dsh/run-assistant-persona.md"
        persona.write_text(persona.read_text() +
            '\n本轮使用 source-case/ 随题给定的冻结输入或观测，遵循题目的求解或只读后处理范围。'
            '先用一次 python3 "$MANDIFUEL_PLUGIN_ROOT/rag/experience/experience_rag.py" query '
            '--query "本题物理问题与英文工程关键词" --limit 3 --compact。复用已有检索，'
            '只采纳与本题模型、单位和条件相符的经验。无适用项时继续独立计算。'
            '最终简述采用的经验ID与用途，或不适用的原因。本题数值必须来自本次输入和执行结果。\n')
    shutil.copytree(HERE, root / "definition/experience-card-transfer", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO / "benchmarks/three-arm-20", root / "definition/three-arm-20", ignore=shutil.ignore_patterns("__pycache__"))
    # The preparation helper's alternate plugin is unused for this single RAG arm.
    plugins = (plugin, plugin)
    tasks = list(TASKS)
    random.Random(20261119).shuffle(tasks)
    refs = json.loads((TRAIN / "reference.json").read_text())
    inputs = {}
    for task in TASKS:
        identifier = task[0]
        destination = root / identifier
        destination.mkdir()
        shutil.copytree(TRAIN / identifier / "source-case", destination / "source-case")
        for name in ("task.txt", "inputs.json"):
            shutil.copyfile(TRAIN / identifier / name, destination / name)
        if (destination / "task.txt").read_text() != previous.prompt(task) + "\n":
            raise ValueError(f"Task prompt drift: {identifier}")
        inputs[identifier] = pairs.hashes(destination / "source-case")
        if inputs[identifier] != pairs.hashes(TRAIN / identifier / "source-case"):
            raise ValueError(f"Input drift: {identifier}")
    save(root / "reference.json", refs)
    manifest = dict(version="learned-cards-original-20-v1" if library == "learned20" else "merged-cards-original-20-v1", started=pairs.now(),
        source_cohort=str(TRAIN.relative_to(REPO)), arms=["skill_rag"],
        tasks=[dict(id=t[0], title=t[1], mode=t[3], units=t[5]) for t in TASKS],
        schedule=[t[0] for t in tasks], model="deepseek-official/deepseek-v4-flash", reasoning="high",
        workers=workers, timeout=timeout, repeats=1, frontend=False,
        library=library, compatibility=compatibility,
        scope=("仅补C组20题各1次；复用历史A/B，Skill软件与B完全一致，仅启用独立20卡检索和原检索提示；原题复跑不作为未见题迁移证据。"
               if library == "learned20" else "原20题沉淀方法后复跑；当前Skill与默认合并库；历史对比不作为独立迁移效果或纯语料消融。"),
        score="沿用原20题：正常结束、输入不变、真实求解到原终点；两个数值容差max(abs(ref)*0.005,1e-12)。",
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        plugin_sha256=pairs.hashes(plugin), definition_sha256=pairs.hashes(root / "definition"),
        inputs_sha256=inputs, reference_sha256=pairs.sha(root / "reference.json"))
    save(root / "manifest.json", manifest)
    envs = {t[0]: previous.prepare(t, "skill_rag", root, plugins) for t in TASKS}
    for index, task in enumerate(TASKS):
        policy_path = root / task[0] / "skill_rag/launch-config/isolation.json"
        policy = json.loads(policy_path.read_text())
        # A single arm has no bare workspace. Probe an existing other-task input.
        policy["denied_probe_files"] = [p for p in policy["denied_probe_files"]
                                          if "/bare/workspace/request.txt" not in p]
        other = TASKS[(index + 1) % len(TASKS)][0]
        policy["denied_probe_files"].append(str(root / other / "skill_rag/workspace/request.txt"))
        if library == "learned20":
            policy["denied_probe_files"].extend(str(p) for p in (
                root / "card-audit.json", TRAIN / "scores.json", TRAIN / task[0] / "skill/workspace/answer.json",
                TRAIN / "frozen-plugin/rag/experience/data/reviewed_corpus.json",
                REPO / "rag/experience/data/reviewed_corpus.json"))
        save(policy_path, policy)
    # All isolation checks complete before the first paid model session.
    try:
        for task in tasks:
            entry, env = envs[task[0]]
            pairs.preflight(entry, "skill_rag", root, env)
        manifest["all_preflights_passed"] = True
        save(root / "manifest.json", manifest)
        def one(task):
            entry, env = envs[task[0]]
            try:
                return pairs.run(entry, "skill_rag", root, env, timeout)
            finally:
                previous.remove_temporary_auth(root / task[0] / "skill_rag")
        results = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(one, t): t[0] for t in tasks}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(dict(task_id=futures[future], arm="skill_rag", infrastructure_error=str(exc)))
                save(root / "progress.json", results)
        manifest.update(ended=pairs.now(), plugin_unchanged=pairs.hashes(plugin) == manifest["plugin_sha256"])
        save(root / "manifest.json", manifest)
        print("finished", len(results), flush=True)
    finally:
        for task in TASKS:
            previous.remove_temporary_auth(root / task[0] / "skill_rag")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--library", choices=("merged_default", "learned20"), default="merged_default")
    args = parser.parse_args()
    launch(args.root.resolve(), args.workers, args.timeout, args.library)
