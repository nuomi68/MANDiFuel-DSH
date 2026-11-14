# 已验证参数计划

此入口是普通运行助手使用的公共工具。不要阅读实现。契约目录目前只覆盖：单 UO2 材料区、`materialProperties byZone`、`elementTransport byList`、仅 `FpDiffusion`、仅 Cs 的常扩散系数。区名按源输入填写，D 单位 m²/s，必须为正有限数。工具不检查安装、不联网、不查看源码，不自动换模型或增加求解次数。

## 一次准备和运行

先按题面和源中相关输入生成一个 JSON 计划，再调用一次工具。以下数值仅示范格式，全部替换为本题要求；未请求修改的输入不要列入 edits。

```json
{
  "bindings": [
    {"contract": "fpdiffusion-cs-constant-v1", "zone": "Kernel", "value": 2e-13}
  ],
  "edits": [
    {"file": "system/controlDict", "entry": "startFrom", "value": "startTime"},
    {"file": "system/controlDict", "entry": "startTime", "value": "0"},
    {"file": "system/controlDict", "entry": "endTime", "value": "20000"},
    {"file": "system/controlDict", "entry": "deltaT", "value": "50"},
    {"file": "system/controlDict", "entry": "purgeWrite", "value": "0"},
    {"file": "0/T", "entry": "internalField", "value": "uniform 1800"},
    {"file": "0/T", "entry": "boundaryField/outer/value", "value": "uniform 1800"}
  ],
  "expected_fields": {"T": 1800, "sourceCs": 0},
  "cs_inventory": true
}
```

`edits` 只替换源中已有项，禁止用它覆盖材料或输运选择器。Cs 契约可以在真实所有者下新增已验证的可选块，保留已有未修改项。其他组分/材料/求解器组合失败时报告缺口，不猜新键。温度边界、固定步长开关、写出间隔仍按当前卡片与题目明确填写，工具不隐式重设。

```bash
python3 "$MANDIFUEL_PLUGIN_ROOT/skills/prepare-offbeat-case/scripts/parameter_plan.py" run --source source-case --case case --request plan.json --command bash Allrun
```

`--command` 之后为已确认的纯计算配方，正常包含 blockMesh 和 OFFBEAT；保留现有启动记账入口，默认不限制真实启动次数，不用额外的试算验证参数。长操作首次提交就设置 DSH `run_in_background: true`，随后复用其句柄。不要读取工具实现、重复改卡或回读。

只准备时将 `run` 改为 `prepare` 并省略 `--command`。已有相同计划、源和未改变输入时工具复用准备记录，不再改写或回读；已有目标不匹配时保留原目录，需新的独立目标。已有执行失败不自动重试，修复后使用独立目标继续；每次真实启动均记录，仅遵守用户明确设置的限制。

## 证据和交付

- `.mandifuel-preparation.json`：计划、源和输入哈希、契约范围、逐项原生回读。状态 `input_readback_only` 不代表物理生效。
- `.mandifuel-execution.json`：公共执行器真实退出码、正常结束和实际终态。重复执行调用复用记录，不增加求解。
- `.mandifuel-verification.json`：正常完成后所有保留正时间的实际 `diffCs` 范围与量纲，以及请求的 T、sourceCs 检查；不会用 `0/diffCs` 冒充实际值。失配返回 `mismatch`，不得宣称任务完成。

`cs_inventory: true` 为可选的已固化结果操作，仅用于以原点为球心、从 0 开始、均匀初始 Cs、无持续生成的任务；必须同时请求 `sourceCs: 0` 实际检查。通过验证才调用现成结果 API，输出 `results/cs_radial_profile.csv`（r、Cs、体积均标单位）和 `results/cs_inventory.json`（初始/终态 mol、相对外释分数）。库存为实际网格计算域；扇区或楔形不自动放大为整球，需整球等效值时明确换算和假设。初始浓度取源中实际拼写 `intialFpConcentration/Cs`。非均匀初态、重启、其他结果需求交给通用 Extract，不强套此操作。

CLI 的运行返回为紧凑摘要，完整逐项证据留文件。只在 `mismatch`、失败或未覆盖时读取相应证据；成功时直接交付，不再逐项展开、重新检查安装或查找实现。需要对已有执行复核时用 `verify --case case`，不重新求解。
