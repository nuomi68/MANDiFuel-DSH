# 模型与显示程序

rendering.program:{label:显示变换说明,vertex?:[x表达式,y表达式,z表达式],style?:{基础渲染目标:表达式}}。使用 p.任意参数ID 读取 controls 中的自定义参数，vertex 的表达式作用于原始网格坐标 x/y/z；上下文有 minX/maxX/sizeX/centerX 及对应 Y/Z（当前真实模型坐标范围；views 中 coordinateBounds 可用于选择默认尺寸与单位）。算术 + - * / % **、单次比较和函数 abs/min/max/sin/cos/tan/sqrt/pow/exp/log/clamp/mix/select 可组合成新的显示逻辑；不需要新增前端专用功能。表达式只读坐标和参数，不是 JavaScript，不允许 DOM、网络或其他代码。style 可绑定 scaleX/scaleY/scaleZ、opacity、palette、reversePalette、wireColor、background；它们是基础渲染执行目标，面板参数 ID 由你命名，不必与目标同名。program.options 绑定 cameraView/aspectMode、mesh/cut/cutAngle、displayMode/sliceAxis/slicePosition、compare/compareField、field、time、extrema/extremaMode，以及 zoom/yaw/tilt（角度为度）。program.fields:{实际字段ID:{range:[下限表达式,上限表达式],palette:表达式,reversePalette:表达式}} 用于逐字段调整。time 选择最近的实际保存帧，不生成不存在的结果。切片需要原始内部拓扑，不能假装重建表面具备内部切片。views 的 sliceLimitations 会列出含非凸单元的保存帧；当前引擎不能处理相交的非凸单元，需结合 rendererError 选择有效时间、切面或表面视图。

例：用户要把 XY 长方形显示成梯形，你可创建 upperBase/lowerBase/displayHeight 三个数字参数，标注模型真实长度单位，然后交付 vertex:["centerX+(x-centerX)*mix(p.lowerBase,p.upperBase,(y-minY)/sizeY)/sizeX","minY+(y-minY)*p.displayHeight/sizeY","z"]。这是表达式用法示例；其他剪切、扭转、弯曲同样由表达式定义。先依据真实二维平面选择坐标方向，不能把 XY 公式硬套到 XZ。参数改动由前端直接更新形状、法向、极值位置和截图，保留原始单元场值；明确称为显示变换，不宣称改变了物理计算。

program.annotations:[{id,type:"point"|"probe"|"line"|"arrow",label?,position:[x表达式,y表达式,z表达式],end?:[终点三表达式],text?:表达式,color?:表达式,visible?:布尔表达式,field?:实际字段ID|"selected"}]。point 是坐标点/文字标注，line/arrow 可配合坐标与距离表达式用于指示和测量，probe 读取当前保存帧的实际场。用户要求标注点值时，根据模型坐标单位添加必要的坐标输入，在 position 中引用这些参数，使用 probe，默认跟随当前字段；明确请求温度或应力时绑定实际字段。probe 显示最近存储单元的值，不能宣称为精确插值。轴对称重建使用径向-轴向的等效最近单元。标注随字段、时间、相机和显示变换更新，并进入截图。坐标、文字、颜色、可见性都可由自定义参数绑定；不必固定成三个预置坐标控件。

球壳内、外表面读数使用 `boundaryProbe`。例如 `{id:"outerStress",type:"boundaryProbe",patch:"outer",field:"sigma_yy",views:["shell"]}`。先读 model.views 对应的 boundaryPatches，旧视图缺少边界记录时从同一算例重新导出 shell。标签只写边界或分量的名称。半径、面号、单位和当前数值由渲染器按保存帧填写，切换帧时一同更新。通过 model.actualDisplay.boundarySamples 核对实际显示的字段、带符号值、单位、面号和米制面中心；按请求核对环向分量的坐标基底。

可以组合视角、独立色标、透明度、背景、形状显示、切片、变量比较、保存时间、极值、点值和说明标注来满足用户要求。逐字段色标和标注允许分别设置；新增便利参数前先看已有面板，避免重复。只为当前要求添加有实际绑定的参数，不需要一次展示所有基础能力。界面中不要出现“用户定义的”“按需求生成的”等技术性标题；使用“显示缩放”“测点 1”“温度色标”这样的自然名称。无法由当前引擎完成的高级渲染算法须明确说明缺口，而不是生成无效输入框。

检查显示控件是否形成闭环：原生 scale 控件的 custom 模式由宿主提供当前变量上下限输入；若用 program.fields.range 自行绑定色标，就提供相应参数，避免再创建会被该绑定覆盖的原生 scale 控件。不要让两个不同参数同时控制同一选项。只有一个保存帧时 fixed 和 frame 范围相同是正常的，应以实际色标范围核验。ui_inspect(model).actualDisplay.fieldMapping 包含实际映射的顶点数、采样范围、色标范围及剖切状态，字段映射无效会产生 rendererError。

同一算例、时刻的原始网格与对称重建是同一批物理结果的两种显示，应保留相同字段 ID、selector、标签、单位及数据；切换几何不要只重新导出位移或温度。先检查已有视图和真实字段目录，复用已经选中的变量，补充用户所需且确实保存的应力、应变等分量。完整球壳只露出内外表面，壁厚中的极值可能被遮挡；需要展示径向物理场时可使用已有 cut/cutAngle 剖口，并保留关闭剖口的操作。半透明只是外观调整，不能代替壁厚剖口，也不能据球面近似同色判断场值丢失。

原始一维径向窄楔网格不提供角向剖口，以免裁掉全部单元；同一任务切回原始网格时宿主会保留可见的原始场，剖口可在球壳重建模式下调整。

viewState:{view?:实际已交付视图ID,field?,compareField?,time?,cameraView?,displayMode?,sliceAxis?,slicePosition?,compare?,mesh?,cut?,cutAngle?,extrema?,extremaMode?,aspectMode?,scale?,zoom?,yaw?,tilt?} 用于一次性的视图指令，例如切到已有原始视图、选择某个真实保存时间或转到指定角度；直接填写值，不是表达式，不会锁住用户后续手动操作。持续由参数调整的功能才用 program.options。已有参数绑定优先于一次性值；修改同一项时更新对应 parameterValues 或移除该绑定，避免相互覆盖。ui_inspect(model).viewer 返回用户当前实际视图、字段、时间、相机和 rendererError；camera 内 yaw/tilt 是弧度，交付 viewState/program.options 的 yaw/tilt 使用度。先依据实际状态处理“再转30度”“当前点”等相对要求，不能假定仍是默认视图。参数操作不会自动再次调用你。

rendering 还支持基础样式 scale:[X,Y,Z]、palette（coolwarm/viridis/inferno/gray/rainbow 或自定义 [[0,"#RRGGBB"],...,[1,"#RRGGBB"]] 色阶）、reversePalette、opacity（0.05–1）、background/wireColor（#RRGGBB）、fields:{实际字段ID:{palette?,reversePalette?,range?:[下限,上限]|null}}、reset:true。样式与 program 都是显示配置，窗口、图例、极值与 PNG 共用它们。program:null 取消当前显示程序。未知基础执行能力应明确反馈，不编造控件或结果。渲染基础能力的限制不等于参数 ID 白名单。

已有交付的 view/cameraView/cut/mesh/scale/compare/compareField/extrema 等控件 ID 继续兼容；新需求优先使用自定义参数定义与 program 绑定，不为特定形状添加前端代码。viewState/program.options 还支持 revolve:布尔、revolveAngle:1到360，用已有二维轴对称截面实时旋转显示；不需要为改变显示角度重新导出。三维 cameraView 只改变观察方向，不会把普通平面结果伪造成三维求解；需要轴对称旋转体时显式使用 revolve。XY/XZ/YZ 是实际正视方向。一次性请求使用 viewState，不要无故添加锁定用户视角的 program.options.cameraView。

二维轴对称 wedge 截面可使用 shape revolve、axis 实际旋转轴、sweepAngle 270 生成 3/4 圈旋转体，并保留一个 shape mesh 的原始结果视图；所有值逐原始单元映射，不把它宣称为三维求解。相机的三维视角不会生成旋转体；axialScale 只对 rod 有效，不能给 mesh 配置拉伸。旋转重建只支持表面与已有剖口，不支持内部切片。用户明确要求时，可通过 controls 中的 {id:"extrema",default:true} 标注当前帧全域最大最小值及单元中心位置（透视标记、并列时用代表单元），随字段和时间变化并包含在PNG中。旧视图 task.supportsExtrema 不为 true 时先重新导出已有结果，不能假定能标注位置。

deliveryRequirements:{reconstruction?:"axisymmetric-revolve",axis?,angle?,extrema?:true} 用于声明这次必须交付的能力；优先遵循 ui_inspect(data).deliveryRequirements。完成阶段须有满足要求的真实默认视图和有效标注配置，不能只修改进度文字或生成到临时目录就报告完成。纯显示请求直接复用已保存场，禁止重算。字段缺失保留原语义并反馈；需要等效应力时可显式选择 sigma:von_mises（从实际张量派生），不要替换成 principal_max 后沿用等效应力标签。

默认保留真实网格视图；只有确认是一维径向模型、尺寸确切且单位已换成米时才能额外交付 rod/sphere/shell 对称重建；这时保留原始网格和重建两个可选视图并增加 view 控件。燃料与包壳之间有气隙时，根据明确的区域尺寸及格数提供 radialBands，避免把气隙填成实体。radialBands 只列实体区，空隙直接省略，不要列0格空隙段；各区格数是正整数，总和等于 cells；radius 必须取所有实体的最外半径，含包壳棒使用包壳外半径，不是燃料半径；棒形重建可默认剖切以显示内部场。优先遵循 task.latestRequest 中最新的展示要求。不能把计算域积分当全模型结果，不能发明参数或浓度/温度数值。

材料界面可用通用圆形导引标注：`{id:"interfaceA",type:"circle",position:["0","0","0"],radius:"2.5e-4",axis:"y",label:"材料界面 · 250 μm",views:["真实视图ID"]}`。
axis 为圆平面的法向轴，半径和位置单位与原始网格相同（通常米）；圆仅为几何导引，不是新的计算结果。
按实际材料区域声明 views，裸核不显示不存在的涂层。半径来自真实网格/模型记录，不能按外观猜测。
新增 probe 时保留原有 annotations；不要用只含新测点的列表覆盖已有界面。
