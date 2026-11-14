# 软件能力表：当前本地 OFFBEAT

仅为声明安装的已知能力索引。执行通过不证明所有组合/精度；未列出不等于不支持。运行助手查询本表，不读取维护源码。

维护时间：2026-11-14T14:57:54.756401+08:00。配置档：`local-offbeat-openfoam-v2506`。

安装身份由维护阶段记录；运行助手沿用启动器已准备环境，不为查询本表重复检查安装或源码。升级软件/加载新扩展后应由维护者更新配置档，不能把旧注册事实强套到新安装。

证据级别：runtime_verified=本机执行通过；registered=本机注册确认；documented=本地说明；input_observed=源卡出现；unverified=待核实。源卡出现仅证明语法被写过；本机执行通过仅覆盖记录中的组合。

## 模型选择器

不要把 none 当成所有模块的关闭值；constant 通常是沿用状态，也不等于数值清零。

### thermalSolver：温度方程

输入：`constant/solverDict` → `thermalSolver`。关联输入：0/T；thermalSolverOptions；heatSource 与 Q、T 边界。

已知停用/固定入口：`constant`，仍须按下表语义与依赖使用。

| 值 | 证据 | 语义 |
|---|---|---|
| constant | 本机执行通过 | 不解温度方程，读取并沿用起始 T；固定均匀温度时同时确认内部场和所需边界。 |
| fromLatestTime | 本机执行通过 | 旧名，兼容映射到 constant。 |
| readTemperature | 本地说明 | 逐时读取 constant 子目录中的给定温度场；按源配方确定目录结构。 |
| solidConduction | 本机执行通过 | 求固体导热方程，可使用体积热源 Q。 |

### mechanicsSolver：动量平衡/位移

输入：`constant/solverDict` → `mechanicsSolver`。关联输入：0/D 或 0/DD；mechanicsSolverOptions；rheologyOptions；system/fvSolution 对应字段求解设置。

已知停用/固定入口：`constant`，仍须按下表语义与依赖使用。

本机已确认非法：`none`：本机合法类型列表和实际初始化失败已确认；不要用通用关闭词猜值。

| 值 | 证据 | 语义 |
|---|---|---|
| constant | 本机执行通过 | 不解位移方程，沿用已有位移状态；不等于把已有 D 清零。 |
| fromLatestTime | 本机执行通过 | 旧输入兼容映射到 constant。 |
| largeStrainTotLag | 本机注册确认 | 总位移 D，总拉格朗日大应变；不更新计算网格。 |
| largeStrainUpdLag | 本机注册确认 | 增量位移 DD，更新拉格朗日大应变，更新网格。 |
| smallStrain | 本机执行通过 | 总位移 D，小应变，计算网格不更新。 |
| smallStrainIncrementalUpdated | 本机注册确认 | 增量位移 DD，小应变并更新网格。 |

### neutronicsSolver：中子学

输入：`constant/solverDict` → `neutronicsSolver`。关联输入：对应源中的中子通量初场；neutronicsSolverOptions；与 fastFlux 分开。

已知停用/固定入口：`none`，仍须按下表语义与依赖使用。

| 值 | 证据 | 语义 |
|---|---|---|
| diffusion | 本地说明 | 单群中子扩散；所需场和系数沿对应源卡。 |
| fromLatestTime | 本机执行通过 | 本机已接受的旧输入，初始化日志选择 none。 |
| none | 本机执行通过 | 不求中子方程；不据此推断其他给定通量也被清零。 |

### elementTransport：元素/裂变产物迁移

输入：`constant/solverDict` → `elementTransport`。关联输入：elementTransportOptions/solvers；对应模型 Options、初态和材料参数。

已知停用/固定入口：`none`，仍须按下表语义与依赖使用。

| 值 | 证据 | 语义 |
|---|---|---|
| byList | 本机执行通过 | 由 elementTransportOptions/solvers 列表启用具体输运方程。 |
| fromLatestTime | 本机执行通过 | 旧输入兼容；本机初始化选择 none。 |
| none | 本机执行通过 | 本机已接受的停用输运选择。 |

### materialProperties：材料分区

输入：`constant/solverDict` → `materialProperties`。关联输入：materials/<zone>/material；constant/polyMesh/cellZones。

| 值 | 证据 | 语义 |
|---|---|---|
| byZone | 本机执行通过 | 按 cellZone 绑定材料；分区名称和 materials 中的材料项必须对应。 |

### rheology：本构组织方式

输入：`constant/solverDict` → `rheology`。关联输入：materials/<zone>/rheologyModel；materials/<zone>/rheologyModelOptions；rheologyOptions。

| 值 | 证据 | 语义 |
|---|---|---|
| byMaterial | 本机执行通过 | 本构在每个 materials/<zone>/rheologyModel 中选择。 |

### heatSource：体积热源

输入：`constant/solverDict` → `heatSource`。关联输入：起始 Q 或 heatSourceOptions；lhgr / vhgr 与 timePoints；axialProfile / radialProfile / materials。

已知停用/固定入口：`none`，仍须按下表语义与依赖使用。

| 值 | 证据 | 语义 |
|---|---|---|
| constant | 本地说明 | 沿用起始 Q 场，不等于零功率。 |
| constantLhgr | 本机执行通过 | 恒定线功率，heatSourceOptions/lhgr 为标量；实际本机输入已确认。 |
| fromLatestTime | 本机执行通过 | 旧名，兼容 constant。 |
| laserHeatSource | 源卡出现 | 源卡中出现的激光热源；未独立验证构造参数和适用范围。 |
| none | 本地说明 | 本地说明中的无热源选择；不创建 Q，尚未用本机正常记录独立验证该组合。 |
| timeDependentLhgr | 本机执行通过 | 线功率时间表：timePoints 与 lhgr 为配对列表，可叠加空间分布。 |
| timeDependentVhgr | 本地说明 | 体积热源时间表，输入 vhgr 单位 W/m³；具体表格结构按源。 |

### burnup：燃耗

输入：`constant/solverDict` → `burnup`。关联输入：burnupOptions；热源、密度及核素输入；实际 Bu 字段单位。

已知停用/固定入口：`none`，仍须按下表语义与依赖使用。

| 值 | 证据 | 语义 |
|---|---|---|
| Lassmann | 本地说明 | 简化核素耗损与径向形状因子模型。 |
| LassmannFBR | 源卡出现 | 快堆相关燃耗模型，源卡存在；完整参数及当前注册待核实。 |
| constant | 本机执行通过 | 从起始 Bu 沿用燃耗；不等于清零。 |
| fromLatestTime | 本机执行通过 | 旧名，本机选择 constant。 |
| fromPower | 本地说明 | 由热源推进燃耗。 |
| none | 本机执行通过 | 不推进/不创建燃耗场（本地说明）。 |

### fastFlux：快通量与快注量

输入：`constant/solverDict` → `fastFlux`。关联输入：fastFluxOptions/timePoints、fastFlux；fastFluxOptions/axialProfile；起始 fastFlux / fastFluence 与本构单位约定。

已知停用/固定入口：`none`，仍须按下表语义与依赖使用。

| 值 | 证据 | 语义 |
|---|---|---|
| constant | 本机执行通过 | 沿用给定 fastFlux；fastFluence 仍可随时间累积，不能当作注量冻结。 |
| fromLatestTime | 本机执行通过 | 旧名，本机选择 constant。 |
| none | 本地说明 | 本地说明中的停用选择。 |
| timeDependentAxialProfile | 本地说明 | 给定平均快通量历史及轴向分布。 |

### corrosion：边界腐蚀/氧化生长

输入：`constant/solverDict` → `corrosion`。关联输入：corrosionOptions/patches/<patch>/corrosionModel；oxidationKineticsModel；温度边界与 oxideThickness 作用域。

| 值 | 证据 | 语义 |
|---|---|---|
| byPatch | 本机执行通过 | 按 corrosionOptions/patches/<patch> 配置腐蚀模型和动力学。 |
| constant | 源卡出现 | 源卡存在的固定腐蚀状态模式；本机 fromLatestTime 初始化也选择 constant。 |
| fromLatestTime | 本机执行通过 | 已执行的旧固定状态选择；不要自行更换为未核实的 none。 |

### gapGas：间隙气体状态与物性

输入：`constant/solverDict` → `gapGas`。关联输入：0/gapGas；gapGasOptions；调用气体物性的热边界、几何和 FGR。

已知停用/固定入口：`none`，仍须按下表语义与依赖使用。

| 值 | 证据 | 语义 |
|---|---|---|
| FRAPCON | 本机执行通过 | 棒状燃料间隙/气室的体积、压力、温度、组成及气体物性。 |
| TRISO | 本地说明 | TRISO Buffer—IPyC 间隙气体模型（本地说明和源卡）。 |
| none | 本机执行通过 | 不提供有效气体导热物性；气体模型使用者被评价时可能失败。 |

### fgr：裂变气体释放

输入：`constant/solverDict` → `fgr`。关联输入：算例根 input_settings.txt（存在时）；源中的气体/晶粒等耦合初态；fgrOptions 与气体模型。

已知停用/固定入口：`none`，仍须按下表语义与依赖使用。

| 值 | 证据 | 语义 |
|---|---|---|
| SCIANTIX | 本地说明 | 调用 SCIANTIX 局部气体演化模型；保留源中的根输入和耦合初态。 |
| SCIANTIXRIA | 本地说明 | RIA 相关阈值释放，读取 SCIANTIX 初态；本地说明，尚未独立运行验证。 |
| none | 本机执行通过 | 不计算裂变气体释放；不是关闭 gas 导热模型的同义操作。 |

### sliceMapper：三维网格到轴向切片的映射

输入：`constant/solverDict` → `sliceMapper`。关联输入：globalOptions/pinDirection；materials/<zone>/nSlices 等；依赖切片的热源、本构或燃耗模型。

已知停用/固定入口：`none`，仍须按下表语义与依赖使用。

| 值 | 证据 | 语义 |
|---|---|---|
| autoAxialSlices | 本机执行通过 | 按材料和单元轴向位置自动分组。 |
| byMaterial | 本机执行通过 | 在材料项定义 nSlices 等切片参数。 |
| byPellets | 本地说明 | 按芯块高度划分切片，参数按源。 |
| none | 本机执行通过 | 不建立映射；需要切片平均或轴向力平衡的模型不能据此认为不依赖映射。 |

## 输运子模型与空间分布

`elementTransport byList` 的子列表在 `elementTransportOptions/solvers`。FpDiffusion 已执行确认；porosityTransport、PuRedistribution、AmRedistribution 在本地说明中列出，未逐个实跑。FpDiffusion 的具体字段与已验证单UO2/Cs参数见参数契约，不能向其他元素材料直接推广。

空间分布常见 flat、constantTabulated、timeDependentTabulated；时间、轴向节点和data形状必须与具体type一致。常量表不是时变矩阵。新的空间分布不在本表逐个注册验证，使用源和相应输入绑定。
