# 保留径向坐标的映射

用于没有生成器的显式几何，或用户另行要求同步的保留坐标。先解析坐标输入与运动组件；生成器管理的尺寸应改参数。

新算例采用标准 `smallStrainIncrementalUpdated` 时，`referenceMesh` 由初始 `constant/polyMesh/points` 和活动拓扑构建，再作为输出写出。重新生成初始网格即可提供新参考几何；保留的 `constant/referenceMesh` 不是另一个需要修改的初始绑定。重启保留原参考几何和对应状态。

原生r-z `rodMaker` 会对顶点半径做楔体体积修正：`coordinate_radius = nominal_radius * sqrt(sin(alpha/2)/(alpha/2))`，`alpha` 用弧度。生成器会处理该约定；坐标映射必须使用实际坐标半径，不能直接代入名义半径。

```python
from geometry_ops import apply
readback = apply(case, {
    'operation': {'type': 'radial-map', 'space': 'spherical',
                  'radii_m': [[0.0004, 0.00042], [0.0006, 0.00062]]},
    'artifacts': [{'path': 'system/blockMeshDict', 'format': 'openfoam-block-mesh',
                   'selection': {'blocks': ['shell']}}],
})
```

半径对为递增的 `[源半径, 目标半径]`，对之间线性映射。相同偏移保持厚度，不同偏移改变厚度。长度用米，块坐标使用字面 `convertToMeters` 或标量 `scale` 换算；保留点已是米。

两种空间都可用 `origin_m`，默认 `[0,0,0]`。`space: 'cylindrical'` 保留沿 `axis` 的坐标，轴可为x、y、z，默认z；球面映射使用到中心的距离。端点容差默认 `max(1e-12 m, 最大源半径 * 1e-5)`，可用 `radius_tolerance_m` 覆盖；它只处理ASCII舍入，不负责选点。

各数据项可用 `selection` 选择 `{'blocks':['区域名']}`、`{'patch':'边界名'}`、`{'connected_to_patch':'边界名'}`、`{'component':40}` 或 `{'points':[4,5,6,7]}`；省略则映射全部点。保留点数据项使用 `format: 'openfoam-points'`。连通组件需要同目录ASCII `faces`，patch选择还需要 `boundary`。

成员未知时使用 `describe(case, artifact)` 获得组件ID与范围；ID是代表点ID，径向范围围绕 `(0,0,0)`。同目录有 `faces` 而 `boundary` 为空时仍可报告组件；按运动组件真实径向范围匹配组件，使用 `component` 即可，不必枚举点ID。

重合间隙表面可有不同ID，要按成员关系选择请求的一侧，不能只按半径。连通组件不一定是材料区，不同表示的ID不同，应分别解析；共享ID仍然共享，本映射不能拆开没有独立点ID的表面。径向圆弧须与映射原点同心。

若另有限制径向单元宽度，均匀单元数量为 `ceil(厚度/宽度上限)`，按对应块的局部方向另外更新。生成器参数和锚定特征的探针仍需完成各自绑定。
