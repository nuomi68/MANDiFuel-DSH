#!/usr/bin/env python3
"""Probe natural-language paraphrases against reviewed children, without solving cases."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "rag" / "experience"))
from experience_rag import query_experience  # noqa: E402

PROBES = [
    ("zh_cold_geometry", "冷态直径与燃料包壳的初始间距如何关联", "solve", {"K01_P02:02"}),
    ("gap_definition", "FRAPCON 的 GapCold 是半径间隙还是直径间隙", "solve", {"K01_P02:02"}),
    ("en_clad_oxide", "cladding outer oxide corrosion surface boundary value", "solve", {"K02_C04:02", "K02_C04:04"}),
    ("zh_time", "氧化腐蚀终点怎么确定是天还是秒", "solve", {"K02_C04:01"}),
    ("en_cylindrical_gap", "cylindrical gas conduction thermal resistance", "solve", {"K03_KTH01:01"}),
    ("zh_interface_coefficient", "同轴气体层等效换热系数面积基准", "solve", {"K03_KTH01:01"}),
    ("en_interface_normals", "fuel cladding interface normals heat flow sign", "solve", {"K04_C01:02"}),
    ("zh_sector_power", "楔形扇区热源积分总功率换算", "solve", {"K04_C01:03", "K12_G01:03"}),
    ("en_continuation", "continuation checkpoint temperature displacement compare", "solve", {"K05_W01:01", "K05_W01:04"}),
    ("zh_restart", "从交接时间继续计算保存字段与清单", "solve", {"K05_W01:01"}),
    ("zh_sphere", "球壳内外压力球坐标切向应力", "solve", {"K06_C02:01", "K13_G02:02"}),
    ("en_table_error", "zero power table end point error time extrapolation", "troubleshoot", {"K06_C02:03"}),
    ("en_gap_error", "fuelRodGap gapGas none missing conductivity model", "troubleshoot", {"K07_C08_LIMITED:02"}),
    ("en_mechanics_error", "mechanicsSolver none invalid selector", "troubleshoot", {"K07_C08_LIMITED:01"}),
    ("zh_annulus", "变孔径但保持线功率不变如何扫点", "solve", {"K09_F01:01"}),
    ("en_sic_component", "SiC component epsilonCreep XX order", "solve", {"K10_C05:01"}),
    ("en_sic_decomposition", "turn off thermal expansion plastic strain elastic creep sum", "solve", {"K10_C05:02"}),
    ("zh_cylinder", "两个压力点的圆筒界面位移应力怎样对照", "solve", {"K11_F02:02"}),
    ("zh_reference", "从零建立目标模型如何选择参考卡片", "solve", {"K12_G01:01"}),
    ("en_cylinder", "cylinder pressure interface cell values", "solve", {"K11_F02:02"}),
    ("en_projection", "spherical shell stress projection radial stress", "solve", {"K13_G02:02"}),
    ("en_cesium", "radioactive cesium diffusion inventory release ratio", "solve", {"K14_M01:03"}),
    ("mesh_axis", "checkMesh 球心 坍塌 楔形网格", "solve", {"K12_G01:05", "K14_M01:05"}),
    ("fgr_scope", "FGR 重启未启用 续算的证明范围", "solve", {"K05_W01:04"}),
]


def main() -> int:
    hits = 0
    for name, query, purpose, expected in PROBES:
        result = query_experience(query, purpose=purpose, limit=3, adjacent=0)
        ids = [row["child"]["id"] for row in result["results"]]
        matched = any(any(cid.endswith(target) for target in expected) for cid in ids)
        hits += int(matched)
        print(f"{'PASS' if matched else 'MISS'} {name}: {', '.join(ids) or '(empty)'}")
    print(f"Top-3 paraphrase probes: {hits}/{len(PROBES)} expected topic hit")
    return int(hits != len(PROBES))


if __name__ == "__main__":
    raise SystemExit(main())
