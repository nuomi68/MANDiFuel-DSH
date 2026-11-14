# 软件能力表：当前本地 OFFBEAT

仅为声明安装的已知能力索引。执行通过不证明所有组合/精度；未列出不等于不支持。运行助手查询本表，不读取维护源码。

维护时间：2026-11-14T14:57:54.756401+08:00。配置档：`local-offbeat-openfoam-v2506`。

安装身份由维护阶段记录；运行助手沿用启动器已准备环境，不为查询本表重复检查安装或源码。升级软件/加载新扩展后应由维护者更新配置档，不能把旧注册事实强套到新安装。

证据级别：runtime_verified=本机执行通过；registered=本机注册确认；documented=本地说明；input_observed=源卡出现；unverified=待核实。源卡出现仅证明语法被写过；本机执行通过仅覆盖记录中的组合。

## 任务意图与可组合操作

| 意图ID | 目的 | 已知操作 | 限制 |
|---|---|---|---|
| disable_mechanics | 关闭力学方程 | mechanicsSolver constant；兼容旧 fromLatestTime | 保留已有位移状态；不自动关闭气体模型、热边界或其他物理模块。 |
| thermal_only | 纯热学准备 | 保留/选择适用热模型；固定力学状态；按请求关闭热应变；沿用内部热耦合和所需物性 | 没有气隙实体热容不等于不需要气体导热物性。 |
| prescribed_temperature | 给定温度 | thermalSolver constant；按请求设置起始 T 与对应边界 | 不自动把所有功率、燃耗、通量清零。 |
| constant_power | 恒定线功率 | 已用 constantLhgr 时使用标量；已用 timeDependentLhgr 时让配对值恒定；源值已满足就复用 | 不为整理格式重写模型和时间节点，保留已有稍后末点。 |
| fixed_step | 固定步长瞬态 | deltaT 为请求模型时间步长；关闭已有自适应开关；采用请求的瞬态格式和写出方式 | 模型时间与物理秒分开；正常终态以执行器证据为准。 |
| steady_thermal | 稳态热学 | ddtSchemes/default steadyState；沿用相同几何、界面和物性；按请求设置功率和边界 | 不是必须额外试算的特殊任务，也不是把所有模型改为 none。 |
| restart | 物理续算 | 保留完整检查点状态与输入；独立目标、不继承旧执行凭据；不执行会清理状态的生成/清理步骤 | 不能仅复制T/D；未验证的活跃耦合模型续算不被一般成功记录覆盖。 |
| cs_constant_diffusion | 单UO2/Cs常扩散 | 使用 fpdiffusion-cs-constant-v1 公共入口；运行后核实 diffCs、T、sourceCs | 只在声明适用范围内，未知材料组合走一般输入/运行反馈。 |
| change_rod_geometry | 棒尺寸修改 | 修改 rodDict 等生成器输入；已有冷态直径/间隙同步；必要几何锚定采样点同步 | 保留轴向结构和无关材料/载荷，生成器负责派生网格。 |
| energy_increment | 常密度比热热能增量 | 确认rho、Cp在本次范围为常数；按实际cellZone求rho*Cp*sum((T-T0)*V) | 单位J；只积分真实实体域，不自动加入气隙热容或放大到整棒。 |

## 依赖、风险与已知限制

| 规则 | 类别 | 条件 | 处理 |
|---|---|---|---|
| selector_not_universal | 错误 | 关闭方式按具体选择器 | mechanicsSolver none 本机已证实非法；gapGas/fgr/neutronics 等的 none 另有各自含义。 |
| fuelRodGap_gas | 错误 | solidConduction 实际评价 fuelRodGap 且 gapGas none | 缺少气体导热物性会失败。温度方程固定、未评价该边界时不凭边界名字强制开启气体模型。 |
| minimal_changes | 原则 | 源输入已经满足请求 | 保持原值和时间网格；每项改动对应用户要求或已证实依赖。 |
| heat_time_coverage | 风险 | 时变线功率表末点等于或早于终点 | 本机已出现查下一标记越界；保留现有更晚末点。相等不一概认定每个配方必失败，需结合具体时步/模型。 |
| rhoCp_constant | 范围 | 热能增量用rho*Cp*DeltaT | 只适用于已确认常数物性；温变Cp需要模型一致的焓/积分定义。 |
| displacement_field | 依赖 | 增量/更新拉格朗日力学 | 使用DD初边界和相应求解项，不能把D机械复制为标量场。 |
| materials_zones | 依赖 | materialProperties byZone | 实际分区与材料项对应；固定材料合法不代表任意温度/辐照条件均适用。 |
| coupled_patches | 依赖 | 区域耦合界面 | 几何配对、neighbourPatch/neighbourRegion及owner信息按源保持；必要配方changeDictionary不能遗漏。 |
| sampling_compatibility | 已知兼容风险 | 本机OpenFOAM v2506旧采样输入 | 已遇到lineUniform不被注册、patchProbes缺patch而仅给patchName；用支持语法或适用的已有场提取，不为此改物理。 |
| empty_patch_metadata | 工具限制 | list_scopes遇到0面defaultFaces | 函数存在，但当前范围查询可抛解析异常。该网格已由原生工具正常运行；不把它当物理坏网格，不为查询重算。 |
| field_scope | 语义 | 边界/材料区/全域响应 | 不能用内部占位值替代边界，不能用探针替代全区最大单元值。 |
| execution_evidence | 完成 | 退出码、正常结束、实际终点三项结合 | 失败运行即使已写终态目录仍为失败；输入回读不代表物理生效。 |
| uncovered | 恢复 | 本表没有条目或仅有源卡观察 | 这不构成拒绝任务的理由；保留源、定点查资料、按允许范围运行并修复，默认不限启动次数。 |

## 局部资料的边界

- 时间控制和离散格式的本地官方页面尚为空页；相关条目依据已维护协议、输入与运行证据。
- elementTransport本地说明未列FpDiffusion；该能力由实际输入/运行与已验证契约补充。
- 本地后处理说明有BU/BUkgU等命名和单位差异，确切Bu以现有核实约定为准，Bu_kgU待核实。
- list_scopes存在，空defaultFaces异常属于当前解析器范围查询限制，不是方法缺失。
- 模型名和property key区分大小写，例如源中PoissonRatioModel和poissonRatioModel不能擅自归并。
- 手册constant材料列出的所有required项与可运行源并不完全一致；不凭旧列表补造未需要的参数。
- 没有对文档/源卡列出的全部模型逐个求解，不宣称穷举注册表或完整参数验证。

仅核对本次改动及直接依赖，不把该表转成逐项探索清单。已完成算例不因新提示重算。没有覆盖的值先标未核实，按原源和运行反馈推进；未知能力不是默认拒绝项。
