# 重复提取内部材料区极值

普通标量极值直接复用 Extract 的 `result_api.extreme`。需要Decimal精度、全部并列单元和来源细节时，使用 `scripts/cellzone_extremum.py`；它对一个内部cellZone调用公共 `select_cell_field_at_time` 和 `reduce_cell_selection`，支持 `min`、`max`、`max_abs`。

一次调用归约一个模型时间的一个字段。时间窗口峰值等历史操作使用结果序列API。辅助入口支持标量 `value` 和OFFBEAT `sigmaCyl` 的工程分量 `hoop`，接受 `latest` 或一个精确时间，不向更早字段回退；单位不足时返回 `unit_unverified`，不猜测。

`max_abs` 的JSON `comparison` 是非负幅值，适用于绝对应力目标或限值。`value` 和 `ties[*].value` 保留符号，用于明确请求的拉压细节；这些符号值不是绝对响应。普通标量API已经直接返回幅值。

精确终态复用 Execute 确认的完成状态与配置 `endTime` 作为 `--time`；不能以 `latest` 替代。只有请求明确选择全局最后可用结果时才使用 `latest`。

把详细提取放入Python回调，由控制器处理正常完成的结果根；已有响应复用：

```bash
python3 -B "$MANDIFUEL_PLUGIN_ROOT/skills/conduct-offbeat-study/scripts/cellzone_extremum.py" \
  --plugin-root "$MANDIFUEL_PLUGIN_ROOT" \
  --result-root point-001 \
  --field T \
  --zone fuel \
  --component value \
  --operation max \
  --time "$CONFIGURED_END_TIME"
```

`CONFIGURED_END_TIME` 来自该点的 `system/controlDict`，使用结果目录单位。包壳环向绝对应力使用 `--field sigmaCyl --zone cladding --component hoop --operation max_abs`。

成功返回简洁JSON，含状态、数值、比较幅值、单位、模型时间、全部并列单元及相对来源路径。选择或归约异常返回 `status: extraction_failed`、保留 `error_type` 并以非零退出；这是提取状态，与求解终态分开。
