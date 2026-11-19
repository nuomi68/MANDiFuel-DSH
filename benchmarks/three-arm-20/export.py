"""Export backend scores to a Chinese spreadsheet and Markdown tables."""
import argparse
import csv
import json
import statistics
from pathlib import Path


ARMS = {"bare": "DSH 基线", "skill": "Skill", "skill_rag": "Skill + 经验 RAG"}
STRATA = {"S": "从初态求解", "P": "场与日志后处理", "D": "观测与设计分析"}


def percentage_delta(after, before):
    return 100 * (after / before - 1)


def fraction(k, n):
    return f"{k}/{n}（{k/n:.0%}）"


def tables(rows, stats):
    arms = stats["arms"]
    yield "| 配置 | 总 token | 每题平均 | 每题中位数 | 任务成功 | 物理符合 | 工程量命中 |"
    yield "|---|---:|---:|---:|---:|---:|---:|"
    for arm, label in ARMS.items():
        g = arms[arm]
        n = g["n"]
        yield (f'| {label} | {g["tokens"]:,} | {g["tokens"]/n:,.0f} | {g["median_tokens"]:,.0f} | '
               f'{fraction(g["task_pass"], n)} | {fraction(g["physics_pass"], n)} | {g["endpoint_matches"]}/{2*n} |')
    yield ""
    yield "| 同题配对 | 总 token 变化 | 每题变化率中位数 | 后一配置更省／持平／更费的题数 |"
    yield "|---|---:|---:|---:|"
    pairs = {(r["id"], r["arm"]): r for r in rows}
    for left, right in [("bare", "skill"), ("skill", "skill_rag"), ("bare", "skill_rag")]:
        changes = [percentage_delta(pairs[r["id"], right]["total_tokens"], r["total_tokens"])
                   for r in rows if r["arm"] == left]
        change = percentage_delta(arms[right]["tokens"], arms[left]["tokens"])
        yield (f'| {ARMS[left]} → {ARMS[right]} | {change:+.1f}% | {statistics.median(changes):+.1f}% | '
               f'{sum(v < 0 for v in changes)}／{changes.count(0)}／{sum(v > 0 for v in changes)} |')
    yield ""
    yield "| 类别 | 题数 | 基线每题 token | Skill 每题 token | Skill + 经验每题 token | Skill 相对基线 | 加经验相对 Skill |"
    yield "|---|---:|---:|---:|---:|---:|---:|"
    for group, label in STRATA.items():
        split = stats["strata"][group]
        n = split["bare"]["n"]
        a, b, c = [split[arm]["tokens"] / n for arm in ARMS]
        yield (f"| {label} | {n} | {a:,.0f} | {b:,.0f} | {c:,.0f} | "
               f"{percentage_delta(b,a):+.1f}% | {percentage_delta(c,b):+.1f}% |")
    yield ""
    yield "| 配置 | 非缓存输入 | 缓存命中输入 | 模型输出 | 非缓存输入＋输出 |"
    yield "|---|---:|---:|---:|---:|"
    for arm, label in ARMS.items():
        g = arms[arm]
        yield (f'| {label} | {g["uncached_input"]:,} | {g["cached_input"]:,} | '
               f'{g["model_output"]:,} | {g["uncached_plus_output"]:,} |')


def spreadsheet(rows, root, target):
    columns = [
        ("id", "题号"), ("title", "题目"), ("question", "完整题面"), ("group", "类别"),
        ("arm", "配置"), ("task_pass", "任务成功"), ("physics_pass", "物理符合"),
        ("a", "工程量A"), ("a_ref", "A参考值"), ("a_unit", "A单位"), ("a_match", "A符合"),
        ("b", "工程量B"), ("b_ref", "B参考值"), ("b_unit", "B单位"), ("b_match", "B符合"),
        ("total_tokens", "总token"), ("uncached_input", "非缓存输入"), ("cached_input", "缓存命中输入"),
        ("model_output", "模型输出"), ("model_messages", "模型回复次数"), ("tool_calls", "工具调用次数"),
        ("skill_calls", "Skill调用次数"), ("rag_invocations", "经验检索调用次数"),
        ("rag_observed_returns", "确认成功返回次数"), ("returned_ids", "回包中可见的经验标识"),
        ("expected_final_time", "给定算例终点(s)"), ("actual_final_time", "实际保存终点(s)"),
        ("raw_values", "独立复读终态场(A和B)"), ("input_preserved", "原输入完整"),
        ("wall_s", "会话用时(s)"), ("source", "会话交付的取数说明"), ("evidence", "原始运行目录"),
    ]
    with target.open("w", encoding="utf-8-sig", newline="") as file:
        out = csv.writer(file)
        out.writerow([label for _, label in columns])
        for data in rows:
            r = data.copy()
            folder = root / r["id"] / r["arm"]
            answer = folder / "workspace/answer.json"
            r.update(
                arm=ARMS[r["arm"]], group=STRATA[r["id"][0]],
                evidence=str(Path("runs") / root.name / r["id"] / r["arm"]),
                question=(folder.parent / "task.txt").read_text().strip(),
                source=json.loads(answer.read_text()).get("source", "") if answer.exists() else "",
            )
            def value(key):
                entry = r.get(key)
                if isinstance(entry, bool):
                    return "是" if entry else "否"
                if isinstance(entry, list):
                    return " | ".join(map(str, entry))
                return entry
            out.writerow([value(key) for key, _ in columns])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    rows = json.loads((root / "scores.json").read_text())
    stats = json.loads((root / "aggregate.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    spreadsheet(rows, root, args.output / "逐题明细.csv")
    print("\n".join(tables(rows, stats)))


if __name__ == "__main__":
    main()
