# DSH 科学应用契约

在任务工作区执行 `python3 "$MANDIFUEL_PLUGIN_ROOT/scripts/simulation-app.py" --case 相对算例目录 inspect`。未生成应用时，运行层返回已验证的物理绑定、单位、当前值及可用输出。若 available 为 false，报告对应原因。读取用户的目标，自行选择需要开放的参数、输出和显示组件。在当前任务保存 JSON 提案，执行 `create --definition 文件`。同一个算例后续使用 `evolve --version N --definition 文件` 提交完整的新定义，保留仍需要的参数和输出。创建或演化不会启动求解。

| 属性 | 内容 |
|---|---|
| title | 本次应用名称 |
| parameters | 按用户要求排列，每项提供 id、label、binding。binding 从 inspect 返回的 bindings 选择。单位、默认值和读写目标由运行层提供 |
| outputs | 每项提供 id、label、field、kind。field 取自 outputCapabilities。原生物理场使用 kind=field。径向曲线使用 kind=profile 并指定 region。材料单元极值使用 kind=statistic，指定 region 和 reduction |
| components | 可选。每项提供 id、title、type、output。type 可选 table、lineChart、scatterChart、barChart。用 slot 指定 main 或 aside，scope 指定 selected 或 history，x 和 y 指定数据列。表列含 case、已声明参数 id 和 value，曲线另有 radius（m）。历史工况比较可采用一个温度统计量作为 value 并以线功率的参数 id 为横轴 |

若 inspect 列出了 heatFlow，可用 `{"id":"powers","label":"全周热流","kind":"heatFlow"}` 声明四项全周功率，单位 W。一个 table 即可展示项目、正方向、取值方法及数值，随当前已完成工况切换。

通过网页开关首次构建时，请为每个要展示的非 field 输出提供引用其 id 的组件。例如，径向温度曲线用 lineChart 引用 profile 输出；原生 field 输出直接进入已有物理场窗口。

已备候选工况用 `candidate --candidate-case 相对目录` 检查。运行层验证固定输入和未开放的参数，按本应用契约单位返回所有可编辑参数。带来源复算使用 `run --version N --values JSON --candidate-case 同一目录`，提交时再次比对输入并在运行记录保存候选目录。

图表与表格引用输出 id，field 交给工作台已有模型窗口。参数表单、工况选择、执行按钮与证据入口由运行层按实际契约提供。不要提交 HTML、CSS、JS、求解命令或任意文件路径。已有参数的实际复算使用 `run --version N --values '{"参数id":数值}'`。当前物理适配器验证恒物性燃料棒的一种 OFFBEAT 输入族，其他模型需注册并验证物理绑定。
