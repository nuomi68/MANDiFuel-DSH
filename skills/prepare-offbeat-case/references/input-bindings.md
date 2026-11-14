# OFFBEAT 输入绑定

只读取请求变化对应的行，再沿当前模型、`#include` 和 `file` 定位实际定义。下表是常见新算例的路径，不覆盖所选模型的显式配置。Python 字面量 `rodDict`、`sphereDict` 不是 OpenFOAM 字典；使用有针对性的 Python 或文本修改。带键的 OpenFOAM 包含片段即使没有头部，也使用原生编辑器。

这里的“实际定义”指输入卡及其引用的数据文件，不是模型 C++ 构造函数。已有明确绑定直接采用；只为本题修改读取对应输入，不沿类型名称进入求解器源码。源中保留的物理选择器和载荷沿用，除非用户要求变更；不能因阅读实现自行开启额外物理模型。

| 请求变化 | 输入所有者 | 路径与含义 |
|---|---|---|
| Cs 常扩散系数（单 UO2 / FpDiffusion） | `constant/solverDict/materials/<zone>/fissionProductsTransport/Cs` | 已验证契约 `fpdiffusion-cs-constant-v1`：`d1=D`、`q1=d2=q2=0`，同级 `fissionProductsName (Cs)`；必须用[参数计划](parameter-plan.md)并核对实际 `diffCs`，不向位移场 `0/D` 写扩散系数 |
| 初始或边界温度 | `0/T` | `internalField` 初始化内部场；`boundaryField/<patch>` 定义热边界 |
| 位移约束、接触 | 按力学求解器选择 `0/D` 或 `0/DD` | `boundaryField/<patch>`；`gapContact` 可含 `frictionCoefficient` |
| 冷却剂压力 | 位移边界或 `constant/solverDict/rheologyOptions` 引用的表 | 沿 `coolantPressureList.file`，常见 `constant/systemPressure`，修改其压力数据 |
| 燃料棒冷态尺寸 | 生成器参数和 `materials/<fuel>` | 已有 `DiamCold`、`GapCold` 随对应半径、间隙一起更新，见生成器尺寸参考 |
| 初始间隙气体状态 | `0/gapGas` | `gasPressure` 单位Pa、`gasPressureType` 和质量分数 `massFractions`；`fromModel` 由气体模型演化压力 |
| 线功率或体积功率历史 | `constant/solverDict/heatSourceOptions` | 按所选 `heatSource` 使用配对的 `timePoints` 与 `lhgr`（W/m）或 `vhgr`（W/m³），并保留对应插值方式 |
| 给定快中子通量历史 | `fastFluxOptions` | 自身的 `timePoints`、`fastFlux`；已有 `0/neutronFlux0` 则属于求解通量场的初值和边界 |
| 轴向功率分布 | `heatSourceOptions/axialProfile` 及其包含文件 | 所选 `type`、`axialLocations`、分布时间点、`axialInterpolationMethod` 和数据一起定义分布，常见定义文件为 `constant/axialProfile` |
| 物理模型选择 | `constant/solverDict` | `thermalSolver`、`mechanicsSolver`、`heatSource`、`gapGas`、`fgr` 等顶层选择器及其选项 |
| SCIANTIX 开关 | 算例根的 `input_settings.txt`，若存在 | 保留耦合模型读取的设置文件 |
| 材料和本构 | `materials/<material-or-zone-group>` | 材料、参考温度、密度分数、富集度、导热、肿胀、蠕变、失效参数 |
| 时长、步长、重启、写出 | `system/controlDict` | `startFrom`、`startTime`、`endTime`、`deltaT`、自适应控制和写出设置 |
| 收敛、松弛 | `system/fvSolution` | `solvers`、`stressAnalysis` 等外修正设置和 `relaxationFactors` |
| 离散格式 | `system/fvSchemes` | 时间导数、梯度、散度和拉普拉斯格式 |
| 监测和采样 | `controlDict/functions` 或包含的 `system/probes`、`system/sample` | 字段及对象特有的 `axialPositions`、`probeLocations`、`points`、端点 |

## 载荷与状态的依赖

标准 ESI `coolantPressureList` 的 `interpolationScheme` 默认是 `linear`。`outOfBounds clamp` 在表外保持首末值，不是压力上限。位移边界与启用 `modifiedPlaneStrain on` 的流变模型可能共用同一文件，一次修改即可服务两者；显式配置优先，其他表类型使用自身选择器。

新鲜 FRAPCON 间隙气体中，缺少或非正 `gasMass` 时，模型由压力、组成、气体体积和温度初始化质量；正 `gasMass` 则给定初始库存。重启保留既有库存，明确重新充气时才使用新鲜初态输入。

只改变表格载荷的数值时保留既有时间网格。`endTime` 只控制停止，不等于截断载荷表；改变载荷水平或时长时保留模板已有的稍后终点，除非请求本身要求改网格或插值。kW/m 转成 `lhgr` 时乘1000。局部功率还受轴向、径向分布影响，输入回读和输出积分功率是不同证据。

`0/T` 中由所选 patch 类型确定实际载荷项：`fixedValue` 用 `value`；`uniformFixedValue` 用 `uniformValue`，它可能是时间表；`convectiveHTC` 用环境温度 `T0` 和 `h`；`radiativeConvectiveSink` 用 `T0`、`alpha`、`emissivity`。后两类的 `value` 是初始化值，不能替代载荷。使用真正覆盖请求表面的 patch 或带引号的 patch 组。网格字典定义名称，场文件定义物理条件。

请求精确等模型时间间隔输出时，使用 `writeControl adjustableRunTime`，并由模型时长和间隔数得到 `writeInterval`；可变步长下普通 `runTime` 可能错过精确时刻。

`constantTabulated` 读取一列平坦值列表，保留时间项并不会使它成为矩阵。`timeDependentTabulated` 的每行对应一个分布时间、每列对应一个轴向位置；静态替代重复相同行。`axialLocations` 通常是燃料高度的0至1归一化位置，其时间网格独立于LHGR。分段线性分布需要 `axialInterpolationMethod linear`，只改数值不会改变保留的 `step` 方式。

按所选插值和请求积分归一化分布，节点平均一般不等于空间平均。输入回读证明设置，额外输出功率分析是独立响应。保留无关的网格与幅值。

块堆叠 `rodMaker.py` 中，整段燃料高度比例 `f` 对应米制位置 `convertToMeters * (offsetFuel + f * sum(heightFuel))`。其他生成器或单块内比例使用真实原点和范围。只移动锚定几何特征的监测点；同一探针若在不同分布中同时出现，保持 `points` 和 `probeLocations` 一致。

## 原生编辑和回读

条目使用文件内部的斜线分隔路径：

```python
from foam_edit import set_foam_entry
readback = set_foam_entry(case, file='constant/solverDict',
                          entry='heatSourceOptions/lhgr', value='(0 18000 18000)')
```

返回包含 `file`、`entry` 和原生 `value` 回读。标量、列表、表格和整块字典使用 OpenFOAM 语法；CLI 不带 `--set` 或 `--set-file` 时仅回读。编辑定义文件，保留包含与宏不展开。原生写入可能归一化格式和数字拼写。

含 `timePoints`、`axialLocations`、`data` 的无头包含片段仍是带键字典，可以直接编辑 `data`。多行替代值文件只放值本身：

```bash
python3 "$MANDIFUEL_PLUGIN_ROOT/skills/prepare-offbeat-case/scripts/foam_edit.py" --case ./case --file constant/axialProfile --entry data --set-file matrix-value.txt
```

裸列表、新条目、要求周围文本逐字保持或不支持的语法，使用局部文本或 Python 编辑。`surfaces (data { point (...); ... });` 的 `surfaces` 是列表，可替换整个列表或选定文本；`surfaces/data/point`、`surfaces/0/point` 不是字典路径。文件名也不属于 `--entry`，例如 `system/controlDict` 中使用 `startFrom`，不使用 `controlDict/startFrom`。
