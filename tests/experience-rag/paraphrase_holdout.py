#!/usr/bin/env python3
"""Additional paraphrases not used for the first terminology adjustments."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "rag" / "experience"))
from experience_rag import query_experience  # noqa: E402

CHECKS = [
    ("mesh_readback", "几何半径变更后如何回读网格和冷态材料参数", "solve", {"K01_P02:03"}),
    ("radius_vs_diameter", "冷态间隙输入到底是包壳内半径减芯块外半径吗", "solve", {"K01_P02:02"}),
    ("cladding_patch", "包壳腐蚀数据在哪个 patch，不是一般体积场", "solve", {"K02_C04:02", "K02_C04:04"}),
    ("oxide_field_type", "表面氧化物厚度字段不是体积标量场如何提取", "solve", {"K02_C04:04"}),
    ("control_dict_time", "time units for controlDict days versus seconds", "solve", {"K02_C04:01"}),
    ("annular_gas_conductance", "radial annular gas layer equivalent conductance under constant conductivity", "solve", {"K03_KTH01:01"}),
    ("opposing_normals", "coupled interface opposing outward normals heat transfer", "solve", {"K04_C01:02"}),
    ("completed_fields", "求解完成时间文件存在是否说明程序成功", "solve", {"K02_C04:03", "K05_W01:02"}),
    ("restart_state", "保留续算交接时刻原始状态和字段清单", "solve", {"K05_W01:01"}),
    ("restart_pressure", "restart checkpoint coolantPressureList read failure", "troubleshoot", {"K05_W01:03"}),
    ("zero_schedule", "zero power end time tabulated schedule fails at last entry", "troubleshoot", {"K06_C02:03"}),
    ("mechanics_selector", "机械求解类型 mechanicsSolver none 不支持如何报错", "troubleshoot", {"K07_C08_LIMITED:01"}),
    ("gas_dependency", "gapGas disabled but fuelRodGap thermal needs gas conduction", "troubleshoot", {"K07_C08_LIMITED:02", "K08_C08_RECOVERY:02"}),
    ("stress_order", "how to check symmTensor normal xx and xy shear ordering", "solve", {"K10_C05:01"}),
    ("strain_decomposition", "without thermal expansion, is total strain equal to elastic plus creep?", "solve", {"K10_C05:02"}),
    ("different_positions", "two cladding interface sample positions stress and displacement", "solve", {"K11_F02:02"}),
    ("tensor_basis", "cylindrical tensor versus spherical radial stress", "solve", {"K13_G02:02"}),
    ("cs_mass_balance", "Cs remaining inventory M0 mass balance absorbing boundary", "solve", {"K14_M01:03"}),
    ("diffusion_binding", "燃料核扩散系数写入之后如何验证已生效", "solve", {"K14_M01:02"}),
    ("mesh_failure", "中心塌缩球核网格的 checkMesh 失败是否影响其他问题", "solve", {"K14_M01:05"}),
]


def main() -> int:
    hits = 0
    for name, query, purpose, expected in CHECKS:
        result = query_experience(query, purpose=purpose, limit=3, adjacent=0)
        ids = [row["child"]["id"] for row in result["results"]]
        matched = any(any(cid.endswith(target) for target in expected) for cid in ids)
        hits += int(matched)
        print(f"{'PASS' if matched else 'MISS'} {name}: {', '.join(ids) or '(empty)'}")
    print(f"Additional top-3 paraphrases: {hits}/{len(CHECKS)} expected topic hit")
    return int(hits != len(CHECKS))


if __name__ == "__main__":
    raise SystemExit(main())
