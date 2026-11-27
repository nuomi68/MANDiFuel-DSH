# 插槽和操作协议

`ui_inspect` 的 `target` 可为 page、main、aside、settings、model、data、capabilities、evidence；读取 main/aside 时可另给 node，定位唯一组件 ID。每次返回当前不透明 revision。page 的 browser 是实际页面上报状态，包含连接情况、视口、插槽尺寸、节点可见性、当前页签、表格搜索/排序/分页和图表缩放。

`ui_apply` 参数为 `{expectedRevision, datasets?, operations?, update?}`。顶层 datasets 按 ID 合并进现有数据源，可和引用该数据源的节点操作一起提交。完整替换页面时统一使用 update.ui.datasets。至少有一项修改。operations 最多 24 个，最终组件树和数据绑定仍由宿主校验；错误事务不提交。

## 主区与右侧组件

slot 使用 main 或 aside：

- `{op:"replace",slot,value:组件树}` 替换整个插槽，aside 的 value 可为 null。
- `{op:"replace",slot,id,value:组件}` 替换指定节点。
- `{op:"insert",slot,parent:父ID,index?:位置,value:组件}` 插入到 row/column/grid/tabs，省略 index 追加。
- `{op:"update",slot,id,props:{...}}` 更新节点属性，不能改 ID/type。
- `{op:"remove",slot,id}` 删除子节点；根节点用 replace。
- `{op:"move",slot,id,toSlot?:main或aside,parent:目标父ID,index?:位置}` 移动现有节点，可跨主区/右侧；不能形成循环。
- `{op:"interact",slot,id,state:{...}}` 操作已有组件：tabs 使用 activeTab；table 使用 query、sort:{column,direction}、page（从 0 起）；chart 使用 viewport:{x:[下限,上限],y:[下限,上限]} 或 null 复位，以及 hiddenSeries:[序列序号]；focus:true 将该节点带入视野。只操作目标组件，不接收 DOM 选择器或代码。

节点 ID 唯一，所有节点均来自 capabilities 中的组件目录。移动、标题和布局修改保留未改变节点的交互状态。没有自定义组件树时，创建旁路面板会保留基础模型。

## 显示设置

slot 为 settings：replace 的 value 是整套控件数组；upsert 的 value 为带 id 的控件定义，已有 ID 局部合并，新增 ID 追加；remove 按 id 删除。参数必须通过显示程序或组件表达式实际使用。新增能力只增加当前需要的操作，不移除仍在使用的其他控件。

修改已有参数的当前数值直接用 `update:{parameterValues:{实际ID:数值}}`，保留定义与其他参数。不要改 default 来代替当前值。settings upsert 的外层仅有 op/slot/value，ID 放在 value 内；replace 的外层仅有 op/slot/value，value 是数组。

## 模型、数据和完整更新

`update` 使用既有展示协议的 controls、parameterValues、rendering、viewState、ui、exports、defaultView、parameters、studyMapping 等属性；完整 ui 可声明 version/mode/scope/root/aside/datasets。不要同时用 operations 和 update.ui 修改组件树，或同时用 settings 操作与 update.controls 修改控件。

`update.rendering` 和 `update.viewState` 操作模型；`exports` 只导出已有保存场。model 是保留的渲染设施，不接收 HTML/JS。需要整块图表或模型更新时可用完整 update；局部页面变更优先使用 operations。

导出模型与引用它的组件分成两笔提交，先核对实际模型和字段。`update.interactions` 也可直接填写 [{id,state}]，效果与 interact 一致。

成功返回新的 revision、presentationVersion、uiRevision、viewStateRevision 和 renderStatus。`ui_wait_for_render` 等待最后一次修改的浏览器回执，可给 timeoutMs（最多 10000）；返回 confirmed、pending、offline、error、stale 或 selection-unconfirmed。保存配置不等于页面已确认。版本冲突必须重新观察，不能自动用新版本强行重试旧操作。
