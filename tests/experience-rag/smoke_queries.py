#!/usr/bin/env python3
"""Representative retrieval-only checks against the reviewed experience corpus."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "rag" / "experience"))
from experience_rag import query_experience  # noqa: E402

SCENARIOS = [
    ("cold_gap_zh", "燃料棒冷态直径与冷态间隙 DiamCold GapCold", {}, {"knowledge:K01_P02:02"}),
    ("cold_gap_en", "fuel rod cold gap fuel diameter GapCold", {}, {"knowledge:K01_P02:02"}),
    ("oxidation_zh", "包壳外表面氧化层厚度怎么提取 oxideThickness", {},
     {"knowledge:K02_C04:02", "knowledge:K02_C04:04"}),
    ("oxidation_en", "cladding oxidation oxide thickness cladOuter", {},
     {"knowledge:K02_C04:02", "knowledge:K02_C04:04"}),
    ("time_units", "腐蚀 userTime 时间 单位 天 秒", {}, {"knowledge:K02_C04:01"}),
    ("gap_heat_resistance", "稳态燃料棒 圆柱气隙 热导 热阻", {}, {"knowledge:K03_KTH01:01"}),
    ("heat_flux", "燃料包壳界面 热流 外法向 守恒", {},
     {"knowledge:K04_C01:02", "knowledge:K04_C01:03"}),
    ("creep", "SiC 蠕变 应变 张量 epsilonCreep", {},
     {"knowledge:K10_C05:01", "knowledge:K10_C05:02"}),
    ("spherical_stress_zh", "球壳 球坐标 径向应力 应力张量投影", {},
     {"knowledge:K13_G02:02"}),
    ("spherical_stress_en", "spherical shell stress projection radial stress", {},
     {"knowledge:K13_G02:02"}),
    ("cesium_diffusion", "UO2 球核 Cs 扩散 释放分数 库存", {}, {"knowledge:K14_M01:03"}),
    ("annular_fuel", "环形燃料 孔径 固定点 扫描", {}, {"knowledge:K09_F01:01"}),
    ("mesh_warning", "球心 塌缩 楔网格 checkMesh", {}, {"knowledge:K14_M01:05"}),
    ("restart_error", "续算 D coolantPressureList 回读失败",
     {"purpose": "troubleshoot", "review_status": "troubleshooting_only"},
     {"knowledge:K05_W01:03"}),
    ("limited_gap_error", "fuelRodGap gapGas 初始化失败",
     {"purpose": "troubleshoot", "review_status": "troubleshooting_only",
      "arm": "skill", "task_status": "incomplete"}, {"knowledge:K07_C08_LIMITED:02"}),
    ("mechanics_error", "mechanicsSolver none 初始化失败",
     {"purpose": "troubleshoot", "review_status": "troubleshooting_only",
      "arm": "skill", "task_status": "incomplete"}, {"knowledge:K07_C08_LIMITED:01"}),
]


def main() -> int:
    failures = 0
    for name, query, options, expected in SCENARIOS:
        result = query_experience(query, limit=5, **options)
        ids = [item["child"]["id"] for item in result["results"]]
        matches = expected.intersection(ids)
        valid = bool(matches)
        failures += not valid
        print(f"{'PASS' if valid else 'FAIL'} {name}: {', '.join(ids) or '(no hits)'}")
    print(f"Retrieval scenarios: {len(SCENARIOS) - failures}/{len(SCENARIOS)} passed")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
