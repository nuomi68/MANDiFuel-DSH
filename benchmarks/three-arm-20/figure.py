"""Draw the three-arm comparison directly from scored backend sessions."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter


ARMS = ("bare", "skill", "skill_rag")
NAMES = ("DSH 基线", "Skill", "Skill + 经验 RAG")
COLORS = ("#58677D", "#197565", "#C1632E")
MARKERS = ("o", "s", "D")


def chart(root, file, font):
    if font:
        font_manager.fontManager.addfont(font)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=font).get_name()
    plt.rcParams.update({
        "axes.unicode_minus": False, "font.size": 10, "axes.spines.top": False,
        "axes.spines.right": False, "axes.edgecolor": "#C6CED5", "text.color": "#202D38",
        "axes.labelcolor": "#334858", "xtick.color": "#485762", "ytick.color": "#304453",
    })
    scores = json.loads((root / "scores.json").read_text())
    aggregate = json.loads((root / "aggregate.json").read_text())
    by_id = {(row["id"], row["arm"]): row for row in scores}
    tasks = [row for row in scores if row["arm"] == "bare"]
    fig = plt.figure(figsize=(13.6, 9), layout=None)
    fig.subplots_adjust(left=.20, right=.96, top=.80, bottom=.12, wspace=.40, hspace=.64)
    grid = fig.add_gridspec(2, 2, width_ratios=(1.38, 1))
    paired = fig.add_subplot(grid[:, 0])
    total = fig.add_subplot(grid[0, 1])
    strata = fig.add_subplot(grid[1, 1])
    fig.text(.035, .958, "20 道工程任务的后端配对实测", fontsize=24, fontweight="bold")
    fig.text(.035, .912, "同一题面与数据  /  每题三组独立会话  /  DeepSeek V4 Flash · high", fontsize=12)
    rates = []
    for arm, label in zip(ARMS, NAMES):
        stats = aggregate["arms"][arm]
        rates.append(f'{label}  {stats["task_pass"]/stats["n"]:.0%} / {stats["physics_pass"]/stats["n"]:.0%}')
    fig.text(.035, .868, "任务成功率 / 物理符合率（各 20 题）      " + "       ".join(rates), fontsize=11)

    for i, task in enumerate(tasks):
        points = [by_id[task["id"], arm]["total_tokens"] / 10000 for arm in ARMS]
        paired.hlines(i, min(points), max(points), color="#C0C9CF", lw=1.4)
        for x, c, marker in zip(points, COLORS, MARKERS):
            paired.scatter(x, i, s=31, c=c, marker=marker, zorder=3, edgecolors="white", linewidths=.65)
    paired.set_xscale("log")
    paired.set_xticks([5, 10, 20, 50, 100, 200])
    paired.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:g}"))
    paired.set_yticks(range(len(tasks)), [f'{r["id"]}  {r["title"]}' for r in tasks], fontsize=9)
    paired.set_ylim(len(tasks) - .4, -.65)
    paired.tick_params(axis="y", length=0, pad=6)
    paired.set_xlabel("单题总 token（万，对数刻度）")
    paired.set_title("同一任务的三组用量", loc="left", fontsize=14, pad=12)
    paired.grid(axis="x", color="#DFE5E9")
    for mark in (7.5, 15.5):
        paired.axhline(mark, c="#D7DEE2", lw=1, ls="--")

    totals = [aggregate["arms"][a]["tokens"] / 10000 for a in ARMS]
    total.barh(range(3), totals, color=COLORS, height=.46)
    total.set_yticks(range(3), NAMES)
    total.tick_params(axis="y", length=0)
    total.invert_yaxis()
    total.set_xlim(0, 1.23 * max(totals))
    for i, val in enumerate(totals):
        total.text(val + max(totals)*.02, i, f"{val:,.1f}", va="center", fontsize=11)
    total.set_title("完成整套题的总用量", loc="left", fontsize=14, pad=12)
    total.set_xlabel("总 token（万，含缓存命中输入）")

    for idx, group in enumerate(("S", "P", "D")):
        for j, arm in enumerate(ARMS):
            part = aggregate["strata"][group][arm]
            strata.barh(idx + (j - 1)*.22, part["tokens"] / part["n"] / 10000,
                        height=.18, color=COLORS[j])
    strata.set_yticks(range(3), ("初态求解（8）", "场与日志（8）", "观测分析（4）"))
    strata.tick_params(axis="y", length=0)
    strata.invert_yaxis()
    strata.set_xlabel("每题平均 token（万）")
    strata.set_title("按工作类型看每题开销", loc="left", fontsize=14, pad=12)
    for ax in (total, strata):
        ax.spines["left"].set_visible(False)
        ax.grid(axis="x", color="#E8ECEF")
        ax.set_axisbelow(True)
    handles = [plt.Line2D([], [], color=c, marker=m, lw=0, markersize=7)
               for c, m in zip(COLORS, MARKERS)]
    fig.legend(handles, NAMES, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(.5, .012))
    file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(file, dpi=180, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("file", type=Path)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    chart(args.root, args.file, args.font)
