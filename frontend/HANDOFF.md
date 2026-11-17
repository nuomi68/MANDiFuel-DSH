# 网页任务交付接口

本协议只供独立展示 worker 使用，不注入计算主 agent。计算任务的提示、技能、步骤、回执与普通终端一致；关闭或损坏 UI 不改变求解流程。工作台自动启动独立的展示 worker，按重要节点整理进度、参数和显示选项。主 agent 继续专注输入准备与计算。已有模型的颜色、XYZ 显示缩放、色标、透明度、视角和极值标注由展示子 agent 使用通用 rendering 接口处理；主 agent 不因这些请求重算或另写绘图脚本。网格与交付文件会持续加载，无需等待整轮结束。

## 按需编排展示页面

`presentation.ui` 是受控组件树，不执行 HTML/JavaScript。展示子 agent 的 `facts.uiCapabilities` 给出当前组件目录，`facts.availableTables` 列出真实交付数据表的列、行数和少量样本；`facts.uiState` 反馈浏览器实际挂载的组件与错误。现有配色由前端主题提供，用户没要求改配色时不要重置 `rendering`。

界面与视角更新会等待对应版本的浏览器回执，防止旧状态被当作新指令已执行。真实渲染错误会反馈给展示子 agent，最多自动修正两次；超过限额保留具体错误。浏览器未打开或没有在等待期限内确认时，只标记配置已保存、显示未确认，不宣告显示完成。

布局组件 `row`、`column`、`grid`、`tabs` 可以组合 `lineChart`、`scatterChart`、`table`、`metric`、`text`、`controls`、`button`、`model`。每个节点有唯一 `id` 和 `type`，布局使用 `children`，`grid.columns` 为 1–4。`ui.mode` 可为 `above`、`below`、`replace`，分别在默认模型前后增加面板或用面板替代默认展示；`ui:null` 恢复默认页面。最多 64 个组件、8 层嵌套、一个主模型；双变量模型继续使用 `compare`。这是可扩展的组件目录，新增算法仍需实现相应渲染器，不能生成无效控件或任意脚本。

生成式 UI 的操作项默认归入悬浮“显示设置”。`controls:{id,type:"controls",title,ids:[已有控件ID],placement:"settings"}` 按标题组织已声明控件；省略 placement 也按 settings 处理。视角、网格、剖切、缩放、测点等任意操作组都遵循这个规则，不在主区域重复展示。只有用户明确要求操作与图表并排时才使用 `placement:"inline"`；模型、图表和实际结果放在主区域。原有设置图标与关闭按钮控制面板收起，操作模型不会收起面板。

例如“三张线图”可交付一个三列网格，组件数量和字段由请求决定：

```json
{
  "ui": {
    "version": 1,
    "mode": "replace",
    "root": {
      "id": "resultPlots", "type": "grid", "columns": 3,
      "children": [
        {"id":"temperatureMax","type":"lineChart","title":"最高温度","series":[{"label":"T","source":{"kind":"history","field":"T","statistic":"max"}}]},
        {"id":"temperatureMean","type":"lineChart","title":"平均温度","series":[{"label":"T","source":{"kind":"history","field":"T","statistic":"mean"}}]},
        {"id":"temperatureMin","type":"lineChart","title":"最低温度","series":[{"label":"T","source":{"kind":"history","field":"T","statistic":"min"}}]}
      ]
    }
  }
}
```

该示例要求已经交付真实 `T` 保存帧。`history` 读取全部保存帧的 min/max/mean；`profile` 读取指定字段的实际单元或坐标剖面（`axis:cell/r/x/y/z`、`time:current` 或保存时刻）；`probeHistory` 使用三个坐标表达式，例如 `position:["p.sampleX","p.sampleY","p.sampleZ"]`，读取每帧最近真实单元的值，不作精确插值。坐标参数在 `controls` 声明，可在 `ui` 的参数组或显示设置中按需展示。图表与模型中的 `program.annotations` 可引用同一组坐标参数，保持曲线与测点标注一致。不存在的字段、视图或数据表会拒绝，不能用零或其他物理量代替。

“展示 XY”可直接使用 `viewState:{cameraView:"xy"}`，或按需增加 `button`，其 `action:{type:"view",state:{cameraView:"xy"}}`。`model.state` 接受相同的一次性视图指令。三维观察用 `cameraView:"3d"`；二维轴对称旋转体用 `revolve:true,revolveAngle:270`，二者不代表进行三维求解。持续参数联动放在 `rendering.program.options`，一次性请求使用 `viewState`，避免锁住用户后续手动操作。

若需求必须产生新的采样曲线或派生计算结果，主 agent 复用现有求解结果提取数据，交付真实 JSON 数据表并在清单 `files` 登记：

```json
{"columns":[{"id":"time","label":"时间","unit":"s"},{"id":"value","label":"测点温度","unit":"K"}],"rows":[{"time":0,"value":300}]}
```

上面数字只是格式示意，实际交付必须替换为本任务已计算的值。展示配置用 `ui.datasets:{sample:{file:"delivery/sample.json"}}` 声明文件，曲线序列用 `source:{kind:"dataset",dataset:"sample"},x:"time",y:"value"` 读取。最多 8 份数据表，每份 2 MB、20000 行，工作区外的路径和脚本不被接受。无需为三张图分别写网页或绘图脚本，也不为展示失败重新求解。需要精确点值时，应交付求解器或明确后处理算法得到的实际采样结果，保留方法说明，不能把最近单元值说成精确插值。


## 先确定交付类型

单算例使用下文的模型导出。扫描、优化、反演、批量候选或不确定度任务使用[研究与多参数组交付](STUDY_HANDOFF.md)：先登记已知参数计划，即使尚无响应或网格；再累计更新响应和各组模型。网页默认先显示研究总览，不能把整个任务覆盖为最后一个case。

多参数组导出模型时使用 `--no-handoff`，每组使用独立文件名，再由 `export_study.py` 统一登记。新的图表、变量标签和模型绑定均由数据定义，不要求用户手动配置网页。求解和算法继续由已有Skills负责，前端交付不启动求解器，也不更换优化算法。

这是现成的结果导出工具，只调用已有结果公共 API，不启动求解，也不修改输入。正常计算仍按已加载的 MANDiFuel Skills 执行。不要读取或改写导出器、解析器及求解器源码。

交付应随实际步骤持续进行：网格就绪先登记网格，已有完整保存场时登记结果，后续保存帧到达后更新同一结果文件；不能等全部计算与报告结束才首次交付。导出只读取已保存数据，不重新求解。单算例尚无人工交付时，宿主可自动预览唯一计算根中的网格和保存场；多计算根的归属必须用研究计划显式声明，不能猜测。

例如，在本任务工作区导出当前已保存结果：

```sh
python3 /home/lwz/MANDiFuel-DSH-lwz/frontend/export_case.py --case ./case --output ./delivery/viewer.json --title '燃料棒温度' --fields T --time latest
```

`--case` 必须是本任务工作区内的实际结果根。默认输出原始网格，可显示任意拓扑模型，不需要匹配已见案例。`--fields` 支持多个字段；分量写作 `D:x`、`sigma:principal_max` 等。只导出请求相关量，不为导出或绘图失败重复求解。

`--time all` 导出全部已保存时间帧，`--time 具体目录值` 导出指定时刻。默认从 controlDict 核验用户时间单位（如 `userTime { type days; }` 对应 d），不转换保存时刻的数值；无法核验时须显式指定匹配的 `--time-unit`，不得把天标成秒。

只有确认是径向一维模型时才可指定 `--shape sphere|shell|rod` 进行对称重建，并提供真实尺寸：`--radius 外半径`、`--inner-radius 内半径`，棒形还需 `--length 长度`。几何参数均使用米。重建不替代原始计算网格；位移不会自动放大几何。

二维轴对称 wedge 网格使用 `--shape revolve --axis z --sweep-angle 270`，可将真实截面绕指定轴展开为 3/4 圈立体模型。导出器验证 wedge 约束、旋转轴和单元覆盖，逐原始单元复制场值；这是二维解的显示重建，不能宣称为三维求解。普通二维平面与一维径向模型不能套用此入口。旋转重建保留现有材料间隙；原始网格须作为独立视图同时交付。旋转重建提供外表面和已有剖口，内部切片继续使用原始网格视图。观察信息的 sliceLimitations 列出含非凸单元的帧；相交非凸单元仍会明确报错，应选有效切面或表面视图。

```sh
python3 /home/lwz/MANDiFuel-DSH-lwz/frontend/export_case.py --case ./case --fields T sigma:von_mises --time latest --output delivery/raw.json --no-handoff
python3 /home/lwz/MANDiFuel-DSH-lwz/frontend/export_case.py --case ./case --fields T sigma:von_mises --time latest --shape revolve --axis z --sweep-angle 270 --output delivery/revolve.json --no-handoff
```

`--time` 也接受逗号分隔的真实保存目录，例如 `--time 718866.7,50000000`，用于明确选择展示帧。大规模动网格历史按 64 MB 数据包上限拆分，不能为减少后处理工作而重算。`sigma:von_mises` 从实际应力张量派生等效应力；`sigma:principal_max` 是最大主应力，二者不可静默替换。

新导出的结果带真实单元中心，可用 `controls: [{"id":"extrema","default":true}]` 开启模型上的最大最小值标签。统计范围为**当前字段、当前保存帧的全域原始单元**，不随剖切缩小；虚线标记表示单元中心的透视位置。并列极值取一个代表单元并注明数量，恒定场合并为“最大＝最小”。标签随字段、时间、相机和双变量比较同步，PNG 包含标签。旧数据缺少单元中心时重新导出已有结果即可，无需求解。

声明 `deliveryRequirements: {"reconstruction":"axisymmetric-revolve","axis":"z","angle":270,"extrema":true}` 后，只有真实默认视图满足重建要求、保留原始网格，并启用有效极值标注，才可把渲染阶段标成 `done`。相机切到三维或只修改摘要不能通过交付校验。`axialScale` 只适用于 `rod`，不得用于原始网格或球形旋转重建。

导出器在 `delivery/` 自动写出 `viewer.json` 和 `workbench.json`。后者登记输入卡、结果根与可视化文件，网页会持续校验并自动加载；本轮结束时还会复核一次。生成的文件路径须位于本任务工作区内；不要写前端应用目录，不要请求开放其他端口或联网。

可以在 `workbench.json` 增加 `files` 相对路径数组登记报告、CSV 等交付文件。输入卡通过 `inputs` 登记。只登记本次真实存在且愿意交付的文件；求解失败时保留诊断并明确说明，不能生成伪结果。

仅准备输入卡、不执行求解的任务，可以只写 `delivery/workbench.json`，包含 `schema: "mandifuel.handoff/v1"` 和 `inputs` / `files` 路径数组，省略 `viewer`。网页会显示交付文件，不伪造求解模型。


## 求解前先展示网格

网格生成后即可交付，不需要任何结果场：

```sh
python3 /home/lwz/MANDiFuel-DSH-lwz/frontend/export_case.py --case ./case --mesh-only --output ./delivery/mesh.json
```

网格预览使用独立格式，不包含伪造的温度、浓度或时间帧。后续交付真实结果会更新模型。默认原始网格和有明确几何依据的对称重建可以同时保留。

## 可定制的展示内容

`workbench.json` 可带 `presentation` 对象，展示子 agent 也通过同一校验接口更新它：

```json
{
  "progress": {"summary": "网格已就绪，正在准备求解", "stages": [{"id": "mesh", "label": "网格", "status": "done"}, {"id": "solve", "label": "求解", "status": "active"}]},
  "parameters": [{"title": "模型尺寸", "items": [{"label": "长度", "value": "120", "unit": "mm"}]}],
  "controls": [{"id": "mesh", "label": "显示网格线", "default": true}, {"id": "cut", "label": "剖切", "default": false}]
}
```

参数分组、条目和控件列表可以整组替换，不限定物理模型种类。可用渲染能力包括 `cut`、`cutAngle`、`mesh`、`scale`、`axialScale`、`view`、`extrema`，以及下述正交视角、切片和比较控件；配置只决定内容、标签、范围、默认值及是否出现，不执行任意网页代码。

多视图清单使用 `views: [{"id":"raw","label":"原始网格","viewer":"delivery/raw.json"},{"id":"rod","label":"对称重建","viewer":"delivery/rod.json"}]`，用 `defaultView` 指定初始视图。在 `controls` 添加 `{"id":"view","label":"模型显示方式"}` 后即可切换。每个模型都要来自真实数据；改变展示方式不触发重新求解。


## Agent 自定义参数面板与显示程序

前端提供通用面板、基础控件和表达式执行能力；具体参数由 agent 按当前用户要求定义，不需要提前在前端登记参数名称或形状类型。默认只保留视图导航，不自动罗列缩放、配色等所有能力。`controls` 支持任意唯一 ID，声明 `type` 为 number/range/toggle/select/color/text，以及 label、default、min/max/step、unit、group、help、options。窗口标题固定为“显示设置”；可用简短的 panelDescription 补充单位或操作说明，使用自然功能组名称，不显示“按用户需求生成”等实现性措辞。

例如，下列数据定义把 XY 长方形显示为梯形，并提供上底、下底和高度参数。示例按模型坐标单位设置尺寸；其他平面需相应选择坐标方向，不能直接照套。

```json
{
  "controls": [
    {"id":"upperBase","type":"number","label":"上底","default":2,"min":0.1,"unit":"m","group":"形状"},
    {"id":"lowerBase","type":"number","label":"下底","default":6,"min":0.1,"unit":"m","group":"形状"},
    {"id":"displayHeight","type":"number","label":"高度","default":3,"min":0.1,"unit":"m","group":"形状"}
  ],
  "rendering": {"program": {
    "label": "用户定义的外形",
    "vertex": [
      "centerX+(x-centerX)*mix(p.lowerBase,p.upperBase,(y-minY)/sizeY)/sizeX",
      "minY+(y-minY)*p.displayHeight/sizeY",
      "z"
    ]
  }}
}
```

这不是预制梯形组件。`vertex` 的三个表达式作用于原始网格的 x/y/z，使用 `p.参数ID` 读取任意新参数；上下文包含各轴 min/max/size/center，支持算术、比较和声明的数学函数。相同执行器可由不同表达式实现剪切、扭转等显示变换。`program.style` 则把参数表达式绑定到基础样式目标，例如 `{"opacity":"p.surfaceAlpha","scaleX":"p.horizontalFactor","wireColor":"p.edgeTint"}`。完整基础执行能力由观察接口的 renderingCapabilities 返回。表达式不执行 JavaScript 或读取文件、网络、DOM。

用户手动修改参数时直接更新渲染，并把实际值保存到 presentation.parameterValues，供下一次 agent 指令复用。agent 可用 `parameterValues:{"upperBase":4}` 仅更新数值，或替换 controls 增删参数。新增参数必须实际被显示程序使用或有明确用途，不能只画出输入框却不接到渲染。`program:null` 取消显示程序；显示变换与原始求解结果分开标注，原始单元场值不变。顶点变换需要原始网格或已交付重建网格；一维径向重建应先交付网格视图。

## 按用户指令调整渲染

展示 agent 使用 `rendering` 更新通用渲染配置，不依赖固定案例或固定窗口元素。主 agent 沿用本接口交付真实数据；颜色、缩放、视角和标注变化不重新导出、不重新求解。

```json
{
  "rendering": {
    "scale": [2, 0.5, 1],
    "palette": "viridis",
    "opacity": 0.8,
    "background": "#ffffff",
    "wireColor": "#334455",
    "fields": {"T": {"palette": "inferno", "range": [1290, 1380]}}
  }
}
```

XYZ 显示倍率为 0.01–100，窗口和 PNG 会标注显示缩放，真实数据与单元位置不变。色带支持 coolwarm、viridis、inferno、gray、rainbow，也支持自定义色阶数组，例如 `[[0,"#0000ff"],[0.5,"#00ff00"],[1,"#ff0000"]]`；首尾必须为 0 和 1，中间位置严格递增，颜色使用 #RRGGBB。`reversePalette` 反转色带。`opacity` 是 0.05–1 的表面不透明度。字段可分别指定色带、反转和色标区间，范围使用该字段实际单位；`range:null` 取消该字段固定区间。后续仅发送改变的属性，宿主合并并保留其他设置；`reset:true` 恢复默认。

可公开的显示控件包括 `scaleX/scaleY/scaleZ`（数字）、`palette`、`reversePalette`、`opacity`、`background`、`wireColor`，以及 `colorMin/colorMax`（配合 scale 的 custom 模式，调整当前变量色标）。相机、线框、切片、双变量、时间与极值继续使用既有配置。窗口、图例与 PNG 共用色带及范围。未知属性、字段和非法范围会返回明确错误，交由展示 agent 根据反馈调整；尚未支持的功能须如实说明。

## 二维、三维与多变量

原始网格导出会保留实际单元边拓扑，支持正交XY/XZ/YZ观察和凸多面体的内部切片；切片采用相交单元的原始场值，不作未声明的插值。非凸单元切片明确报告限制，外表面仍可显示。通过empty/wedge边界识别降维约束，不能仅凭case_3d目录名或重建外观宣称真正三维。

前端导出器还支持 `D:mag` / `D:magnitude`，使用已有D:x/y/z组合计算位移幅值；这是导出器派生量，不代表result_api直接提供mag分量。多字段按共同保存时刻对齐，不回填缺失帧。

显示配置新增：cameraView（auto/3d/xy/xz/yz）、displayMode（surface/slice）、sliceAxis（x/y/z）、slicePosition（0–1）、compare（布尔）、compareField（实际字段id）。compare开启后在固定模型区域内并排显示两个变量，相机和时间同步，两边保留各自单位和色标。只有实际存在多个字段时提供比较。原始网格且带内部拓扑时才提供切片。

`aspectMode` 可取 `physical`（保持几何比例，默认）或 `fit`（按两个屏幕坐标分别展开）。仅对二维正交显示生效；展开后会明确标注“坐标缩放”，截图也带此标记，不应把屏幕长宽比解释为真实几何比例。


径向棒的对称重建如有气隙，CLI也可直接提供实体材料区：

```sh
python3 /home/lwz/MANDiFuel-DSH-lwz/frontend/export_case.py --case cases/a --fields T --shape rod --radius 0.00485 --length 0.12 --radial-bands '[[0,0.0041,40],[0.00425,0.00485,12]]' --output delivery/a/rod.json --no-handoff
```

各段只覆盖真实实体，气隙0.0041–0.00425m省略；各段格数总和必须等于导出单元数。不能省略材料分段而用均匀实体填满气隙。改变显示不重新求解。

标题摘要和“执行过程”使用同一份progress历史。只在真实阶段、进度数量或状态变化时更新中文summary/stages，不为每个读文件或工具调用发布一条进度。参数或控件单独变化不会增加进度条目。交付文件按files/inputs登记后显示在页面底部的目录与只读文本区；更新同名文件无需修改前端或重新求解。

XYZ 显示缩放控件按需出现：无缩放请求且倍率均为 1 时不列出系数；存在非 1 倍缩放时保留参数以便查看调整。用户只要求展开缩放参数时，可设置 `rendering.showScaleControls:true` 并加入 `scaleX/scaleY/scaleZ` 控件。`reset:true` 恢复默认并隐藏。显示设置和模型参数抽屉打开时，模型区保持清晰，便于观察同步更新。

## 按需求组合便利操作

默认面板只提供观察方向、线框、色标范围以及已有视图切换。用户提出具体要求后，agent 复用基础项，并按需追加自然命名的功能组；不一次性罗列全部渲染能力。窗口固定称“显示设置”，不能改成“按用户需求生成的参数”。

通用 program 还可组合以下基础执行能力，所有参数 ID 仍由 agent 定义：

- `options`：cameraView/aspectMode、mesh/cut/cutAngle、displayMode/sliceAxis/slicePosition、compare/compareField、field、time、extrema/extremaMode，以及 zoom/yaw/tilt（度）。切片必须使用有内部拓扑的原始网格；time 选择最近实际保存帧；extremaMode 可选 both/max/min。
- `fields`：按实际字段 ID 设置表达式 range、palette、reversePalette。字段各自保留真实单位，数值不因配色改变。
- `annotations`：point/probe/line/arrow，使用 position 三个坐标表达式，可选 end、text/color/visible 表达式及 label。probe 用 field 指定实际字段或 selected；读取最近存储单元值，轴对称重建按径向-轴向距离选单元。标注进入截图，随时间、视角和显示变换同步。

例如，用户要求显示某点温度，可以在现有 controls 后加入三个坐标参数（用适合模型的单位），并追加：

```json
{"id":"temperaturePoint","type":"probe","label":"测点 1","position":["p.locationX","p.locationY","p.locationZ"],"field":"T"}
```

这里 locationX/Y/Z 只是示例 ID。用户使用 μm 输入时，表达式显式乘 1e-6 转换为模型坐标 m；可用其他名称、其他单位、更多测点或组合标注，不需要修改前端。用户只要某个点的文字说明时可用 point 和 text；指示方向或两点距离可用 line/arrow 与数学表达式。只有实际具备所需字段和单元中心时才发布点值，不以初值或伪造数值替代。

一次性的“切到应力、跳到某时刻、再转 30°”使用顶层 `viewState`，例如 `{"viewState":{"view":"raw","field":"T","time":50000000,"cameraView":"3d","yaw":90,"tilt":20}}`。这些直接值仅在该次交付应用，用户仍能继续手动操作；需要保留可调输入时才用 `program.options`。已有响应式绑定优先，应修改相应参数值或移除该绑定，避免同一项相互覆盖。`viewState` 不替代 `defaultView` 的交付默认视图。

观察接口的 `viewerState` 返回浏览器当前实际视图、变量、时间、相机及 `rendererError`，结合 `presentation.parameterValues` 处理后续或相对指令。观察相机的 yaw/tilt 是弧度，交付 viewState/program.options 时转换为度。面板参数变化只在浏览器执行与保存，不发起新的 agent 回合或求解。

普通终端 Study 历史可通过展示 API 的 studyMapping:{history,study} 映射；参数和响应定义使用显式 source 路径，宿主读取真实记录并在观察侧生成研究表。计算主 agent 无需写前端协议，也无需知道生成式 UI 存在。展示 worker 使用独立宿主上下文，不是计算 agent 的子会话，不往其消息队列回写完成通知。

## 按分析目的组合图表与表格

默认不再展示按单元编号连线的“单元场分布”。图表由展示 worker 根据需求和真实数据组织。通用 chart 支持同图 line/scatter/bar/interval 图元、点形与线型、阶梯线、线性/对数轴、参考线与容差带、图例；heatmapChart 支持真实二维采样矩阵、数值标注和缺失格。科学单位与数据缺口保持原义，不自动平滑、插值或平均重复格。

source:{kind:"study",status:"completed"} 直接读取当前研究表，无需模型或主 agent 导出。列名 parameter.<id>/response.<id>，另有 record/runId/label/status/statusCode/iteration/caseRoot。status 是中文显示文字，statusCode 是 completed 等原始状态代码。record只是保存顺序；iteration 仅在真实记录中存在时提供。best:<目标响应ID> 添加该目标的累计最好可行值列 best.<目标ID>；再设置 select:"best" 可读取最佳可行工况的参数及响应，列名仍用 parameter.<id>/response.<id>。没有可行工况时不产生数值。

图、表、指标及筛选器的列引用在发布前按实际数据校验；错误反馈会列出可用列。指标的真实数据尚未产生时显示“暂无有效值”，不补零。数据缓存包含 UI 版本和映射定义，防止更换列配置时复用旧投影。

表格可在主区域与图并列或放入 tabs。columns 支持列 ID 或格式配置（label/unit/format/digits/align），可搜索、排序、分页和突出真实最小/最大值。缺失值显示破折号，CSV保留原值。ui.scope:"overview" 可只替换研究总览，同时保留独立模型页；默认scope:"all"兼容现有布局。

示例：反求任务可组合实际响应散点与目标线、偏差对数图、真实上下界区间图和逐次数据表。没有上下界列时不生成区间，正数条件不满足时不使用对数轴。具体字段、数量和布局都由当前需求决定。完整属性以观察接口 uiCapabilities 为准。

网页交互由渲染器统一提供：悬停读数、键盘点选、工况联动、图例开关、数值坐标框选缩放/复位及全屏。study 源携带真实 runId；dataset 源通过 `runId:"真实工况ID所在列"` 显式关联研究表，发布前核对 ID。不得按行号、数值近似或目录猜工况。数据表行和图点共享选择，查看模型只打开该组已保存视图，不触发求解。缩放与图例开关只改显示，CSV保留完整数据。

`ui.aside` 是 DSH 聊天窗下方的可选组件树，和 `ui.root` 共用验证、绑定与节点限制。可自由组合表格、辅助图、总结和本地图片；聊天收起或窄屏时移到主区下方，保留交互状态。相关图表优先使用 tabs，避免左侧无限铺长；左右内容长度大致协调，不为填空重复内容。`image:{file,alt,caption?}` 只加载声明的工作区 PNG/JPEG/WebP（10 MB以内）；图片是已有图像的展示能力，不能冒充新计算结果。

页面和浏览器标签标题跟随 DSH 的持久化 session/title；首次打开已有会话也同步标题。计算主 agent 不接收标题或 UI 要求。力学任务的 preview.fields 按实际请求和保存字段选择位移/应力，不把均匀的 T 当作完整结果交付；二维平面应变仍按真实二维几何展示。

普通终端任务不必创建 delivery 目录。监听器自行建立观察索引，先登记文件，再把模型导出交给独立队列；索引提交失败会在文件未变时重试。可识别工作区内浅层报告、CSV、说明和图片，并把 JSON 中任意记录数组及少量上下文提供给展示 worker，例如 results/result.json 的 quantities，而非只支持固定文件名或 rows。不扫描源库、尝试目录和算例数值场来凑报告。

首次发现已有稳定结果会补唤醒，独立 worker 使用工作台默认模型，不要求计算 agent 常驻。最多两个展示生成同时运行，各任务合并通知；生成超时120秒，有界重试并携带被拒绝的配置和校验反馈，避免丢掉修复上下文。模型导出与文件发现分离，重启不重复导出未变的预览。health 接口和 observe 的 observer 字段报告扫描位置、文件错误、导出队列与错误，不能用吞异常后标记成功代替。

单工况没有研究分页时，model/overview 作用域都作用于唯一任务页面。显示程序若引用 p.mesh、p.cameraView 等兼容名称，声明的同名控件会作为参数绑定，不因保留名称失效。显示导出器接受 nFaces=0 的合法空边界占位符，保留原始网格文件；指定温度时只解析温度等实际选择字段，不反复解析所有无关场。所有这些流程均不运行求解器、不更改输入或执行回执。

展示 worker 可直接用 `ui.datasets:{power:{file:"results/power_terms.csv"}}` 读取带表头的 CSV，使用真实表头列名。空单元格是缺失值，有限数字按数值读取，前导零标识和大整数保持文字；不执行公式，不改写源文件。JSON 映射继续可用。`profile` 源是全体单元集合，多维场不能未经截面采样就连成一条径向曲线；优先绑定真实采样 CSV/JSON，并注明截面/窗口与已采用的平均方法。
