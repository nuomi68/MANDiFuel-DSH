# OFFBEAT 输出单位依据

当确切字段或明确作用域的结果量无法由七指数 `dimensions` 确定单位时，才使用本表。本版本部分物理量未完整标注维度，全零或无法映射的向量不能独立证明它无量纲。

本表是受支持快照已经核实的接口约定，计算时直接采用。右列源码位置只供技能维护追溯，不是 agent 每次需要打开的文件或额外验证清单。

字段名称区分大小写，不将表项扩展到别名或物理意义相似的量。间隙气体一行仅适用于已解析的 `gasPressure`，或其包含对象明确标识为间隙气体状态的压力项，不适用于普通压力场。

| 确切字段或明确作用域的量 | 单位 | 相对官方源树的依据 |
|---|---|---|
| `Bu` | `MWd/MT_oxide` | `mkdocs/docs/user_guide/solverDict/burnup.md:4`；`offbeatLib/burnup/burnupLassmann.H:65-67` |
| `gapWidth` | `m` | `mkdocs/docs/user_guide/data_processing/index.md:27`；`offbeatLib/physicsSubSolvers/mechanicsSubSolver/mechanicsSubSolver.C:640-655,1475-1485` 也说明了为何不能据全零维度判无量纲 |
| `interfaceP` | `Pa` | `mkdocs/docs/user_guide/data_processing/index.md:27` |
| `sigma` | `Pa` | `mkdocs/docs/user_guide/data_processing/index.md:25` |
| `sigmaEq` | `Pa` | 同上 |
| `sigmaHyd` | `Pa` | 同上 |
| `sigmaY` | `Pa` | 同上 |
| 间隙气体的 `gasPressure` | `Pa` | `offbeatLib/gapGasModel/gapGasModel.H:133-134` |

本快照不能为 `Bu_kgU` 给出已核实单位，普通计算将其标为 `unit_unverified`，不为此展开源码搜索。以下是维护时已记录的冲突：`burnupLassmann.H:219-220` 声明 `MWd/kgU`，而 `burnupLassmann.C:796,806,812` 描述 `MWd/MTU` 且只应用铀分数0.8815换算；官方验证脚本 `Cases/Verification/burnupFBR/plot.py:19-21,57-58,73` 在按 `MWd/kgHM` 比较前又除以1000。只有用户要求单位考证或相应维护任务时再调查，不能猜测单位后计入已核实响应。
