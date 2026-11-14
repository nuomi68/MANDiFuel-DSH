# 软件能力表：当前本地 OFFBEAT

仅为声明安装的已知能力索引。执行通过不证明所有组合/精度；未列出不等于不支持。运行助手查询本表，不读取维护源码。

维护时间：2026-11-14T14:57:54.756401+08:00。配置档：`local-offbeat-openfoam-v2506`。

安装身份由维护阶段记录；运行助手沿用启动器已准备环境，不为查询本表重复检查安装或源码。升级软件/加载新扩展后应由维护者更新配置档，不能把旧注册事实强套到新安装。

证据级别：runtime_verified=本机执行通过；registered=本机注册确认；documented=本地说明；input_observed=源卡出现；unverified=待核实。源卡出现仅证明语法被写过；本机执行通过仅覆盖记录中的组合。

## 材料与输入所有者

| 材料 | 证据 | 说明 |
|---|---|---|
| PyC | 源卡出现 | 热解碳材料，各向异性及辐照参数按源。 |
| SiC | 源卡出现 | 碳化硅涂层/试样材料；蠕变等不是仅选材料就自动确定。 |
| UO2 | 本机执行通过 | 二氧化铀燃料，默认物性和行为相关式按所选配置。 |
| UPuO2 | 源卡出现 | 混合氧化物燃料，相关式和燃料组成按源。 |
| buffer | 源卡出现 | TRISO缓冲层材料，名称大小写保留。 |
| constant | 本机执行通过 | 显式常数材料，常见rho、Cp、k、E、nu、alpha、Tref等沿完整源输入。 |
| Inconel 600 | 本地说明 | 本地手册列出的Inconel 600；当前源卡扫描未观察。（selector未确认，不提供可直接写入的值） |
| 钼（Molybdenum） | 本地说明 | 本地手册列出的钼材料；实际selector大小写需对应源确认。（selector未确认，不提供可直接写入的值） |
| steel1515Ti | 源卡出现 | 15-15Ti不锈钢材料，物性与本构按源。 |
| zircaloy | 本机执行通过 | 锆合金包壳，可包含相变、蠕变、生长等行为。 |

## 常用参数绑定

| 文件内路径（solverDict，除非另注明） | 单位/类型 | 作用与限制 |
|---|---|---|
| materials/<zone>/material | 材料类型 | 精确大小写；继承对应源中的完整属性和行为模型。 |
| materials/<zone>/rho | kg/m³ | constant 材料常用密度项。 |
| materials/<zone>/Cp | J/(kg·K) | constant 材料常用比热项。 |
| materials/<zone>/k | W/(m·K) | 热导率；UO2 等材料改常数时还需正确 conductivityModel。 |
| materials/<zone>/E | Pa | 杨氏模量；GPa乘1e9。 |
| materials/<zone>/nu | 1 | 泊松比；不按其他材料默认值替换。 |
| materials/<zone>/alpha | 1/K | 热膨胀系数，与热应变开关分开。 |
| materials/<zone>/Tref | K | 参考温度，沿用物理定义。 |
| materials/<zone>/DiamCold | m | 已有项随燃料外半径变化同步为2r。 |
| materials/<zone>/GapCold | m | 已有项为直径间隙2*(rCladInner-rFuelOuter)，不是径向间隙。 |
| materials/<zone>/rheologyModel | 本构名称 | 不是顶层 mechanicsSolver；弹性/塑性/蠕变配套。 |
| materials/<zone>/rheologyModelOptions/creepModel | 蠕变模型 | 保留对应通量、应力、温度、单位及 fluxConversionFactor。 |
| materials/<zone>/phaseTransitionModel | 相变模型 | ZyDynamic 在源卡出现；未做本机独立相变验证。 |
| materials/<zone>/fissionProductsTransport/Cs/{d1,q1,d2,q2} | 模型系数 | 单UO2/Cs已验证常D：d1=D，q1=d2=q2=0；别推广到所有材料/元素。 |
| elementTransportOptions/FpDiffusionOptions/intialFpConcentration/Cs | mol/m³ | 实际拼写 intial；不能自动改成 initial。 |
| elementTransportOptions/FpDiffusionOptions/outerPatches | patch 名称 | 沿源的扩散外表面配置；核对实际 Cs 边界。 |
| 0/gapGas/gasPressure | Pa | 明确的初始间隙气体压力。 |
| 0/gapGas/gasPressureType | 源定义 | 按源的状态初始化方式。 |
| 0/gapGas/massFractions | 质量分数 | 组分与气体模型兼容。 |
| gapGasOptions | 模型专属 | 几何/储气空间体积按实际计算域，不能直接塞整棒/整球值。 |
| heatSourceOptions/axialProfile | 空间分布 | type、axialLocations、timePoints、data、插值配套。 |
| heatSourceOptions/radialProfile | 径向形状 | 沿源归一化约定；不以节点算术平均替代积分平均。 |
| fastFluxOptions/{timePoints,fastFlux,axialProfile} | 模型时间和通量 | 与热源的时间网格分开，单位见字段说明。 |
| corrosionOptions/patches/<patch>/corrosionModel | 腐蚀模型 | 已验证源中有 zircaloyOuterCorrosion；对象是明确边界。 |
| corrosionOptions/patches/<patch>/oxidationKineticsModel | 动力学模型 | 源中存在 EPRI-KWU-CE\|Cathcart-Pawel 组合写法，保持确切字符串。 |

## 源卡中出现的物性和本构选择

以下均为源输入观察，不是全模型注册验证。大小写、嵌套路径和拼写照源保留，不由文件名或英文词推导selector。

| 材料项内的路径 | 观察值 |
|---|---|
| PoissonRatioModel | ZyConstant, constant |
| YoungModulusModel | PyCPARFUME, SiCPARFUME, UPuO2SckCen, constant |
| conductivityModel | BufferPARFUME, SiCPARFUME, UO2MATPRO, UPuO2Kato, UPuO2MagniMAMOX, constant |
| damageModel | isotropicCracking, mazars |
| densificationModel | UO2FRAPCON, empirical, none |
| densityModel | UO2Constant, constant |
| emissivityModel | ZyConstant, constant |
| failureModel | ZyOverstrainBISON, none |
| heatCapacityModel | SiCSnead, UO2MATPRO, constant |
| phaseTransitionModel | ZyDynamic, none |
| poissonRatioModel | constant |
| poreVelocityModel | UO2Sens, constant, none, vaporPressureMOX |
| relocationModel | UO2FRAPCON, none |
| rheologyModel | elasticity, misesPlasticCreep, misesPlasticity, neoHookeanMisesPlasticity |
| rheologyModelOptions/creepModel | LimbackCreepModel, LimbackCreepModelLOCA, MatproCreepModel, MonolithicSiCCreepModel, PARFUMUEBufferCreepModel, PARFUMUEPyCCreepModel, RoutbortFastMOXCreepModel, TobbeAIM1CreepModel, constantCreepPrincipalStress, correlationCreepPrincipalStress, fromLatestTime |
| rheologyModelOptions/damageModel | smearedCracking |
| rheologyModelOptions/softeningModel | exponentialSoftening |
| rheologyModelOptions/yieldStressModel | FRAPTRAN, constant |
| swellingModel | BufferPARFUME, FBRMOX, PyCCorrelation, PyCPARFUME, UO2FRAPCON, UO2MATPRO, constant, growthBISONZy, growthGeneralized1515Ti, none |
| thermalExpansionModel | BufferPARFUME, PyCPARFUME, SiCSnead, UO2RELAP, UPuO2Lemehov, constant |

## 几何入口

| 输入 | 现成入口 | 注意 |
|---|---|---|
| rodDict | 源配方中的rodMaker.py | 1D/2Dsmeared/2Ddiscrete；长度乘convertToMeters，结果字典通常写在工作目录。 |
| rod3Ddict.json | 源配方中的rod3Dmaker.py | 已有原生版本的单轴向段/数组首项限制见几何参考，不当作通用装配器。 |
| sphereDict | 源配方中的sphereMaker.py或octantSphereMaker.py | 半径与层厚、Buffer后间隙及外层联动见径向几何参考。 |
| system/blockMeshDict | blockMesh | 显式网格不得只改一个尺寸变量而遗漏顶点、弧和分区。 |
| 导入网格 | 源配方的导入工具 | 需要现有网格或明确生成器，不能凭坐标缩放创建缺失界面。 |

已有DiamCold/GapCold与所改几何同步；根输入、初场、材料、网格边界配套。更多尺寸定义见[径向几何](../radial-geometry.md)和[几何构建](../geometry-construction.md)。
