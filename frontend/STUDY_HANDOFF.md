# 研究与多参数组交付

此接口服务扫描、候选优选、自适应优化及不确定度等多次求解任务。前端只展示已有数据；求解、采样与优化算法由已加载的Skills管理。

## 运行时流程

计算主 agent 采用普通终端流程，只保存实际输入、执行回执、参数历史与报告。本接口只供旁路展示 worker 使用，不加入主 agent 的提示、技能或步骤。

监听器识别普通 Study 的 history.json 后，展示 worker 可提交 studyMapping，显式指定参数和响应的 source 路径、单位及预览字段。观察侧独立建立研究表，并随原始历史累计更新；不会让主 agent 调用前端导出器。已有明确的 mandifuel.study/v1 定义也继续兼容。

每个模型按 caseRoot 归属参数组。只读导出与模型绑定由展示侧完成；工具和浏览器失败只影响展示状态。下列 CLI 是展示服务的工具入口，无需计算主 agent 调用：

```sh
python3 /home/lwz/MANDiFuel-DSH-lwz/frontend/export_case.py \
  --case cases/a --fields T --time latest \
  --output delivery/a/viewer.json --no-handoff

python3 /home/lwz/MANDiFuel-DSH-lwz/frontend/export_study.py \
  --definition study-view.json --output delivery/study.json
```

所有路径都必须属于当前任务工作区。登记器自动合并视图，写出`delivery/study.json`以及根清单`delivery/workbench.json`；不启动求解器。

## 直接交付格式

`study-view.json`示意如下，示例数值仅说明格式，实际响应必须来自本任务的正常完成记录。

```json
{
  "study": {
    "schema": "mandifuel.study/v1",
    "kind": "scan",
    "label": "燃料棒孔半径扫描",
    "parameters": [{"id": "hole", "label": "孔半径", "unit": "mm"}],
    "responses": [{"id": "maxT", "label": "燃料最高温度", "unit": "K", "goal": "min", "bounds": {"max": 1300}}],
    "runs": [
      {"id": "a", "label": "孔半径0.5mm", "status": "completed", "parameters": {"hole": 0.5}, "responses": {"maxT": 1235.47}, "caseRoot": "cases/a", "viewIds": ["a-temperature"], "defaultView": "a-temperature"},
      {"id": "b", "label": "孔半径0.75mm", "status": "queued", "parameters": {"hole": 0.75}, "responses": {}, "viewIds": []}
    ],
    "defaultRun": "a"
  },
  "views": [{"id": "a-temperature", "label": "温度结果", "viewer": "delivery/a/viewer.json"}]
}
```

`kind`为`scan`、`optimization`或`uncertainty`。id只用于稳定关联，界面优先显示label；省略组label时用参数名称和值生成。定义支持数值参数；类别参数使用`type: "category"`，值为字符串。所有响应为有限数值；缺失值省略或置null，不填0。参数与响应id不可重名。

状态支持queued/running/completed/failed/skipped。queued组可以登记已生成的网格，不能登记响应或结果场；failed和skipped组不得登记响应或结果视图。running组可显示已经写出的真实保存场，但仍保持运行中状态和缺失响应，不代表正常完成。失败原因放`error`，修复后新尝试可以使用独立id保留轨迹。

`viewIds`只列本组视图，例如本组原始网格、温度结果和有依据的重建；同一视图id不得归属不同组。`caseRoot`提供时必须与其模型实际计算目录一致。没有模型的组也可显示标量响应图，但选择该组不能沿用别组模型。

优化响应可设置`goal: "min"|"max"`，约束通过`bounds.min/max`声明，单位与响应相同。最好可行值只使用正常完成、目标响应存在、且所有已声明响应约束满足的组；缺少约束响应不当作满足。双目标响应图仅标记已评价候选的非支配集，不宣称全局最优或算法收敛。`iteration`可提供评价横坐标；省略时按记录顺序编号，不猜测优化器代数。

## 复用已有Study历史

`--history history.json`读取已有共享Study历史，definition中的study字段此时作为映射配置。显式指定source路径，避免根据名称猜单位或拿优化惩罚当物理响应：

```json
{
  "study": {
    "kind": "scan",
    "label": "孔半径研究",
    "parameters": [{"id": "hole", "label": "孔半径", "unit": "mm", "source": "point.r_inner_mm"}],
    "responses": [{"id": "maxT", "label": "燃料最高温度", "unit": "K", "source": "reporting_response.fuel_T_max_K", "goal": "min"}],
    "models": {"p01": {"caseRoot": "cases/p01", "viewIds": ["p01-temperature"]}}
  },
  "views": [{"id": "p01-temperature", "label": "温度", "viewer": "delivery/p01/viewer.json"}]
}
```

```sh
python3 /home/lwz/MANDiFuel-DSH-lwz/frontend/export_study.py \
  --history history.json --definition study-view.json
```

正常完成的记录才提供响应；prepare_failed等状态保留为failed；提取失败或缺失的响应保持缺失。中文或不适合内部id的原始点名自动转成稳定id，models映射仍用原始点名。适配器不会重新运行、重新提取或猜测模型目录；模型绑定由已知的case与导出路径明确提供。

## 自定义图表与后续模型

省略charts时按任务类型生成默认组合。需要换变量或图表时，可在study定义加入：

```json
{
  "charts": [
    {"id": "history", "type": "history", "label": "温度优化进展", "y": "maxT"},
    {"id": "response", "type": "response", "label": "孔半径与温度", "x": "hole", "y": "maxT"},
    {"id": "distribution", "type": "histogram", "label": "温度分布", "y": "maxT"}
  ],
  "defaultChart": "history"
}
```

支持response/scatter/history/histogram/cdf。横轴可以是已定义的输入或响应，纵轴是已定义响应。参数响应连线只连接其余输入参数相同的点，避免把多参数混合点误画成一条单变量响应。类别输入使用离散坐标。主agent可累计更新数据定义，展示子agent可通过`study: "delivery/study.json"`附加已有研究文件；不能凭描述编造数值或把不同组普通exports混在一起。

分布、均值、P5/P95和经验CDF当前按等权正常有效样本计算，P5/P95采用线性插值经验分位数，不能称为置信区间。非等权、MCMC相关样本、代理模型置信带或Sobol指数需要专门交付与图表能力，当前不可用这套等权摘要替代。

每组模型仍使用原有动态显示控件，字段、单位、网格与切片均来自该组文件。组切换按同单位的物理时间寻找相同或最近的保存状态，显示实际时刻；不同时间单位不自动换算。当前支持逐组切换；跨参数组并排模型、统一场值色标和跨组包络线尚未提供。

单份研究最多10000组，单个模型JSON仍受64MB限制。总览只请求标量研究数据；选中模型再取对应场。服务器缓存最多3份且总JSON文件体积不超过64MB，浏览器字段缓存最多3份；不是把全部模型场塞进研究JSON。

## 独立本地文件监听

工作台每秒检查实际工况的网格、正时间目录保存场、执行回执、0/constant/system 输入卡，以及研究、历史和 columns/rows 数据表。文件稳定后合并事件，自动刷新输入卡目录、发布明确 caseRoot 归属的模型，再唤醒展示子 agent；不等待主 agent 工具调用或回合结束。未变化文件不重复唤醒，半写 JSON 不进入展示。

自动登记使用独立的 delivery/workspace-observation.json 和 delivery/observed/ 模型，不改写求解输入、原始研究表、响应与运行状态。初始只生成网格；配置 preview.fields 后才按明确字段导出保存场。没有 caseRoot 时，只接受 history 中 point.id 与 result_root 的明确对应，不按文件夹名称猜组。无法归属的文件会作为观察事实交给展示子 agent 处理。

展示子 agent 可通过 exports 中的 runId、caseRoot、fields、kind 为指定组补交模型，宿主核对归属并保存后续预览提示。显式交付的有效结果优先。失败组保留输入卡、执行回执和日志，不能混入另一组的场。
