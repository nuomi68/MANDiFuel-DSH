"""Score a twenty-task supplement and compare its whole-task outcomes with frozen controls."""
import argparse
import csv
import json
from pathlib import Path

from materials import REPO, TRAIN, pairs, save
from tasks import TASKS
from analyze import brief, close, score
from reference import times
from score import trace_details


def export(root, destination):
    progress = json.loads((root / "progress.json").read_text())
    if (len(progress) != 20 or {(r["task_id"], r["arm"]) for r in progress}
            != {(t[0], "skill_rag") for t in TASKS} or any(r.get("infrastructure_error") for r in progress)):
        raise ValueError("Incomplete cohort; inspect progress.json before scoring")
    manifest = json.loads((root / "manifest.json").read_text())
    learned_only = manifest.get("library") == "learned20"
    if not manifest.get("all_preflights_passed") or not manifest.get("plugin_unchanged"):
        raise ValueError("Preflight or frozen-plugin integrity check failed")
    if pairs.hashes(root / "frozen-plugin") != manifest["plugin_sha256"]:
        raise ValueError("Frozen plugin changed after the run")
    if pairs.sha(root / "reference.json") != manifest["reference_sha256"]:
        raise ValueError("Reference changed after freezing")
    if pairs.hashes(root / "definition") != manifest["definition_sha256"]:
        raise ValueError("Frozen run definition changed")
    calibration = json.loads((root / "calibration.json").read_text())
    references = json.loads((root / "reference.json").read_text())
    if learned_only:
        provenance = json.loads((root / "calibration-provenance.json").read_text())
        if (pairs.sha(root / "calibration.json") != provenance["calibration_sha256"]
                or pairs.hashes(root / "calibration") != provenance["files_sha256"]):
            raise ValueError("Reused independent calibration differs from its recorded provenance")
    for task in TASKS:
        identifier = task[0]
        actual = pairs.hashes(root / identifier / "source-case")
        if actual != manifest["inputs_sha256"][identifier] or actual != pairs.hashes(TRAIN / identifier / "source-case"):
            raise ValueError(f"Source drift: {identifier}")
        if task[3] == "solve":
            item = calibration[identifier]
            if item["exit_code"] or not all(close(a, b) for a, b in zip(item["values"], references[identifier])):
                raise ValueError(f"Calibration failed: {identifier}")
            if times(root / "calibration" / identifier) != times(TRAIN / "calibration" / identifier):
                raise ValueError(f"Calibration save times differ: {identifier}")
    rows = [score(task, "skill_rag", root) for task in TASKS]
    reviews = []
    if learned_only:
        card_sources = json.loads((root / "card-audit.json").read_text())
        corpus = json.loads((root / "frozen-plugin/rag/experience/data/reviewed_corpus.json").read_text())
        if (not manifest["compatibility"]["shared_skill_identical_to_B"]
                or manifest["compatibility"]["old_library_included"]
                or {p["id"] for p in corpus["parents"]} != {f"knowledge:K{i}" for i in range(21, 41)}
                or len(corpus["children"]) != 20):
            raise ValueError("Learned-only library or group B software compatibility check failed")
    else:
        card_sources = json.loads((root / "frozen-plugin/rag/experience/data/card_transfer_review.json").read_text())["cards"]
    expected_cards = {c["task"]: c["id"] + ":01" for c in card_sources}
    for row in rows:
        if (row["session_count"] != 1 or not row["preflight"] or row["ui_or_subagent_tools"]
                or row["configs"] != [["deepseek-official", "deepseek-v4-flash", "high"]]
                or row["model_messages"] != row["messages_with_usage"]
                or row["total_tokens"] != row["uncached_input"] + row["cached_input"] + row["model_output"]):
            raise ValueError(f"Backend trace or usage mismatch: {row['id']}")
        folder = root / row["id"] / "skill_rag"
        retrieval, final = trace_details(folder)
        answer = json.loads((folder / "workspace/answer.json").read_text()) if (folder / "workspace/answer.json").is_file() else {}
        returned = sorted({cid for query in retrieval for cid in query["ids"]})
        combined = final + "\n" + str(answer.get("source", ""))
        named = [cid for cid in returned if cid in combined or cid.split(":", 1)[1] in combined]
        row.update(retrieval=retrieval, source_card=expected_cards[row["id"]],
                   source_card_retrieved=expected_cards[row["id"]] in returned, named_hit_ids=named)
        reviews.append(dict(id=row["id"], title=row["title"], returned_ids=" | ".join(returned),
            named_hit_ids=" | ".join(named), source_card=row["source_card"],
            source_card_retrieved=row["source_card_retrieved"], source=answer.get("source", ""), final=final))
    aggregate = brief(rows)
    aggregate.update(source_card_retrieved=sum(r["source_card_retrieved"] for r in rows),
        named_hit_sessions=sum(bool(r["named_hit_ids"]) for r in rows),
        tool_calls=sum(r["tool_calls"] for r in rows))
    historical = json.loads((TRAIN / "aggregate.json").read_text())["arms"]
    if learned_only:
        historical = {k: historical[k] for k in ("bare", "skill")}
    save(root / "scores.json", rows)
    comparison = dict(current=aggregate, historical=historical)
    if learned_only:
        comparison["changes"] = {key: dict(
            total_tokens=aggregate["tokens"] - old["tokens"],
            total_tokens_percent=100 * (aggregate["tokens"] / old["tokens"] - 1),
            uncached_plus_output_percent=100 * (aggregate["uncached_plus_output"] / old["uncached_plus_output"] - 1),
            task_pass_percentage_points=100 * (aggregate["task_pass"] - old["task_pass"]) / 20,
            physics_pass_percentage_points=100 * (aggregate["physics_pass"] - old["physics_pass"]) / 20)
            for key, old in historical.items()}
    else:
        comparison["strata"] = {mode: brief([r for r in rows if r["id"].startswith(mode)]) for mode in "SPD"}
    save(root / "aggregate.json", comparison)
    evaluation = root / "evaluation"
    evaluation.mkdir(exist_ok=True)
    scorer = Path(__file__).resolve()
    frozen_scorer = evaluation / scorer.name
    if frozen_scorer.exists() and frozen_scorer.read_bytes() != scorer.read_bytes():
        raise ValueError("Scoring code differs from the saved evaluation")
    frozen_scorer.write_bytes(scorer.read_bytes())
    save(evaluation / "manifest.json", dict(scoring_file=scorer.name, sha256=pairs.sha(frozen_scorer),
        dependencies="definition/three-arm-20/{analyze,reference,tasks}.py; definition/experience-card-transfer/score.py"))
    destination.mkdir(parents=True, exist_ok=True)
    fields = ["id", "title", "arm", "task_pass", "physics_pass", "a", "a_ref", "a_unit", "a_match", "b", "b_ref", "b_unit", "b_match", "total_tokens", "uncached_input", "cached_input", "model_output", "tool_calls", "rag_invocations", "rag_observed_returns", "source_card", "source_card_retrieved", "named_hit_ids", "expected_final_time", "actual_final_time", "raw_checks", "execution_ok", "input_preserved", "result_root", "wall_s"]
    with (destination / "逐题明细.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with (destination / "检索与答复原文.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, list(reviews[0]))
        writer.writeheader()
        writer.writerows(reviews)
    if learned_only:
        controls = [r for r in json.loads((TRAIN / "scores.json").read_text()) if r["arm"] in ("bare", "skill")]
        with (destination / "三组逐题明细.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["配置", "题号", "任务", "任务成功", "整体物理正确完成", "总token", "非缓存输入", "缓存输入", "输出", "耗时秒"])
            for record in [*controls, *rows]:
                group = ("A 原DSH" if record["arm"] == "bare" else
                         "B Skill" if record["arm"] == "skill" else "C Skill+20张新卡")
                writer.writerow([group, record["id"], record["title"], record["task_pass"], record["physics_pass"],
                    record["total_tokens"], record["uncached_input"], record["cached_input"], record["model_output"], record["wall_s"]])
    labels = ({"bare": "A 原 DSH（已有）", "skill": "B DSH + Skill（已有）"} if learned_only else
              {"bare": "历史 DSH 基线", "skill": "历史仅 Skill", "skill_rag": "历史 Skill + 旧库"})
    if learned_only:
        with (destination / "三组整体汇总.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["配置", "任务数", "总token", "相对原DSH变化百分比", "相对Skill变化百分比", "任务成功数", "物理正确完成数", "工程量符合数", "非缓存输入", "缓存输入", "输出"])
            for key, item in [*historical.items(), ("current", aggregate)]:
                label = "C DSH + Skill + 20张新卡" if key == "current" else labels[key]
                writer.writerow([label, item["n"], item["tokens"], 100 * (item["tokens"] / historical["bare"]["tokens"] - 1),
                    100 * (item["tokens"] / historical["skill"]["tokens"] - 1), item["task_pass"], item["physics_pass"],
                    item["endpoint_matches"], item["uncached_input"], item["cached_input"], item["model_output"]])
    introduction = (["# 20 题 A/B/C 单次整体对照", "",
        "2026 年 11 月 19 日（北京时间）。本轮仅补 C 组：DSH + Skill + 从已核验 20 题提炼的 20 张方法卡，每题新开一个独立 DSH 会话。A/B 复用原批次的单次运行。", "",
        "C 组使用原 A/B 批次的冻结 Skill 软件、模型、推理等级、题面与逐文件输入；与 B 组全部共享软件文件逐项相同。额外启用原批次固定的经验检索提示和独立经验库，仅含 K21–K40 共 20 张父卡、20 条方法记录。旧库及项目默认合并库均未接入，隔离预检确认其语料和历史答案不可读取。"]
        if learned_only else ["# 20 题经验沉淀后的原题复跑", "",
        "2026 年 11 月 19 日（北京时间）。保留旧库全部条目，合入原 20 题提炼的 K21–K40 方法卡，更新默认索引后，用当前项目 Skill 新开 20 个独立 DSH 会话。", "",
        "默认库现有 34 张父卡、79 个子条目：66 条审核通过，其中 3 条历史数值示例默认关闭，常规求解可用 63 条；其余 13 条限于排错。新增卡保留适用条件、取数方法、单位和证据出处。"])
    report = [*introduction, "",
        "## 结果", "", "| 配置 | 总 token | 非缓存输入 | 缓存输入 | 输出 | 任务成功 | 物理符合 | 工程量符合 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for key, item in [*(historical.items()), ("current", aggregate)]:
        label = ("C DSH + Skill + 20 张新卡" if learned_only else "本轮 Skill + 合并库") if key == "current" else labels[key]
        report.append(f"| {label} | {item['tokens']:,} | {item['uncached_input']:,} | {item['cached_input']:,} | {item['model_output']:,} | {item['task_pass']}/20 | {item['physics_pass']}/20 | {item['endpoint_matches']}/40 |")
    control = "skill" if learned_only else "skill_rag"
    delta = 100 * (aggregate["tokens"] / historical[control]["tokens"] - 1)
    old_rows = {r["id"]: r for r in json.loads((TRAIN / "scores.json").read_text()) if r["arm"] == control}
    cheaper = sum(row["total_tokens"] < old_rows[row["id"]]["total_tokens"] for row in rows)
    control_label = "B 组（仅 Skill）" if learned_only else "历史旧库组"
    report += ["", f"相对{control_label}，总 token 变化 {delta:+.1f}%；逐题有 {cheaper}/20 题用量下降。总 token 包括缓存命中输入，不代表账单成本。", "",
        f"本轮 {aggregate['rag_sessions']}/20 题调用经验检索，{aggregate['confirmed_rag_sessions']}/20 题在轨迹中核实有效回包；对应出卡条目在 {aggregate['source_card_retrieved']}/20 题被检回。最终答复或取数说明完整提到命中子条目 ID 的有 {aggregate['named_hit_sessions']}/20 题，这个计数包含排除项，不能直接解释为采用。", "",
        ("| 题号 | 任务 | B 仅 Skill token | C 新卡 token | 任务成功 | 物理符合 | 原题方法卡命中 |" if learned_only else
         "| 题号 | 任务 | 历史旧库 token | 本轮合并库 token | 任务成功 | 物理符合 | 原题方法卡命中 |"), "|---|---|---:|---:|---|---|---|"]
    for row in rows:
        report.append(f"| {row['id']} | {row['title']} | {old_rows[row['id']]['total_tokens']:,} | {row['total_tokens']:,} | {'通过' if row['task_pass'] else '未通过'} | {'通过' if row['physics_pass'] else '未通过'} | {'是' if row['source_card_retrieved'] else '否'} |")
    if learned_only:
        report += ["", "## 整体变化", ""]
        for key, change in comparison["changes"].items():
            report.append(f"相对 {labels[key]}：总 token {change['total_tokens']:+,}（{change['total_tokens_percent']:+.1f}%）；任务成功率 {change['task_pass_percentage_points']:+.1f} 个百分点，物理符合率 {change['physics_pass_percentage_points']:+.1f} 个百分点；非缓存输入加输出 {change['uncached_plus_output_percent']:+.1f}%。")
    report += ["", "## 复核与解释边界", "",
        ("本轮沿用原 20 题完全相同的题面和逐文件输入。模型仍为 DeepSeek V4 Flash、high，headless；每题独立工作区、独立会话和工具轨迹，禁止访问其他题目、历史答案和裁判参考。经验卡的证据路径是来源元数据，测试进程无权读取其指向的历史档案。" +
         ("C 组要求先检索一次，再判断适用性；A/B 不接入经验库。" if learned_only else "两个 RAG 轮次均要求先检索一次，再判断适用性。")), "",
        (("8 道求解题复用原批次已独立求解并核验的裁判校准，冻结输入与参考不变；评分另行复读本轮 C 组的真实结果场。" if learned_only else
          "8 道求解题在裁判端另行从初态执行 OFFBEAT，校准值及保存时刻与原参考一致。") +
         "任务成功核对正常退出、输入未变、交付完整、求解终点和真实结果场；后处理题核查未启动求解。物理符合还要求两个交付量均在 max(参考值绝对值 × 0.5%, 1e−12) 内。原始场复算结果在明细单列，不覆盖终点失败。"), "",
        ("这是把原题记录沉淀为方法后再做原题的单次回归复跑。C 组与 B 组的共享 Skill 软件完全一致，但 A/B 为历史运行，未在本轮重跑；每题每组仅一次，因此不能衡量重复可靠性或排除服务与缓存波动，也不能作为未见题迁移证据。经验提炼含人工审核，本表只统计执行阶段模型用量，不包含出卡及审核成本。"
         if learned_only else "这是把原题记录沉淀为方法后再做原题的回归复跑。历史三组未在本轮重跑，每题每组只有一次；当前 Skill 与历史快照也存在配置差异。因此可报告本轮质量和用量，不能把差异单独归因于新卡，也不能当成未见题迁移收益。此前 8 道新题的 24 会话实验另列。"), "",
        f"[本轮配置与文件指纹](../../runs/{root.name}/manifest.json) · [原始评分](../../runs/{root.name}/scores.json) · [独立校准](../../runs/{root.name}/calibration.json) · [逐题明细](逐题明细.csv) · [检索及最终答复原文](检索与答复原文.csv)", "",
        (f"[本轮20卡来源](../../runs/{root.name}/card-audit.json) · [方法卡与出处](../经验卡迁移实测/20张经验卡.md)" if learned_only else
         "[新增卡审核与来源](../../rag/experience/data/card_transfer_review.json) · [默认经验库](../../rag/experience/README.md) · [此前新题迁移实测](../经验卡迁移实测/迁移实测报告.md)"), ""]
    (destination / ("整体对照报告.md" if learned_only else "复跑报告.md")).write_text("\n".join(report))
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export(args.root.resolve(), args.destination.resolve())
