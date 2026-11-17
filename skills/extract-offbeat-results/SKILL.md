---
name: extract-offbeat-results
description: 从已有 OFFBEAT/OpenFOAM 结果提取温度、位移、应力、间隙、气体状态及其历史、极值或派生响应时使用，也适用于已有结果对比。确定对象、时间、范围和单位后复用公共 API；不为后处理问题重复求解。
---

# 提取请求的物理响应

全程离线，使用本地单位表与接口契约。直接消费 Execute 已确认的结果根、实际 `final_time` 和已有响应，不重新检查运行环境，也不读解析器或物理模型源码来确认常见输出。下面是可直接调用的接口契约。禁止查看或修改解析器、插件或物理模型实现；报错只检查参数、结果元数据与本地契约，仍无法解释时保留成功数据并报告缺口。

## `results` 类的必经工作流

只分析已有结果时命中本类；单算例与研究任务的响应提取也使用本技能。比较多棵已有结果树仍属结果分析，不因“多工况”字样启动 Study。其他未覆盖任务不继承本工作流。

1. **接收证据**：确认结果根和已知运行状态，复用已保存响应及选择；缺少字段不触发新的求解。
2. **固定选择**：明确对象、时间、范围、分量、归约和单位；只有选择未确定时批量读取相关元数据。
3. **批量提取**：用下述公共 API 在一个回调或脚本返回所需映射，区分正常结果与失败运行的诊断场。
4. **保留与产出**：保存响应和选择，表、图、报告使用同一映射；已有响应直接复用，新增量集中读取。
5. **核对交付**：请求响应都有可追溯数值或明确不可用原因，才结束本阶段。部分数据不能冒充完整成功；提取或绘图失败只修复对应阶段。

## 复用参数计划已提取的响应

参数计划返回 `status=verified` 且已生成 Cs 库存和径向表时，直接复用其带单位的 JSON/CSV 写交付说明；不用再次遍历场、重建网格或编写等价提取脚本。只有未覆盖的额外响应才调用下述通用 API。

## 使用公共接口

当前导出签名和已知兼容限制见[能力表的公共工具页](../prepare-offbeat-case/references/software-capabilities/public-tools.md)，字段作用域和单位见[字段页](../prepare-offbeat-case/references/software-capabilities/fields-and-units.md)。`list_scopes`确实存在，空defaultFaces可能触发当前解析器异常，不能据此判断函数不存在或重算物理过程；按本页已有字段/原生条目入口继续。

从本技能 `scripts/result_api.py` 导入公共 API。普通响应直接调用接口，不重写 OpenFOAM 场或网格解析器。多个已知响应放入一个回调或脚本，返回小型映射；批量提取可能超过前台超时时从第一次就使用 `run_in_background: true` 与原生句柄等待；同一场的多个统计复用一次读取的帧，不为每个极值或表格重新解析；只有选择尚未确定时才读取相应元数据。

```python
import sys
from pathlib import Path
import os

PLUGIN = Path(os.environ['MANDIFUEL_PLUGIN_ROOT'])
sys.path.insert(0, str(PLUGIN / 'skills/extract-offbeat-results/scripts'))
import result_api

def extract_reporting(result_root):
    return {
        'fuel_T_max_K': result_api.extreme(result_root, 'T', operation='max',
                                         time='1', scope=('cellZone', 'fuel')),
        'cladding_T_max_K': result_api.extreme(result_root, 'T', operation='max',
                                             time='1', scope=('cellZone', 'cladding')),
    }
```

示例的时间、材料区名和字段必须替换为本题确认的选择；一个标量也可直接返回浮点数。`time='1'` 不是通用终态约定，精确终态应使用 Execute 已确认的目录单位终点。

`read_field(root, variable, *, time='latest', scope='internal', component='value', location=None, owner_zone=None, entry_name='value', include_volumes=False)` 返回 `FieldFrame`；`time='all'` 返回帧元组。帧字段为 `variable`、`time`、`scope`、`component`、`unit`、`labels`、`coordinates`、`values` 和 `volumes`。`values` 是所选标量分量的浮点元组；`volumes` 默认 `None`，请求后为对齐的立方米权重。`extreme` 默认返回浮点数，`details=True` 返回详细结果字典。

| 体场类型 | `component` |
|---|---|
| 标量 | `value` |
| 向量 | `x`、`y`、`z` |
| 对称张量 | `xx`、`xy`、`xz`、`yy`、`yz`、`zz`；或 `principal_max` |
| 完整张量 | `xx`、`xy`、`xz`、`yx`、`yy`、`yz`、`zx`、`zy`、`zz` |

接口不提供 `mag` 分量；需要向量幅值时从同一选择的三个分量计算。分量和公式未被请求时不附加。

## 先固定响应语义

选择包括原生对象或公式、物理范围、模型时间、分量、归约和单位。共享的时间窗口约束适用于该窗口内每项响应。

| 接口 | 用途 |
|---|---|
| `list_times(root, variable=None, source='fields')` | 查找实际可用时间，可按字段筛选 |
| `list_variables(root, time='latest')` | 查找某时刻字段 |
| `list_scopes(root, time='latest')` | 返回含 `cellZones` 与 `patches` 的映射 |
| `read_field(root, variable, ...)` | 读取值及对齐的单元标签、坐标 |
| `extreme(root, variable, operation=..., ...)` | 直接返回标量极值，可要求详细位置 |
| `iter_fields(root, variable, time='all', ...)` | 逐帧读取历史 |

`time` 接受精确模型时间、`'latest'` 或支持历史的接口中的 `'all'`。`scope='internal'` 表示整个内部单元域，`('cellZone', name)` 表示指定材料区，`('patch', name)` 表示边界；边界选择可提供 `owner_zone`。`location=(x,y,z)` 在所选单元范围内取最近存储单元中心。

材料区极值使用真实 cellZone 成员，包含贴边单元；不能用内侧径向环、探针或边界所有者子集替代全区。只有请求明确限定这些范围时才缩小。边界问题使用边界值，不能用同一文件的内部占位值替代。

### 面场与原始边界条目

上面的薄接口主要面向体场；`list_variables` 不列出 `surfaceScalarField`，不能因此宣布该物理量不存在。只有所需范围未知时读取目标结果目录的场头和边界名一次。

面场（例如 `oxideThickness`），或被薄接口拒绝但只需读取存储边界条目的情况，直接使用已安装的原生字典工具：

```bash
foamDictionary ./case/实际终态目录/oxideThickness -disableFunctionEntries -no-libs -noFunctionObjects -entry dimensions -value
foamDictionary ./case/实际终态目录/oxideThickness -disableFunctionEntries -no-libs -noFunctionObjects -entry boundaryField/cladOuter/value -value
```

用本题实际目录和边界名替换示例。`uniform 数值` 即该边界的存储值；`nonuniform` 列表保留其面值，可按请求做最大值等不依赖面积的归约。长度维度 `[0 1 0 0 0 0 0]` 对应米，换成微米乘 `1e6`。不要为读取一个均匀边界值重建全部网格、读腐蚀源码或补写原始网格元数据。需要面积加权、标签对齐或位置时仍须有相应网格证据；原始条目读取不能冒充这些操作。

解析器报告缺少边界双向元数据时，若用户只要原始边界值，使用此入口；若用户需要依赖该拓扑的量，则报告具体缺口。先确认所需选择可读，再批量提取；某项失败保留已成功响应，只重做该项，不重复整份统计。

## 分量、符号与时间

`operation='max_abs'` 默认返回非负幅值；`details=True` 的 `matches` 保留带符号的值。普通最大值保留代数符号。

标准 OFFBEAT 力学输出笛卡尔对称应力 `sigma`，单位 Pa；启用 `mechanicsSolverOptions/cylindricalStress on` 后另写 `sigmaCyl`，基底为绕z轴的径向、环向、轴向。最大主应力使用 `sigma`、`component='principal_max'`；环向应力使用 `sigmaCyl`、`component='hoop'`。仅拉伸量在主值选择后再取 `max(0, value)`。`principal_max` 也支持其他对称单元张量。

单个时刻的空间最大值回答状态问题；`time='all'` 回答已保存帧上的时间与空间极值，若零时刻存在该字段也包含零时刻。需要窗口时按各帧模型时间筛选。不同算例甚至不同字段的保存时刻可以不同；先用 `list_times(root, variable=...)` 确认。

稀疏写出不能证明连续历史峰值或单调演化，探针也不等于材料区全域。燃料单元最大温度不是精确中心线温度。具体边界、Decimal、体积平均和历史对齐见[高级选择](references/openfoam-result-discovery.md)。维度不足以确定单位时直接采用[已核实单位表](references/offbeat-result-units.md)，其出处不要求每题重查；未覆盖且无法核实的单位明确标记，不遍历源码。

## 保留并复用响应

将成功响应及其选择一起保留，导出、绘图和报告使用同一映射。复用前确认提取公式、区域归属和库存换算口径没有改变；定义变化后，旧 reporting_response 不代表新口径，应在已有场上重新提取所需响应。公共 API 的历史几何缓存只在单次调用内复用同一版本网格，不缓存跨调用的物理响应或报告。研究已保存的响应不重复调用 API；新增量是新的选择，可在保留结果上集中提取。

精确时间键、字段、范围、分量、符号和并列项遵循精确选择语义；派生均值、体积或比例采用任务容差与数据数值精度，不能以小数字符串完全相同当作准确性标准。缺失响应明确返回不可用状态，并与求解状态分开。
