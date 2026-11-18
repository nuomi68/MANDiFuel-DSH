#!/usr/bin/env python3
"""Fresh qualitative probes after terminology updates; reports misses transparently."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "rag" / "experience"))
from experience_rag import query_experience  # noqa: E402

CASES = [
    ("power_limit", "换算燃料线功率到最高温度限值时是否必须重新计算", "solve", {"K03_KTH01:04"}),
    ("gap_area_basis", "同轴燃料模型中圆柱间隙等效传热系数应按哪一侧面积", "solve", {"K03_KTH01:01"}),
    ("conservation_cause", "热流守恒残差能否证明由 AMI 插值造成", "solve", {"K04_C01:04"}),
    ("restart_fgr_scope", "续算温度和位移维持不变能否证明裂变气体释放续算正确", "solve", {"K05_W01:04"}),
    ("strain_sum", "辐照蠕变总应变可否直接等于弹性加蠕变", "solve", {"K10_C05:02"}),
    ("interface_cells", "同一界面内外材料区单元中心数值是否等于界面本身", "solve", {"K11_F02:02"}),
    ("grid_independence", "如何判断两层网格是否已经证明网格无关", "solve", {"K12_G01:02"}),
    ("sector_factor", "什么情况下按扇区角换算整棒功率", "solve", {"K04_C01:03", "K12_G01:03"}),
    ("sphere_projection", "球壳应力如何由位置向量和张量投影而不是柱坐标", "solve", {"K13_G02:02"}),
    ("nonzero_source", "反应源不为零时还能用初始库存减现存库存算释放分数吗", "solve", {"K14_M01:03"}),
    ("prepare_only", "只允许输入准备任务是否应该启动 offbeat", "solve", {"K01_P02:03"}),
    ("unverified_claim", "temperature clamp SiC 640 900 claim unverified", "troubleshoot", {"K10_C05:04"}),
    ("launch_budget", "用户限制启动次数时初始化失败和重试怎么算", "solve", {"K05_W01:02", "K08_C08_RECOVERY:04"}),
    ("restart_boundary", "续算时修改压力边界后如何证明物理等价", "troubleshoot", {"K05_W01:03"}),
]


def main() -> int:
    hits = 0
    for name, query, purpose, expected in CASES:
        result = query_experience(query, purpose=purpose, limit=3, adjacent=0)
        ids = [row["child"]["id"] for row in result["results"]]
        matched = any(any(cid.endswith(target) for target in expected) for cid in ids)
        hits += int(matched)
        print(f"{'PASS' if matched else 'MISS'} {name}: {', '.join(ids) or '(empty)'}")
    print(f"Fresh top-3 paraphrases: {hits}/{len(CASES)} expected topic hit")
    return int(hits != len(CASES))


if __name__ == "__main__":
    raise SystemExit(main())
