# 软件能力表：当前本地 OFFBEAT

仅为声明安装的已知能力索引。执行通过不证明所有组合/精度；未列出不等于不支持。运行助手查询本表，不读取维护源码。

维护时间：2026-11-14T14:57:54.756401+08:00。配置档：`local-offbeat-openfoam-v2506`。

安装身份由维护阶段记录；运行助手沿用启动器已准备环境，不为查询本表重复检查安装或源码。升级软件/加载新扩展后应由维护者更新配置档，不能把旧注册事实强套到新安装。

证据级别：runtime_verified=本机执行通过；registered=本机注册确认；documented=本地说明；input_observed=源卡出现；unverified=待核实。源卡出现仅证明语法被写过；本机执行通过仅覆盖记录中的组合。

## 温度与位移边界

场边界输入在起始场的 boundaryField/<patch>；网格patch类型在网格输入/constant/polyMesh。两者不能混为一项。标准OpenFOAM边界并未在本表穷举。

### T

| 类型 | 证据 | 用途 | 输入与依赖 |
|---|---|---|---|
| NaCoolantChannel | 本地说明 | 钠冷通道换热 | 以源卡的确切类型名为准；本地手册标题带 fvPatchScalarField 后缀，不能照抄标题当 selector。 |
| axialProfileT | 本地说明 | 轴向温度分布 | 按源确认轴线、归一化位置与温度项。 |
| convectiveHTC | 本地说明 | 给定对流换热 | T0（K）、h（W/(m²·K)）；value 通常仅初始化。 |
| coolantChannel | 本地说明 | 冷却剂通道换热 | 保持完整通道输入及质量流量、入口温度、物性约定。 |
| cyclic | 源卡出现 | 周期连接 | 保持配对和变换。 |
| cyclicAMI | 本机执行通过 | 非共形周期连接 | 保持 AMI 配对与实际覆盖。 |
| empty | 本机执行通过 | 降维边界 | 由网格维数决定，不当作普通物理表面改载荷。 |
| fixedGradient | 本地说明 | 给定法向梯度 | gradient；温度梯度 K/m，按所选字段核实。 |
| fixedTemperature | 本地说明 | 考虑附加热阻的定温边界 | 按源定义外界/界面温度，不能等同普通 fixedValue 的全部语法。 |
| fixedValue | 本机执行通过 | 给定场值 | value；T 为 K，D/DD 为 m；实际作用取决于字段。 |
| fuelRodGap | 本机执行通过 | 由气体/间隙状态参与的燃料棒界面换热 | 被热求解评价时需要可用的气体导热物性；gapGas none 已验证会失败。 |
| radiativeConvectiveSink | 本地说明 | 辐射与对流散热 | T0、alpha、emissivity；不把 value 当环境载荷。 |
| resistiveGap | 本机执行通过 | 给定界面热阻/导热系数 | alpha（W/(m²·K)）、coupled、kappa；源卡中固定 alpha 的纯热学场景可不使用气体模型。 |
| symmetry | 源卡出现 | 对称边界 | 保持源约束。 |
| symmetryPlane | 源卡出现 | 平面对称边界 | 保持源约束。 |
| temperatureCoupled | 本地说明 | 两侧直接耦合导热 | 配对 regionCoupledOFFBEAT 元数据和 kappa。 |
| timeDependentAxialProfileHTC | 本地说明 | 时变轴向对流换热 | 环境温度、系数和时间/空间表按源。 |
| timeDependentAxialProfileT | 本地说明 | 随时间变化的轴向温度分布 | 同时核对空间与时间索引。 |
| timeDependentTemperature | 本地说明 | 随时间给定温度 | 时间表和载荷项沿源；列表语法不在本表完整覆盖。 |
| trisoGap | 本地说明 | TRISO 间隙换热 | 保持源中的气体和几何组合；jumpDistance 是热跳跃贡献，不是直接几何间隙宽度。 |
| uniformFixedValue | 本地说明 | 均匀给定值/时间函数 | uniformValue；不能用 value 初始化项替代实际载荷。 |
| wedge | 本机执行通过 | 轴对称/球对称楔形约束 | 保留几何与场类型一致；球楔形体积分数不能直接用圆柱角度比例替代。 |
| xzTemperatureProfile | 本地说明 | x-z 温度分布 | 按源坐标与数据约定。 |
| zeroGradient | 本机执行通过 | 零法向梯度 | 用于绝热温度边界时不额外给定温度；面值与邻近存储单元取值口径应注明。 |

### D

| 类型 | 证据 | 用途 | 输入与依赖 |
|---|---|---|---|
| coolantPressure | 本地说明 | 冷却剂压力载荷 | 沿源所引用的 coolantPressureList 或实际压力数据定义。 |
| cyclic | 源卡出现 | 周期连接 | 保持配对和变换。 |
| cyclicAMI | 本机执行通过 | 非共形周期连接 | 保持 AMI 配对与实际覆盖。 |
| empty | 本机执行通过 | 降维边界 | 由网格维数决定，不当作普通物理表面改载荷。 |
| fixedDisplacement | 本地说明 | 给定位移 | 位移方向、基底、value 及时间条件按源。 |
| fixedDisplacementZeroShear | 本机执行通过 | 指定方向位移并允许滑移 | 保留源中的轴向约束与剪切处理。 |
| fixedPointLoad | 本地说明 | 集中载荷 | 施加载荷位置与力的单位按源。 |
| fixedTorque | 本地说明 | 给定扭矩 | 轴线与扭矩输入按源。 |
| fixedValue | 本地说明 | 给定场值 | value；T 为 K，D/DD 为 m；实际作用取决于字段。 |
| frictionalGapContact | 源卡出现 | 含摩擦接触 | 源卡存在；摩擦输入/适用构型未独立验证。 |
| gapContact | 本机执行通过 | 显式接触界面 | 成对的耦合 patch、压力/牵引、penaltyFactor 等；仅在实际机械求解评价时处理相关依赖。 |
| gapPressure | 本地说明 | 间隙气体压力载荷 | 保持气体模型依赖与源作用面。 |
| implicitGapContact | 本地说明 | 隐式接触 | 按对应源保留配对与求解设置，不能仅替换类型名。 |
| plenumSpringPressure | 本地说明 | 气室/弹簧压力载荷 | 保留气室几何、气体与弹簧输入。 |
| symmetry | 源卡出现 | 对称边界 | 保持源约束。 |
| symmetryPlane | 源卡出现 | 平面对称边界 | 保持源约束。 |
| topCladRingPressure | 本地说明 | 包壳端环载荷 | 作用区域和方向按源。 |
| tractionDisplacement | 本机执行通过 | 牵引/压力边界 | traction 与 pressure；压力 Pa，正压力与应力分量的符号须分开解释。 |
| unilateralContact | 本地说明 | 单侧接触/滑动约束 | 法向和支承位置按源；不等于双向固定。 |
| wedge | 本机执行通过 | 轴对称/球对称楔形约束 | 保留几何与场类型一致；球楔形体积分数不能直接用圆柱角度比例替代。 |
| zeroGradient | 本机执行通过 | 零法向梯度 | 用于绝热温度边界时不额外给定温度；面值与邻近存储单元取值口径应注明。 |

### DD

| 类型 | 证据 | 用途 | 输入与依赖 |
|---|---|---|---|
| empty | 源卡出现 | 降维边界 | 由网格维数决定，不当作普通物理表面改载荷。 |
| fixedValue | 源卡出现 | 给定场值 | value；T 为 K，D/DD 为 m；实际作用取决于字段。 |
| gapContact | 源卡出现 | 显式接触界面 | 成对的耦合 patch、压力/牵引、penaltyFactor 等；仅在实际机械求解评价时处理相关依赖。 |
| symmetry | 源卡出现 | 对称边界 | 保持源约束。 |
| symmetryPlane | 源卡出现 | 平面对称边界 | 保持源约束。 |
| tractionDisplacement | 源卡出现 | 牵引/压力边界 | traction 与 pressure；压力 Pa，正压力与应力分量的符号须分开解释。 |
| uniformFixedValue | 源卡出现 | 均匀给定值/时间函数 | uniformValue；不能用 value 初始化项替代实际载荷。 |
| wedge | 源卡出现 | 轴对称/球对称楔形约束 | 保留几何与场类型一致；球楔形体积分数不能直接用圆柱角度比例替代。 |

## 气体与热耦合

solidConduction 评价 fuelRodGap 时，不能关闭它需要的气体导热能力。本机 FRAPCON 组合已正常执行，none 已报导热率调用错误。resistiveGap 固定alpha的源场景已在gapGas none下运行，但不推广到所有边界。

当热方程固定且相应边界没有被评价时，不仅凭文件里存在fuelRodGap就强制开启气体模型；保持源物理范围。TRISO等其他气体/边界组合按源，本表没有逐个验证。
