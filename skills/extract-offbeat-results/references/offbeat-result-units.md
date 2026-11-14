# OFFBEAT 运行输出单位

优先用目标字段的七指数 `dimensions`。维度不足时采用下表已经核实的受支持约定；不阅读求解器或插件源码考证。字段名区分大小写，不能推广到相似名称。

| 确切字段或明确作用域的量 | 单位 |
|---|---|
| `Bu` | `MWd/MT_oxide` |
| `gapWidth` | `m` |
| `interfaceP` | `Pa` |
| `sigma`、`sigmaEq`、`sigmaHyd`、`sigmaY` | `Pa` |
| 明确属于间隙气体状态的 `gasPressure` | `Pa` |

间隙气体一行不适用于其他压力对象。`Bu_kgU` 在该快照未核实，标为 `unit_unverified`；不猜测单位，不在运行任务中追查实现。其他未覆盖字段也保留未核实状态。维护出处单独保存在开发记录，运行无需加载。
