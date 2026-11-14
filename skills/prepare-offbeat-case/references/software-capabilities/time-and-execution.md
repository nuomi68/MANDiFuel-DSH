# 软件能力表：当前本地 OFFBEAT

仅为声明安装的已知能力索引。执行通过不证明所有组合/精度；未列出不等于不支持。运行助手查询本表，不读取维护源码。

维护时间：2026-11-14T14:57:54.756401+08:00。配置档：`local-offbeat-openfoam-v2506`。

安装身份由维护阶段记录；运行助手沿用启动器已准备环境，不为查询本表重复检查安装或源码。升级软件/加载新扩展后应由维护者更新配置档，不能把旧注册事实强套到新安装。

证据级别：runtime_verified=本机执行通过；registered=本机注册确认；documented=本地说明；input_observed=源卡出现；unverified=待核实。源卡出现仅证明语法被写过；本机执行通过仅覆盖记录中的组合。

## 时间、控制与完成

| 文件 | 条目 | 值/单位 | 说明 |
|---|---|---|---|
| system/controlDict | startFrom | startTime / latestTime | 选择新鲜起点或保留状态，不能混入更晚目录。 |
| system/controlDict | startTime | 模型时间 | 新鲜计算通常为0；续算按可信检查点。 |
| system/controlDict | endTime | 模型时间 | 不等于裁剪载荷表，也不能只凭该值证明完成。 |
| system/controlDict | deltaT | 模型时间 | 物理秒转换由 userTime 决定。 |
| system/controlDict | userTime/type | seconds / hours / days | 缺省沿源秒制；days 已有本机运行验证，hours 仅接口约定；其他类型不猜。 |
| system/controlDict | adjustableTimeStep | off / false 或 on / true | 请求固定步长时关闭；不凭空新增不存在的其他开关。 |
| system/controlDict | adjustableWriteTimeStep | 若源存在则 false | 附加写出时间控制，不是 writeControl 的枚举值。 |
| system/controlDict | writeControl | timeStep / runTime / adjustableRunTime 等 | 每步输出可用 timeStep；精确模型间隔按现有说明选择。 |
| system/controlDict | writeInterval | 与 writeControl 对应 | 不是所有模式都按秒解释。 |
| system/controlDict | purgeWrite | 非负整数 | 需全部保存帧时用0；保留结果不能靠反复重算补齐。 |
| system/controlDict | writeFormat / writeCompression | ascii；off | 只在用户需要相应交付格式时设置。 |
| system/controlDict | timePrecision / writePrecision | 显示与序列化精度 | 不能为日志或目录显示尾数重算已完成物理过程。 |
| system/fvSchemes | ddtSchemes/default | Euler / steadyState 等 | Euler 是瞬态时间离散；steadyState 是稳态离散，不把伪时间序列当真实瞬态。 |
| system/fvSolution | solvers/<field> | 字段对应的线性求解与阈值 | D/DD/T 与所选模型一致，阈值沿源与请求。 |
| system/fvSolution | stressAnalysis | maxOuterIter、T、D、relT 等源项 | 名称随本机输入，未请求时保留；不靠随意放宽精度换成功。 |
| constant/solverDict | heatSourceOptions/timePoints | 模型时间列表 | 与时间载荷配对；已有更晚有效末点应保留。 |
| constant/solverDict | heatSourceOptions/lhgr | 标量或列表，依 heatSource | constantLhgr 标量，timeDependentLhgr 列表；kW/m 转 W/m 乘1000。 |
| constant/solverDict | heatSourceOptions/vhgr | W/m³ | 用于相应体积热源模型，不能与线功率直接互换。 |
| constant/solverDict | rheologyOptions/thermalExpansion | off / on | 控制热应变，与 mechanicsSolver 是否求位移分开。 |

## 时间覆盖

模型时间与物理秒分开：seconds×1，hours×3600，days×86400。改userTime时所有引用历史必须保持原物理含义，不能只改单位名。没有单位项时沿源秒制。

源的功率和时间表已经覆盖请求区间就保留，不因endTime变小而截断。当前安装的时变线功率在恰好到达末节点时曾因查询下一标记越界；需要新建表时保留区间外有效尾点，或采用已验证的具体端点处理。该观察不等于每个模型/每种步长的相等末点都必失败。

## 续算与恢复

续算保留整个检查点状态、网格、材料和必要根文件；不只带T/D。续算配方不能重新生成会覆盖状态的网格，独立目标不继承旧执行凭据作为新尝试。

正常完成结合退出0、正常结束标记和实际终态。执行器在受限舍入容差内返回真实目录名，提取沿用该名。已有末时刻文件但执行失败仍保留失败；不用显示精度或报告格式触发重算。

默认不限制真实求解启动次数。有具体输入修复后新尝试继续，已成功结果复用。详见[恢复闭环](../../../execute-offbeat-case/references/input-recovery.md)与[时间配方](../../../execute-offbeat-case/references/time-and-restart.md)。
