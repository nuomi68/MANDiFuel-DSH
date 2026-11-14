#!/usr/bin/env python3
"""将已核实的软件接口事实和只读清单编译为中文能力表；不运行求解器。"""
from datetime import datetime
from zoneinfo import ZoneInfo
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).parent
DEST=ROOT/'skills/prepare-offbeat-case/references/software-capabilities'
DOCS=Path('/home/lwz/offbeat/mkdocs/docs')
COVERAGE_LABELS={'rag_cards':'本地检索卡片','input_cases_parsed':'有效源输入','excluded_utility_directories':'排除的工具目录','normal_execution_records':'正常执行记录（含重复组合）','selector_families':'顶层选择器类别','selector_values':'已收录选择器值（证据分级）','material_models':'材料条目（含拼写未核实者）','confirmed_material_selectors':'源卡确认拼写的材料选择器','property_families':'材料物性/本构参数类别','property_values':'源卡出现的物性/本构值','boundary_entries':'边界条目（按T/D/DD分别计）','field_entries':'字段与单位条目','controls':'时间/求解控制条目','parameter_bindings':'常用参数绑定','operations':'可组合任务意图','rules':'依赖/风险规则','public_apis':'结果公共API'}
API_DESCRIPTIONS={'list_times':'列出求解或后处理的数值时刻，可限定必须含有某个场。','list_variables':'描述一个时刻或全部求解时刻中可读的体场。','list_scopes':'返回解析时刻网格中的具名单元区与边界。','describe_field':'返回字段绑定；dimensions使用精确、可序列化的十进制字符串。','describe_mesh':'返回相对于结果根目录的、与所选时刻绑定的网格文件路径。','iter_fields':'逐时刻迭代选定帧，支持相应的动网格几何。','read_field':'读取标量分量或principal_max；time=all将全部帧载入内存。','extreme':'对一个或全部时刻的选定场求极值；默认返回float。'}
LEVELS={'runtime_verified':'本机执行通过','registered':'本机注册确认','documented':'本地说明','input_observed':'源卡出现','unverified':'待核实'}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def table(headers,rows):
 def cell(x):return str(x).replace('|','\\|').replace('\n','；')
 return '\n'.join(['| '+' | '.join(headers)+' |','|'+'---|'*len(headers),*['| '+' | '.join(cell(x) for x in row)+' |' for row in rows]])+'\n'


SELECTORS={
 'thermalSolver':('温度方程','constant',{'constant':'不解温度方程，读取并沿用起始 T；固定均匀温度时同时确认内部场和所需边界。','fromLatestTime':'旧名，兼容映射到 constant。','solidConduction':'求固体导热方程，可使用体积热源 Q。','readTemperature':'逐时读取 constant 子目录中的给定温度场；按源配方确定目录结构。'},'solverDict/thermal_solver.md',['0/T','thermalSolverOptions','heatSource 与 Q、T 边界']),
 'mechanicsSolver':('动量平衡/位移','constant',{'constant':'不解位移方程，沿用已有位移状态；不等于把已有 D 清零。','fromLatestTime':'旧输入兼容映射到 constant。','smallStrain':'总位移 D，小应变，计算网格不更新。','smallStrainIncrementalUpdated':'增量位移 DD，小应变并更新网格。','largeStrainTotLag':'总位移 D，总拉格朗日大应变；不更新计算网格。','largeStrainUpdLag':'增量位移 DD，更新拉格朗日大应变，更新网格。'},'solverDict/mechanics_solver.md',['0/D 或 0/DD','mechanicsSolverOptions','rheologyOptions','system/fvSolution 对应字段求解设置']),
 'neutronicsSolver':('中子学','none',{'none':'不求中子方程；不据此推断其他给定通量也被清零。','fromLatestTime':'本机已接受的旧输入，初始化日志选择 none。','diffusion':'单群中子扩散；所需场和系数沿对应源卡。'},'solverDict/neutronics_solver.md',['对应源中的中子通量初场','neutronicsSolverOptions；与 fastFlux 分开']),
 'elementTransport':('元素/裂变产物迁移','none',{'none':'本机已接受的停用输运选择。','fromLatestTime':'旧输入兼容；本机初始化选择 none。','byList':'由 elementTransportOptions/solvers 列表启用具体输运方程。'},'solverDict/element_transport_solver.md',['elementTransportOptions/solvers','对应模型 Options、初态和材料参数']),
 'materialProperties':('材料分区',None,{'byZone':'按 cellZone 绑定材料；分区名称和 materials 中的材料项必须对应。'},'solverDict/materialProperties.md',['materials/<zone>/material','constant/polyMesh/cellZones']),
 'rheology':('本构组织方式',None,{'byMaterial':'本构在每个 materials/<zone>/rheologyModel 中选择。'},'solverDict/rheology.md',['materials/<zone>/rheologyModel','materials/<zone>/rheologyModelOptions','rheologyOptions']),
 'heatSource':('体积热源','none',{'none':'本地说明中的无热源选择；不创建 Q，尚未用本机正常记录独立验证该组合。','constant':'沿用起始 Q 场，不等于零功率。','fromLatestTime':'旧名，兼容 constant。','constantLhgr':'恒定线功率，heatSourceOptions/lhgr 为标量；实际本机输入已确认。','timeDependentLhgr':'线功率时间表：timePoints 与 lhgr 为配对列表，可叠加空间分布。','timeDependentVhgr':'体积热源时间表，输入 vhgr 单位 W/m³；具体表格结构按源。','laserHeatSource':'源卡中出现的激光热源；未独立验证构造参数和适用范围。'},'solverDict/heat_source.md',['起始 Q 或 heatSourceOptions','lhgr / vhgr 与 timePoints','axialProfile / radialProfile / materials']),
 'burnup':('燃耗','none',{'none':'不推进/不创建燃耗场（本地说明）。','constant':'从起始 Bu 沿用燃耗；不等于清零。','fromLatestTime':'旧名，本机选择 constant。','fromPower':'由热源推进燃耗。','Lassmann':'简化核素耗损与径向形状因子模型。','LassmannFBR':'快堆相关燃耗模型，源卡存在；完整参数及当前注册待核实。'},'solverDict/burnup.md',['burnupOptions','热源、密度及核素输入','实际 Bu 字段单位']),
 'fastFlux':('快通量与快注量','none',{'none':'本地说明中的停用选择。','constant':'沿用给定 fastFlux；fastFluence 仍可随时间累积，不能当作注量冻结。','fromLatestTime':'旧名，本机选择 constant。','timeDependentAxialProfile':'给定平均快通量历史及轴向分布。'},'solverDict/fast_flux.md',['fastFluxOptions/timePoints、fastFlux','fastFluxOptions/axialProfile','起始 fastFlux / fastFluence 与本构单位约定']),
 'corrosion':('边界腐蚀/氧化生长',None,{'constant':'源卡存在的固定腐蚀状态模式；本机 fromLatestTime 初始化也选择 constant。','fromLatestTime':'已执行的旧固定状态选择；不要自行更换为未核实的 none。','byPatch':'按 corrosionOptions/patches/<patch> 配置腐蚀模型和动力学。'},None,['corrosionOptions/patches/<patch>/corrosionModel','oxidationKineticsModel','温度边界与 oxideThickness 作用域']),
 'gapGas':('间隙气体状态与物性','none',{'none':'不提供有效气体导热物性；气体模型使用者被评价时可能失败。','FRAPCON':'棒状燃料间隙/气室的体积、压力、温度、组成及气体物性。','TRISO':'TRISO Buffer—IPyC 间隙气体模型（本地说明和源卡）。'},'solverDict/gap_gas.md',['0/gapGas','gapGasOptions','调用气体物性的热边界、几何和 FGR']),
 'fgr':('裂变气体释放','none',{'none':'不计算裂变气体释放；不是关闭 gas 导热模型的同义操作。','SCIANTIX':'调用 SCIANTIX 局部气体演化模型；保留源中的根输入和耦合初态。','SCIANTIXRIA':'RIA 相关阈值释放，读取 SCIANTIX 初态；本地说明，尚未独立运行验证。'},'solverDict/fgr.md',['算例根 input_settings.txt（存在时）','源中的气体/晶粒等耦合初态','fgrOptions 与气体模型']),
 'sliceMapper':('三维网格到轴向切片的映射','none',{'none':'不建立映射；需要切片平均或轴向力平衡的模型不能据此认为不依赖映射。','byMaterial':'在材料项定义 nSlices 等切片参数。','byPellets':'按芯块高度划分切片，参数按源。','autoAxialSlices':'按材料和单元轴向位置自动分组。'},'solverDict/slice_mapper.md',['globalOptions/pinDirection','materials/<zone>/nSlices 等','依赖切片的热源、本构或燃耗模型'])}
ALIASES={'thermalSolver':{'fromLatestTime':'constant'},'mechanicsSolver':{'fromLatestTime':'constant'},'neutronicsSolver':{'fromLatestTime':'none'},'elementTransport':{'fromLatestTime':'none'},'heatSource':{'fromLatestTime':'constant'},'burnup':{'fromLatestTime':'constant'},'fastFlux':{'fromLatestTime':'constant'},'corrosion':{'fromLatestTime':'constant'}}
BC_MEANINGS={
 'fixedValue':('给定场值','value；T 为 K，D/DD 为 m；实际作用取决于字段。'),
 'uniformFixedValue':('均匀给定值/时间函数','uniformValue；不能用 value 初始化项替代实际载荷。'),
 'zeroGradient':('零法向梯度','用于绝热温度边界时不额外给定温度；面值与邻近存储单元取值口径应注明。'),
 'fixedGradient':('给定法向梯度','gradient；温度梯度 K/m，按所选字段核实。'),
 'fixedTemperature':('考虑附加热阻的定温边界','按源定义外界/界面温度，不能等同普通 fixedValue 的全部语法。'),
 'timeDependentTemperature':('随时间给定温度','时间表和载荷项沿源；列表语法不在本表完整覆盖。'),
 'axialProfileT':('轴向温度分布','按源确认轴线、归一化位置与温度项。'),
 'timeDependentAxialProfileT':('随时间变化的轴向温度分布','同时核对空间与时间索引。'),
 'xzTemperatureProfile':('x-z 温度分布','按源坐标与数据约定。'),
 'temperatureCoupled':('两侧直接耦合导热','配对 regionCoupledOFFBEAT 元数据和 kappa。'),
 'resistiveGap':('给定界面热阻/导热系数','alpha（W/(m²·K)）、coupled、kappa；源卡中固定 alpha 的纯热学场景可不使用气体模型。'),
 'fuelRodGap':('由气体/间隙状态参与的燃料棒界面换热','被热求解评价时需要可用的气体导热物性；gapGas none 已验证会失败。'),
 'trisoGap':('TRISO 间隙换热','保持源中的气体和几何组合；jumpDistance 是热跳跃贡献，不是直接几何间隙宽度。'),
 'convectiveHTC':('给定对流换热','T0（K）、h（W/(m²·K)）；value 通常仅初始化。'),
 'timeDependentAxialProfileHTC':('时变轴向对流换热','环境温度、系数和时间/空间表按源。'),
 'radiativeConvectiveSink':('辐射与对流散热','T0、alpha、emissivity；不把 value 当环境载荷。'),
 'coolantChannel':('冷却剂通道换热','保持完整通道输入及质量流量、入口温度、物性约定。'),
 'NaCoolantChannel':('钠冷通道换热','以源卡的确切类型名为准；本地手册标题带 fvPatchScalarField 后缀，不能照抄标题当 selector。'),
 'fixedDisplacement':('给定位移','位移方向、基底、value 及时间条件按源。'),
 'fixedDisplacementZeroShear':('指定方向位移并允许滑移','保留源中的轴向约束与剪切处理。'),
 'unilateralContact':('单侧接触/滑动约束','法向和支承位置按源；不等于双向固定。'),
 'tractionDisplacement':('牵引/压力边界','traction 与 pressure；压力 Pa，正压力与应力分量的符号须分开解释。'),
 'coolantPressure':('冷却剂压力载荷','沿源所引用的 coolantPressureList 或实际压力数据定义。'),
 'gapPressure':('间隙气体压力载荷','保持气体模型依赖与源作用面。'),
 'plenumSpringPressure':('气室/弹簧压力载荷','保留气室几何、气体与弹簧输入。'),
 'topCladRingPressure':('包壳端环载荷','作用区域和方向按源。'),
 'gapContact':('显式接触界面','成对的耦合 patch、压力/牵引、penaltyFactor 等；仅在实际机械求解评价时处理相关依赖。'),
 'frictionalGapContact':('含摩擦接触','源卡存在；摩擦输入/适用构型未独立验证。'),
 'implicitGapContact':('隐式接触','按对应源保留配对与求解设置，不能仅替换类型名。'),
 'fixedPointLoad':('集中载荷','施加载荷位置与力的单位按源。'),
 'fixedTorque':('给定扭矩','轴线与扭矩输入按源。'),
 'empty':('降维边界','由网格维数决定，不当作普通物理表面改载荷。'),
 'wedge':('轴对称/球对称楔形约束','保留几何与场类型一致；球楔形体积分数不能直接用圆柱角度比例替代。'),
 'symmetry':('对称边界','保持源约束。'),'symmetryPlane':('平面对称边界','保持源约束。'),
 'cyclic':('周期连接','保持配对和变换。'),'cyclicAMI':('非共形周期连接','保持 AMI 配对与实际覆盖。')}
FIELDS=[
 ('T','K',[0,0,0,1,0,0,0],'温度','runtime_verified'),('D','m',[0,1,0,0,0,0,0],'总位移向量；不能用作扩散系数','runtime_verified'),('DD','m',[0,1,0,0,0,0,0],'增量位移向量；与相应机械模型配套','documented'),
 ('Q','W/m³',[1,-1,-3,0,0,0,0],'实际体积热源','runtime_verified'),('lhgr','W/m',None,'线功率，局部或平均作用域随模型定义','runtime_verified'),('k','W/(m·K)',[1,1,-3,-1,0,0,0],'热导率','runtime_verified'),('rho','kg/m³',[1,-3,0,0,0,0,0],'密度，可在材料卡中而不单独写场','documented'),('Cp','J/(kg·K)',[0,2,-2,-1,0,0,0],'定压比热；温变 Cp 不可简单套用常数能量公式','documented'),
 ('sigma','Pa',[1,-1,-2,0,0,0,0],'笛卡尔对称应力张量，分量顺序 xx xy xz yy yz zz','runtime_verified'),('sigmaCyl','Pa',None,'变换后的柱坐标应力；确认轴线，标准棒通常为 z 轴','runtime_verified'),('sigmaEq','Pa',None,'等效应力','runtime_verified'),('sigmaHyd','Pa',None,'静水应力，保留符号','runtime_verified'),('sigmaY','Pa',None,'屈服应力，仅在相应模型写出时可用','documented'),
 ('epsilon','1',None,'总应变，场名按实际输出确认','runtime_verified'),('epsEl','1',None,'弹性应变','runtime_verified'),('epsTh','1',None,'热应变；不把它当总应变','runtime_verified'),('epsilonCreep','1',None,'旧说明中的蠕变应变名；当前具体模型字段名仍需核实','documented'),
 ('gapWidth','m',None,'仅按已确认间隙作用域解释；内部占位值不代表边界','runtime_verified'),('interfaceP','Pa',None,'界面接触压力，作用范围需确认','runtime_verified'),('oxideThickness','m',[0,1,0,0,0,0,0],'氧化层厚度可能是面场；按真实边界条目取值','runtime_verified'),('gasPressure','Pa',None,'仅限明确的间隙气体状态压力，不扩展到任意同名对象','runtime_verified'),
 ('Bu','MWd/MT_oxide',None,'本机已维护的确切字段约定；不与 BU/BUkgU/Bu_kgU 混用','runtime_verified'),('Bu_kgU',None,None,'本地历史来源存在单位冲突；unit_unverified','unverified'),
 ('fastFlux','n/(cm²·s)',None,'本地手册和源注释一致；不要擅自按 SI m²改数字，具体输入/输出作用域仍需确认','documented'),('fastFluence','n/cm²',None,'本地手册约定；constant fastFlux 不等于注量停止累积','documented'),
 ('Cs','mol/m³',[0,-3,0,0,1,0,0],'已验证 Cs 浓度场；均匀初始值在 intialFpConcentration（实际拼写）','runtime_verified'),('diffCs','m²/s',[0,2,-1,0,0,0,0],'运行后有效 Cs 扩散系数，不用 0/diffCs 种子证明生效','runtime_verified'),('sourceCs','mol/(m³·s)',[0,-3,-1,0,1,0,0],'Cs 生成源，零源需实际场核实','runtime_verified'),('V','m³',[0,3,0,0,0,0,0],'单元体积，可由原生后处理获得','runtime_verified')]
CONTROLS=[
 ('system/controlDict','startFrom','startTime / latestTime','选择新鲜起点或保留状态，不能混入更晚目录。'),('system/controlDict','startTime','模型时间','新鲜计算通常为0；续算按可信检查点。'),('system/controlDict','endTime','模型时间','不等于裁剪载荷表，也不能只凭该值证明完成。'),('system/controlDict','deltaT','模型时间','物理秒转换由 userTime 决定。'),('system/controlDict','userTime/type','seconds / hours / days','缺省沿源秒制；days 已有本机运行验证，hours 仅接口约定；其他类型不猜。'),
 ('system/controlDict','adjustableTimeStep','off / false 或 on / true','请求固定步长时关闭；不凭空新增不存在的其他开关。'),('system/controlDict','adjustableWriteTimeStep','若源存在则 false','附加写出时间控制，不是 writeControl 的枚举值。'),('system/controlDict','writeControl','timeStep / runTime / adjustableRunTime 等','每步输出可用 timeStep；精确模型间隔按现有说明选择。'),('system/controlDict','writeInterval','与 writeControl 对应','不是所有模式都按秒解释。'),('system/controlDict','purgeWrite','非负整数','需全部保存帧时用0；保留结果不能靠反复重算补齐。'),('system/controlDict','writeFormat / writeCompression','ascii；off','只在用户需要相应交付格式时设置。'),('system/controlDict','timePrecision / writePrecision','显示与序列化精度','不能为日志或目录显示尾数重算已完成物理过程。'),
 ('system/fvSchemes','ddtSchemes/default','Euler / steadyState 等','Euler 是瞬态时间离散；steadyState 是稳态离散，不把伪时间序列当真实瞬态。'),('system/fvSolution','solvers/<field>','字段对应的线性求解与阈值','D/DD/T 与所选模型一致，阈值沿源与请求。'),('system/fvSolution','stressAnalysis','maxOuterIter、T、D、relT 等源项','名称随本机输入，未请求时保留；不靠随意放宽精度换成功。'),
 ('constant/solverDict','heatSourceOptions/timePoints','模型时间列表','与时间载荷配对；已有更晚有效末点应保留。'),('constant/solverDict','heatSourceOptions/lhgr','标量或列表，依 heatSource','constantLhgr 标量，timeDependentLhgr 列表；kW/m 转 W/m 乘1000。'),('constant/solverDict','heatSourceOptions/vhgr','W/m³','用于相应体积热源模型，不能与线功率直接互换。'),('constant/solverDict','rheologyOptions/thermalExpansion','off / on','控制热应变，与 mechanicsSolver 是否求位移分开。')]
PARAMETERS=[
 ('materials/<zone>/material','材料类型','精确大小写；继承对应源中的完整属性和行为模型。'),('materials/<zone>/rho','kg/m³','constant 材料常用密度项。'),('materials/<zone>/Cp','J/(kg·K)','constant 材料常用比热项。'),('materials/<zone>/k','W/(m·K)','热导率；UO2 等材料改常数时还需正确 conductivityModel。'),('materials/<zone>/E','Pa','杨氏模量；GPa乘1e9。'),('materials/<zone>/nu','1','泊松比；不按其他材料默认值替换。'),('materials/<zone>/alpha','1/K','热膨胀系数，与热应变开关分开。'),('materials/<zone>/Tref','K','参考温度，沿用物理定义。'),('materials/<zone>/DiamCold','m','已有项随燃料外半径变化同步为2r。'),('materials/<zone>/GapCold','m','已有项为直径间隙2*(rCladInner-rFuelOuter)，不是径向间隙。'),
 ('materials/<zone>/rheologyModel','本构名称','不是顶层 mechanicsSolver；弹性/塑性/蠕变配套。'),('materials/<zone>/rheologyModelOptions/creepModel','蠕变模型','保留对应通量、应力、温度、单位及 fluxConversionFactor。'),('materials/<zone>/phaseTransitionModel','相变模型','ZyDynamic 在源卡出现；未做本机独立相变验证。'),
 ('materials/<zone>/fissionProductsTransport/Cs/{d1,q1,d2,q2}','模型系数','单UO2/Cs已验证常D：d1=D，q1=d2=q2=0；别推广到所有材料/元素。'),('elementTransportOptions/FpDiffusionOptions/intialFpConcentration/Cs','mol/m³','实际拼写 intial；不能自动改成 initial。'),('elementTransportOptions/FpDiffusionOptions/outerPatches','patch 名称','沿源的扩散外表面配置；核对实际 Cs 边界。'),
 ('0/gapGas/gasPressure','Pa','明确的初始间隙气体压力。'),('0/gapGas/gasPressureType','源定义','按源的状态初始化方式。'),('0/gapGas/massFractions','质量分数','组分与气体模型兼容。'),('gapGasOptions','模型专属','几何/储气空间体积按实际计算域，不能直接塞整棒/整球值。'),
 ('heatSourceOptions/axialProfile','空间分布','type、axialLocations、timePoints、data、插值配套。'),('heatSourceOptions/radialProfile','径向形状','沿源归一化约定；不以节点算术平均替代积分平均。'),('fastFluxOptions/{timePoints,fastFlux,axialProfile}','模型时间和通量','与热源的时间网格分开，单位见字段说明。'),('corrosionOptions/patches/<patch>/corrosionModel','腐蚀模型','已验证源中有 zircaloyOuterCorrosion；对象是明确边界。'),('corrosionOptions/patches/<patch>/oxidationKineticsModel','动力学模型','源中存在 EPRI-KWU-CE|Cathcart-Pawel 组合写法，保持确切字符串。')]
OPERATIONS=[
 ('disable_mechanics','关闭力学方程',['mechanicsSolver constant；兼容旧 fromLatestTime'],'保留已有位移状态；不自动关闭气体模型、热边界或其他物理模块。'),
 ('thermal_only','纯热学准备',['保留/选择适用热模型','固定力学状态；按请求关闭热应变','沿用内部热耦合和所需物性'],'没有气隙实体热容不等于不需要气体导热物性。'),
 ('prescribed_temperature','给定温度',['thermalSolver constant','按请求设置起始 T 与对应边界'],'不自动把所有功率、燃耗、通量清零。'),
 ('constant_power','恒定线功率',['已用 constantLhgr 时使用标量','已用 timeDependentLhgr 时让配对值恒定','源值已满足就复用'],'不为整理格式重写模型和时间节点，保留已有稍后末点。'),
 ('fixed_step','固定步长瞬态',['deltaT 为请求模型时间步长','关闭已有自适应开关','采用请求的瞬态格式和写出方式'],'模型时间与物理秒分开；正常终态以执行器证据为准。'),
 ('steady_thermal','稳态热学',['ddtSchemes/default steadyState','沿用相同几何、界面和物性','按请求设置功率和边界'],'不是必须额外试算的特殊任务，也不是把所有模型改为 none。'),
 ('restart','物理续算',['保留完整检查点状态与输入','独立目标、不继承旧执行凭据','不执行会清理状态的生成/清理步骤'],'不能仅复制T/D；未验证的活跃耦合模型续算不被一般成功记录覆盖。'),
 ('cs_constant_diffusion','单UO2/Cs常扩散',['使用 fpdiffusion-cs-constant-v1 公共入口','运行后核实 diffCs、T、sourceCs'],'只在声明适用范围内，未知材料组合走一般输入/运行反馈。'),
 ('change_rod_geometry','棒尺寸修改',['修改 rodDict 等生成器输入','已有冷态直径/间隙同步','必要几何锚定采样点同步'],'保留轴向结构和无关材料/载荷，生成器负责派生网格。'),
 ('energy_increment','常密度比热热能增量',['确认rho、Cp在本次范围为常数','按实际cellZone求rho*Cp*sum((T-T0)*V)'],'单位J；只积分真实实体域，不自动加入气隙热容或放大到整棒。')]
RULES=[
 ('selector_not_universal','错误','关闭方式按具体选择器','mechanicsSolver none 本机已证实非法；gapGas/fgr/neutronics 等的 none 另有各自含义。'),
 ('fuelRodGap_gas','错误','solidConduction 实际评价 fuelRodGap 且 gapGas none','缺少气体导热物性会失败。温度方程固定、未评价该边界时不凭边界名字强制开启气体模型。'),
 ('minimal_changes','原则','源输入已经满足请求','保持原值和时间网格；每项改动对应用户要求或已证实依赖。'),
 ('heat_time_coverage','风险','时变线功率表末点等于或早于终点','本机已出现查下一标记越界；保留现有更晚末点。相等不一概认定每个配方必失败，需结合具体时步/模型。'),
 ('rhoCp_constant','范围','热能增量用rho*Cp*DeltaT','只适用于已确认常数物性；温变Cp需要模型一致的焓/积分定义。'),
 ('displacement_field','依赖','增量/更新拉格朗日力学','使用DD初边界和相应求解项，不能把D机械复制为标量场。'),
 ('materials_zones','依赖','materialProperties byZone','实际分区与材料项对应；固定材料合法不代表任意温度/辐照条件均适用。'),
 ('coupled_patches','依赖','区域耦合界面','几何配对、neighbourPatch/neighbourRegion及owner信息按源保持；必要配方changeDictionary不能遗漏。'),
 ('sampling_compatibility','已知兼容风险','本机OpenFOAM v2506旧采样输入','已遇到lineUniform不被注册、patchProbes缺patch而仅给patchName；用支持语法或适用的已有场提取，不为此改物理。'),
 ('empty_patch_metadata','工具限制','list_scopes遇到0面defaultFaces','函数存在，但当前范围查询可抛解析异常。该网格已由原生工具正常运行；不把它当物理坏网格，不为查询重算。'),
 ('field_scope','语义','边界/材料区/全域响应','不能用内部占位值替代边界，不能用探针替代全区最大单元值。'),
 ('execution_evidence','完成','退出码、正常结束、实际终点三项结合','失败运行即使已写终态目录仍为失败；输入回读不代表物理生效。'),
 ('uncovered','恢复','本表没有条目或仅有源卡观察','这不构成拒绝任务的理由；保留源、定点查资料、按允许范围运行并修复，默认不限启动次数。')]


def main():
 e=json.loads((HERE/'evidence.json').read_text());DEST.mkdir(parents=True,exist_ok=True)
 sources={}
 for p in sorted(DOCS.rglob('*.md')):
  if 'user_guide' not in p.parts and 'tools' not in p.parts:continue
  sources['doc:'+p.relative_to(DOCS).as_posix()]={'kind':'local_document','path':str(p.relative_to(DOCS)),'sha256':sha(p)}
 sources['input_inventory']={'kind':'local_input_inventory','case_count':e['cards']-len(e['parse_failures']),'scope':'仅证明字面输入出现，不证明本机运行有效。'}
 sources['runtime_initialization']={'kind':'retained_normal_runs','record_count':e['runtime_success_count'],'scope':'本机正常记录中的初始化和输入；同一组合可能重复，不含数值答案。'}
 sources['mechanics_registry']={'kind':'retained_native_diagnostic','values':['constant','smallStrain','smallStrainIncrementalUpdated','largeStrainTotLag','largeStrainUpdLag'],'scope':'本机mechanicsSolver非法类型诊断的合法类型列表。'}
 def level(group,name,doc=False,registry=False):
  if e.get('runtime_'+group,{}).get(name):return 'runtime_verified'
  return 'registered' if registry else 'documented' if doc else 'input_observed'
 selectors={}
 for key,(purpose,inactive,meanings,doc,bindings) in SELECTORS.items():
  choices=[];values=set(meanings)|set(e['selectors'].get(key,{}))
  for name in sorted(values):
   observed=e['selectors'].get(key,{}).get(name,[]);executed=e['runtime_selectors'].get(key,{}).get(name,[])
   documented=doc is not None and name in meanings and name not in ('laserHeatSource','LassmannFBR')
   registered=key=='mechanicsSolver' and name in ('constant','smallStrain','smallStrainIncrementalUpdated','largeStrainTotLag','largeStrainUpdLag')
   tag='runtime_verified' if executed else 'registered' if registered else 'documented' if documented else 'input_observed'
   choices.append({'value':name,'level':tag,'meaning':meanings.get(name,'源卡中出现；具体语义及参数按原源，未独立验证。'),'source_case_count':len(set(observed)),'runtime_observations':len(executed),'example_case':observed[0] if observed else None,'sources':(['runtime_initialization'] if executed else [])+(['mechanics_registry'] if registered else [])+(['doc:user_guide/'+doc] if documented else [])+(['input_inventory'] if observed else [])})
  selectors[key]={'purpose':purpose,'owner':'constant/solverDict','entry':key,'preferred_inactive':inactive,'aliases':ALIASES.get(key,{}),'bindings':bindings,'choices':choices,'sources':(['doc:user_guide/'+doc] if doc else [])+['input_inventory','runtime_initialization']}
  if key=='mechanicsSolver':selectors[key]['known_invalid']={'none':'本机合法类型列表和实际初始化失败已确认；不要用通用关闭词猜值。'}
 models=[]
 descriptions={'constant':'显式常数材料，常见rho、Cp、k、E、nu、alpha、Tref等沿完整源输入。','UO2':'二氧化铀燃料，默认物性和行为相关式按所选配置。','UPuO2':'混合氧化物燃料，相关式和燃料组成按源。','zircaloy':'锆合金包壳，可包含相变、蠕变、生长等行为。','steel1515Ti':'15-15Ti不锈钢材料，物性与本构按源。','PyC':'热解碳材料，各向异性及辐照参数按源。','buffer':'TRISO缓冲层材料，名称大小写保留。','SiC':'碳化硅涂层/试样材料；蠕变等不是仅选材料就自动确定。','molybdenum':'本地手册列出的钼材料；实际selector大小写需对应源确认。','inconel600':'本地手册列出的Inconel 600；当前源卡扫描未观察。'}
 for name in sorted(set(e['materials'])|{'molybdenum','inconel600'}):
  obs=e['materials'].get(name,[]);executed=e['runtime_materials'].get(name,[])
  models.append({'name':{'molybdenum':'钼（Molybdenum）','inconel600':'Inconel 600'}.get(name,name),'value':name if obs else None,'level':'runtime_verified' if executed else 'input_observed' if obs else 'documented','meaning':descriptions.get(name,'按源配置材料'),'source_case_count':len(set(obs)),'runtime_observations':len(executed),'spelling_verified':bool(obs),'example_case':obs[0] if obs else None})
 boundaries={}
 doc_sets={'T':['fixedValue','fixedGradient','uniformFixedValue','zeroGradient','fixedTemperature','timeDependentTemperature','axialProfileT','timeDependentAxialProfileT','xzTemperatureProfile','temperatureCoupled','resistiveGap','fuelRodGap','trisoGap','convectiveHTC','timeDependentAxialProfileHTC','radiativeConvectiveSink','coolantChannel','NaCoolantChannel'],
           'D':['fixedValue','zeroGradient','fixedDisplacement','fixedDisplacementZeroShear','unilateralContact','tractionDisplacement','coolantPressure','gapPressure','plenumSpringPressure','topCladRingPressure','gapContact','fixedPointLoad','fixedTorque','implicitGapContact']}
 for field in ('T','D','DD'):
  b=[];names=set(e['boundaries'].get(field,{}))|(set(doc_sets.get(field,[])))
  for name in sorted(names):
   obs=e['boundaries'].get(field,{}).get(name,[]);executed=e['runtime_boundaries'].get(field,{}).get(name,[]);meaning,inputs=BC_MEANINGS.get(name,('按源边界','未独立说明'))
   b.append({'type':name,'level':'runtime_verified' if executed else 'documented' if name in doc_sets.get(field,[]) else 'input_observed','meaning':meaning,'inputs':inputs,'source_case_count':len(set(obs)),'runtime_observations':len(executed)})
  boundaries[field]=b
 prop={key:[{'value':v,'level':'input_observed','source_case_count':len(set(paths)),'example_case':paths[0]} for v,paths in sorted(values.items())] for key,values in sorted(e['property_models'].items())}
 public=[]
 tree=ast.parse((ROOT/'skills/extract-offbeat-results/scripts/result_api.py').read_text())
 for f in tree.body:
  if isinstance(f,ast.FunctionDef) and not f.name.startswith('_'):
   public.append({'name':f.name,'signature':f.name+'('+ast.unparse(f.args)+')','description':API_DESCRIPTIONS[f.name],'source':'extract-offbeat-results/scripts/result_api.py','availability':'public_export_checked'})
 c={'schema_version':1,'catalog_id':'offbeat-local-capabilities-20261114','generated_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'profile':e['profile'],'levels':LEVELS,
    'scope':'仅为声明安装的已知能力索引。执行通过不证明所有组合/精度；未列出不等于不支持。运行助手查询本表，不读取维护源码。',
    'sources':sources,'selectors':selectors,'materials':models,'property_models':prop,'boundaries':boundaries,
    'fields':[dict(zip(('name','unit','dimensions','meaning','level'),x)) for x in FIELDS],
    'controls':[dict(zip(('file','entry','value_or_unit','meaning'),x)) for x in CONTROLS],
    'parameters':[dict(zip(('entry','unit_or_type','meaning'),x)) for x in PARAMETERS],
    'operations':[dict(zip(('id','goal','actions','constraint'),x)) for x in OPERATIONS],
    'rules':[dict(zip(('id','severity','condition','meaning'),x)) for x in RULES],'public_apis':public,
    'tooling':{'foam_edit':'get_foam_entry / set_foam_entry，已有项的原生编辑与回读；不会检查全部物理语义。','case_runner':'run_case / inspect_case，保存执行状态、实际终点和diagnostic；同目录幂等，修复后新尝试。','parameter_plan':'已验证Cs常D范围内的批量准备/执行/实际场核对，不作为全部任务入口。','Study':'多评价历史与调度，prepare/execute/evaluate/collect，按实际公开说明使用；默认不限制求解次数。','generators':'rodDict/rod3Ddict.json/sphereDict是输入；调用配方中的现成生成器，不读实现。','postProcess':'纯后处理，可生成C/V；不因提取错误重算物理过程。'},
    'limitations':['时间控制和离散格式的本地官方页面尚为空页；相关条目依据已维护协议、输入与运行证据。','elementTransport本地说明未列FpDiffusion；该能力由实际输入/运行与已验证契约补充。','本地后处理说明有BU/BUkgU等命名和单位差异，确切Bu以现有核实约定为准，Bu_kgU待核实。','list_scopes存在，空defaultFaces异常属于当前解析器范围查询限制，不是方法缺失。','模型名和property key区分大小写，例如源中PoissonRatioModel和poissonRatioModel不能擅自归并。','手册constant材料列出的所有required项与可运行源并不完全一致；不凭旧列表补造未需要的参数。','没有对文档/源卡列出的全部模型逐个求解，不宣称穷举注册表或完整参数验证。']}
 c['coverage']={'rag_cards':e['cards'],'input_cases_parsed':e['cards']-len(e['parse_failures']),'excluded_utility_directories':[x['case'] for x in e['parse_failures']],
                'normal_execution_records':e['runtime_success_count'],'selector_families':len(selectors),'selector_values':sum(len(x['choices']) for x in selectors.values()),'material_models':len(models),'confirmed_material_selectors':sum(x['spelling_verified'] for x in models),'property_families':len(prop),'property_values':sum(len(x) for x in prop.values()),'boundary_entries':sum(len(x) for x in boundaries.values()),'field_entries':len(FIELDS),'controls':len(CONTROLS),'parameter_bindings':len(PARAMETERS),'operations':len(OPERATIONS),'rules':len(RULES),'public_apis':len(public)}
 save(DEST/'catalog.json',c)
 base=['# 软件能力表：当前本地 OFFBEAT','',c['scope'],'',f'维护时间：{c["generated_at_beijing"]}。配置档：`{c["profile"]["name"]}`。', '',
       '安装身份由维护阶段记录；运行助手沿用启动器已准备环境，不为查询本表重复检查安装或源码。升级软件/加载新扩展后应由维护者更新配置档，不能把旧注册事实强套到新安装。', '',
       '证据级别：'+ '；'.join(k+'='+v for k,v in LEVELS.items())+'。源卡出现仅证明语法被写过；本机执行通过仅覆盖记录中的组合。', '']
 model_text=base+['## 模型选择器','', '不要把 none 当成所有模块的关闭值；constant 通常是沿用状态，也不等于数值清零。', '']
 for key,data in selectors.items():
  model_text += [f'### {key}：{data["purpose"]}','',f'输入：`{data["owner"]}` → `{key}`。关联输入：'+ '；'.join(data['bindings'])+'。','']
  if data['preferred_inactive']:model_text += [f'已知停用/固定入口：`{data["preferred_inactive"]}`，仍须按下表语义与依赖使用。','']
  if data.get('known_invalid'):model_text += ['本机已确认非法：'+ '；'.join('`'+k+'`：'+v for k,v in data['known_invalid'].items())+'','']
  model_text += [table(['值','证据','语义'],[(x['value'],LEVELS[x['level']],x['meaning']) for x in data['choices']])]
 model_text += ['## 输运子模型与空间分布','',
  '`elementTransport byList` 的子列表在 `elementTransportOptions/solvers`。FpDiffusion 已执行确认；porosityTransport、PuRedistribution、AmRedistribution 在本地说明中列出，未逐个实跑。FpDiffusion 的具体字段与已验证单UO2/Cs参数见参数契约，不能向其他元素材料直接推广。', '',
  '空间分布常见 flat、constantTabulated、timeDependentTabulated；时间、轴向节点和data形状必须与具体type一致。常量表不是时变矩阵。新的空间分布不在本表逐个注册验证，使用源和相应输入绑定。','']
 (DEST/'models.md').write_text('\n'.join(model_text))
 btext=base+['## 温度与位移边界','', '场边界输入在起始场的 boundaryField/<patch>；网格patch类型在网格输入/constant/polyMesh。两者不能混为一项。标准OpenFOAM边界并未在本表穷举。','']
 for field,items in boundaries.items():btext += [f'### {field}','',table(['类型','证据','用途','输入与依赖'],[(x['type'],LEVELS[x['level']],x['meaning'],x['inputs']) for x in items])]
 btext += ['## 气体与热耦合','', 'solidConduction 评价 fuelRodGap 时，不能关闭它需要的气体导热能力。本机 FRAPCON 组合已正常执行，none 已报导热率调用错误。resistiveGap 固定alpha的源场景已在gapGas none下运行，但不推广到所有边界。', '',
 '当热方程固定且相应边界没有被评价时，不仅凭文件里存在fuelRodGap就强制开启气体模型；保持源物理范围。TRISO等其他气体/边界组合按源，本表没有逐个验证。','']
 (DEST/'boundaries.md').write_text('\n'.join(btext))
 mtext=base+['## 材料与输入所有者','',table(['材料','证据','说明'],[(x['name'],LEVELS[x['level']],x['meaning']+('（selector未确认，不提供可直接写入的值）' if not x['spelling_verified'] else '')) for x in models]),
 '## 常用参数绑定','',table(['文件内路径（solverDict，除非另注明）','单位/类型','作用与限制'],[(x['entry'],x['unit_or_type'],x['meaning']) for x in c['parameters']]),
 '## 源卡中出现的物性和本构选择','', '以下均为源输入观察，不是全模型注册验证。大小写、嵌套路径和拼写照源保留，不由文件名或英文词推导selector。','',table(['材料项内的路径','观察值'],[(k,', '.join(x['value'] for x in vals)) for k,vals in prop.items()]),
 '## 几何入口','',table(['输入','现成入口','注意'],[
 ('rodDict','源配方中的rodMaker.py','1D/2Dsmeared/2Ddiscrete；长度乘convertToMeters，结果字典通常写在工作目录。'),
 ('rod3Ddict.json','源配方中的rod3Dmaker.py','已有原生版本的单轴向段/数组首项限制见几何参考，不当作通用装配器。'),
 ('sphereDict','源配方中的sphereMaker.py或octantSphereMaker.py','半径与层厚、Buffer后间隙及外层联动见径向几何参考。'),
 ('system/blockMeshDict','blockMesh','显式网格不得只改一个尺寸变量而遗漏顶点、弧和分区。'),
 ('导入网格','源配方的导入工具','需要现有网格或明确生成器，不能凭坐标缩放创建缺失界面。')]),
 '已有DiamCold/GapCold与所改几何同步；根输入、初场、材料、网格边界配套。更多尺寸定义见[径向几何](../radial-geometry.md)和[几何构建](../geometry-construction.md)。','']
 (DEST/'materials-and-geometry.md').write_text('\n'.join(mtext))
 ftext=base+['## 字段与单位','', '优先读取实际场头dimensions；单位约定仅适用于确切字段和作用域。没有列出不表示不存在，字段由模型和写出设置决定。以下不把全部同名派生量强制解释为同一对象。','',table(['字段','单位','证据','含义与限制'],[(x['name'],x['unit'] or 'unit_unverified',LEVELS[x['level']],x['meaning']) for x in c['fields']]),
 '## 范围、积分与坐标','', '体积分使用真实cellZone的完整单元集合及对应V；圆柱扇区的整圈换算与球楔形的立体角比例不同。初始与终态库存采用相同物理域，涂层库存仍属于粒子库存。', '',
 'sigma为笛卡尔张量。sigmaCyl按算例柱轴变换，不能无条件当作球坐标应力；球径向位移需要坐标投影。对称张量顺序为xx,xy,xz,yy,yz,zz；最大主应力使用sigma的特征值，不用某一对角分量替代。', '',
 'fastFlux/fastFluence的本地手册和SiC源注释使用cm²约定，不能把所有量默认SI m²后静默改数。Bu_kgU仍有来源冲突，必须保留未核实标签。','']
 (DEST/'fields-and-units.md').write_text('\n'.join(ftext))
 ttext=base+['## 时间、控制与完成','',table(['文件','条目','值/单位','说明'],[(x['file'],x['entry'],x['value_or_unit'],x['meaning']) for x in c['controls']]),
 '## 时间覆盖','', '模型时间与物理秒分开：seconds×1，hours×3600，days×86400。改userTime时所有引用历史必须保持原物理含义，不能只改单位名。没有单位项时沿源秒制。', '',
 '源的功率和时间表已经覆盖请求区间就保留，不因endTime变小而截断。当前安装的时变线功率在恰好到达末节点时曾因查询下一标记越界；需要新建表时保留区间外有效尾点，或采用已验证的具体端点处理。该观察不等于每个模型/每种步长的相等末点都必失败。', '',
 '## 续算与恢复','', '续算保留整个检查点状态、网格、材料和必要根文件；不只带T/D。续算配方不能重新生成会覆盖状态的网格，独立目标不继承旧执行凭据作为新尝试。', '',
 '正常完成结合退出0、正常结束标记和实际终态。执行器在受限舍入容差内返回真实目录名，提取沿用该名。已有末时刻文件但执行失败仍保留失败；不用显示精度或报告格式触发重算。', '',
 '默认不限制真实求解启动次数。有具体输入修复后新尝试继续，已成功结果复用。详见[恢复闭环](../../execute-offbeat-case/references/input-recovery.md)与[时间配方](../../execute-offbeat-case/references/time-and-restart.md)。','']
 # Links from this subdirectory require three levels to reach skills siblings.
 ttext=[x.replace('../../execute-offbeat-case/','../../../execute-offbeat-case/') for x in ttext]
 (DEST/'time-and-execution.md').write_text('\n'.join(ttext))
 ptext=base+['## 公共工具入口','',table(['入口','能力'],c['tooling'].items()),
 '## 提取API：实际导出签名','', '以下签名由当前public result_api.py的AST核对。运行任务按此调用，不需要查看实现。list_scopes确实存在；有空defaultFaces时范围查询会报解析错误，不代表函数不存在。','']
 for entry in public:ptext += ['```python',entry['signature'],'```',entry['description'] or '', '']
 ptext += ['## 使用和限制','', 'component：标量value；向量x/y/z；对称张量xx/xy/xz/yy/yz/zz或principal_max。没有mag；需要幅值时在同一选择上组合分量。sigmaCyl的radial/hoop/axial便利分量按其坐标约定使用。', '',
 'read_field(time="all")会物化全部帧；iter_fields可逐帧消费。同一场的统计与表复用已读结果，长提取从首次提交就使用原生后台句柄。当前大网格/重复几何解析可能耗时，不重复前台测时直到超时。', '',
 '面场不由list_variables完整列出。仅需原始均匀/列表边界条目时可用foamDictionary读取dimensions和boundaryField/<patch>/value，避免重建网格。需要面积/坐标/标签时仍要有相应几何证据。', '',
 '0面defaultFaces可能触发list_scopes解析异常；原生网格有效，不删面、不改物理、不重算。已知材料区可继续尝试已说明的字段选择，或使用原生后处理与明确的实际范围；不私自重写底层解析器。', '',
 '几何字面量裸列表与新增未支持语法可用任务局部输入代码；已有字典替换复用foam_edit。原生回读验证写入，软件模型组合由已知检查和真实结果另行核对。','']
 (DEST/'public-tools.md').write_text('\n'.join(ptext))
 rtext=base+['## 任务意图与可组合操作','',table(['意图ID','目的','已知操作','限制'],[(x['id'],x['goal'],'；'.join(x['actions']),x['constraint']) for x in c['operations']]),
 '## 依赖、风险与已知限制','',table(['规则','类别','条件','处理'],[(x['id'],x['severity'],x['condition'],x['meaning']) for x in c['rules']]),
 '## 局部资料的边界','',*['- '+x for x in c['limitations']], '',
 '仅核对本次改动及直接依赖，不把该表转成逐项探索清单。已完成算例不因新提示重算。没有覆盖的值先标未核实，按原源和运行反馈推进；未知能力不是默认拒绝项。','']
 (DEST/'dependencies-and-operations.md').write_text('\n'.join(rtext))
 index=ROOT/'skills/prepare-offbeat-case/references/software-capabilities.md'
 ix=['# 当前安装的软件能力表','',f'配置档 `{c["profile"]["name"]}`；维护于 {c["generated_at_beijing"]}。能力事实、接口和限制按来源分级，避免反复搜索或猜参数。', '',
 '**先用关键事实**：关闭力学用当前已验证的mechanicsSolver constant；none不是通用关闭词。保留内部fuelRodGap导热时，核对它实际使用的气体物性。源功率和较晚时间末点已经满足请求就沿用。回读成功只证明写入，不能证明物理生效。', '',
 '## 按本次改动定点查询','',
 '```bash','python3 "$MANDIFUEL_PLUGIN_ROOT/skills/prepare-offbeat-case/scripts/software_capabilities.py" show mechanicsSolver gapGas time','python3 "$MANDIFUEL_PLUGIN_ROOT/skills/prepare-offbeat-case/scripts/software_capabilities.py" check --case case --source source-case','```','',
 '一次查询可给多个选择器/主题；只读相关结果，不全表展开。check检查已知问题与直接依赖，错误与未核实项分开；无已知错误不等于整套物理已验证。新任务/未知值仍走一般准备、运行反馈与修复，默认不限次数。', '',
 table(['内容','入口'],[
 ('13类模型选择器、合法关闭与旧名映射','[模型](software-capabilities/models.md)'),('温度/位移边界及耦合','[边界](software-capabilities/boundaries.md)'),('材料、本构、参数路径与几何','[材料和几何](software-capabilities/materials-and-geometry.md)'),('字段、单位、范围与坐标','[字段单位](software-capabilities/fields-and-units.md)'),('时间覆盖、写出、续算与完成','[时间执行](software-capabilities/time-and-execution.md)'),('公开工具和准确API签名','[公共工具](software-capabilities/public-tools.md)'),('意图组合、依赖与已知限制','[操作和依赖](software-capabilities/dependencies-and-operations.md)'),('供程序读取的统一事实源','[catalog.json](software-capabilities/catalog.json)')]),
 '## 覆盖与证据','',table(['项','数量'],[(COVERAGE_LABELS[k],v) for k,v in c['coverage'].items()]),
 '证据级别：'+ '；'.join(k+'='+v for k,v in LEVELS.items())+'。正常记录可重复同一模型，不构成全部组合验证。材料/属性/边界中的源卡观察不等于本机已执行认证。', '',
 '136套带solverDict输入被纳入，另1个工具目录不含该字典。当前二进制SHA256为 `'+c['profile']['binary_sha256']+'`；共享库指纹记录在JSON。运行时沿用已准备环境，不逐题重复安装检查；软件升级由维护阶段更新本表。', '',
 '本表为编译后的离线资料，不要求普通运行打开来源中的实现或维护证据；资料里出现的示例源路径仅供无源选型/维护追溯，已有source-case时不展开备用源。未列出不等于不支持。','']
 index.write_text('\n'.join(ix))
 save(HERE/'catalog-build.json',{'catalog_sha256':sha(DEST/'catalog.json'),'coverage':c['coverage'],'generated_files':{p.relative_to(ROOT).as_posix():sha(p) for p in [index,*sorted(DEST.glob('*'))] if p.is_file()},'OFFBEAT_starts':0})
 print(json.dumps(c['coverage'],ensure_ascii=False))

if __name__=='__main__':main()
