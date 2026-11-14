# OpenFOAM 高级结果选择

普通字段响应使用 `scripts/result_api.py`。只有探针分段表、Decimal归约、派生量或特殊边界语义需要本参考中的高级入口。

## 来源、体积与张量

请求字段或网格来源时，使用 `describe_field(root, variable, time=...)` 和 `describe_mesh(root, time=...)`。前者返回 `variable`、`time`、`unit`、精确十进制字符串形式的 `dimensions` 与 `field_path`；后者返回 `time` 及原始网格项到路径的 `primitive_sources` 映射。路径相对所给结果根，可直接序列化JSON。

体积加权使用 `read_field(..., include_volumes=True)`，`frame.volumes` 是与标签、数值和坐标对齐的立方米权重，也适用于最近单元选择。默认值为 `None`；边界面不是单元，不能请求patch体积。

```python
frame = result_api.read_field(root, 'T', time=time, scope=('cellZone', zone),
                              include_volumes=True)
mean = sum(v * w for v, w in zip(frame.values, frame.volumes, strict=True)) / sum(frame.volumes)
```

薄接口的值和体积是浮点数；需要保留超出浮点精度的存储十进制区别时，使用下方Decimal接口。薄接口不提供边界坐标，单元中心与面位置也是不同支撑。

对称单元张量的 `component='principal_max'` 同时使用六个存储分量，返回最大代数特征值；全向受压时可以为负，拉伸截断属于请求公式。该选择支持内部域和cellZone，不支持边界patch。

自定义历史归约用 `iter_fields(..., time='all')` 逐帧读取该时刻网格，按 `frame.time` 筛选窗口。`read_field(time='all')` 会将全部帧保存在内存，长历史优先逐帧处理。

## 高级公共入口

选择器绑定原生对象、时间、范围和分量。内部范围是实际cellZone；边界/界面还要明确所有者区域与条目；探针要明确采样槽。

| 所需操作 | `scripts/openfoam_parser.py` 的公共入口 |
|---|---|
| 内部材料区字段 | `select_cell_field_at_time` 后接 `reduce_cell_selection` |
| 边界或界面字段 | `select_boundary_field_at_time` 后接 `reduce_boundary_selections` |
| 分段探针 | `parse_segmented_probe_tables` 后接 `select_probe_record` |
| 对齐的单元运算 | 运算前 `validate_aligned_cell_selections` |
| 柱坐标工程分量 | 选择前使用 `cylindrical_symm_tensor_normal_component` |
| 维度转SI单位 | `canonical_si_unit_for_dimensions` |

解析器拒绝说明当前选择不可用或不兼容；确属文件语法不支持时可补充读者，但仍须读取同一对象、时间和物理范围。

## 选择真实的物理支撑

- 单元选择绑定字段、精确cellZone标签和该时刻网格。不能从目录名、名义半径、探针位置或数组长度推断材料成员。
- 边界选择绑定字段对象、patch、条目、所有者区域、拓扑、分量和时间。同对象存在 `internalField` 不意味着所需界面量属于内部单元。
- 探针选择使用真实分段表元数据、槽位、分量和模型时间。重启前后不能按行位置拼接。

仅在本地算例说明或兼容的OFFBEAT输出约定确认时，使用以下条件说明，显式算例说明优先：部分接触/界面结果的内部值是占位或哨兵，物理量存储在所有者侧边界。这时 `gapWidth`、`interfaceP` 选相应边界，不归约内部占位值。

原生柱坐标应力 `sigmaCyl` 用 `cylindrical_symm_tensor_normal_component` 映射径向、环向、轴向。由笛卡尔应力自行推导时需要对应的基底变换。

## 选择、归约和复用

```python
selected = api.select_cell_field_at_time(
    result_root,
    field_selector=field,
    zone_name=zone,
    component=component,
    exact=requested_time,
)
reduced = api.reduce_cell_selection(selected, operation=operation)
unit = api.canonical_si_unit_for_dimensions(selected.dimensions)
```

边界使用对应选择器及 `patch_name`、`owner_zone_name`、`entry_name` 和精确时间，再用 `reduce_boundary_selections`。标量分量为 `value`，向量和张量使用公开分量名或映射。`max_abs` 比较值非负；只有请求时才额外保留带符号并列项和位置。

原生结果对象优先于代理重建量。派生响应必须有任务或已维护源语义定义的公式；所有操作数来自同一根、时间、范围和网格，先检查对齐。语法回退不能改变对象、范围、分量、公式或归约。

## 时间选择

明确请求的时间使用 `exact`，要求对应字段或探针记录存在。终态使用 Execute 返回的 `final_time` 实际目录名：执行器可在受限的舍入误差内确认完成，而结果选择器仍按实际时间键选择，不把请求的 `endTime` 文本重新当成现成目录名。

使用前先固定 `latest` 的含义。`latest=True` 是算例最后数值目录；某字段最后可用时刻或多个量最后共同对齐时刻应使用相应序列接口。不能观察到哪里有值后再切换定义。

跨重启历史按精确模型时间键对齐，行号不能证明时间相同。
