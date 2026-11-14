# 箱体尺寸与单元宽度

显式块网格和保留的 ASCII OpenFOAM 点坐标使用 `box-resize`。先从输入确定尺寸、单位和固定角点。几何由生成器管理时修改参数并重新生成字典；仅对另行要求的保留坐标使用映射。

```python
from geometry_ops import apply
readback = apply(case, {
    'operation': {'type': 'box-resize', 'size_m': [0.003, 0.002, 0.001]},
    'artifacts': [{'path': 'system/blockMeshDict', 'format': 'openfoam-block-mesh'}],
})
```

长度单位为米。块顶点通过字面的 `convertToMeters` 或标量 `scale` 换算，保留的点已经以米表示。默认固定最小角点，指定 `origin_m` 时使用该原点；映射全部顶点。需要同步保留点时增加 `format: 'openfoam-points'` 的数据项。

可选 `cell_size_m` 是一个最大名义宽度或三个全局方向宽度。自动向上取整网格数要求单个轴对齐八顶点六面体。三个单元数对应块的局部方向，顺序不一定是全局x/y/z。其他布局保留原数量或按已有绑定修改；单改数量不会移动界面。

圆弧的非等比缩放需要其他边表示；等比缩放支持现有曲线控制。`describe(case, artifact)` 返回边界与成员信息，`apply` 返回米制边界及请求的数量。中心探针使用这些边界的中点，采样绑定另行完成。
