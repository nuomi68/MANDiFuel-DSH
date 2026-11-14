# 扇区角度与角度元数据

对指定UNV 2411节点或显式块网格使用 `cylindrical-angle-map`。生成器管理的几何先修改角度参数并重新生成；只有另行要求的保留坐标使用映射。输入UNV属于导入网格，不是 `rodDict` 或 `blockMeshDict` 参数来源。

```python
from geometry_ops import apply
readback = apply(case, {
    'operation': {'type': 'cylindrical-angle-map',
                  'source_span_degrees': 90, 'target_span_degrees': 60},
    'artifacts': [{'path': 'mesh/main.unv', 'format': 'unv-2411'}],
})
```

块字典使用 `format: 'openfoam-block-mesh'`。默认 `axis: 'z'`、`origin: [0,0,0]`、`source_start_degrees: 0`、`target_start_degrees: 0`、`require_boundary_coverage: true`。原点使用存储坐标单位，所有声明数据项必须有相同含义。变换保留半径和轴向位置；只有其他明确表示已经建立扇区时才关闭覆盖要求。

`describe(case, artifact)` 可返回UNV节点数量和存储单位边界，UNV操作覆盖全部声明节点。可选顶层 `couplings` 在同一操作中更新实际角度元数据：

```python
couplings = [
    {'path': 'constant/geometryMetadata', 'kind': 'sector-fraction', 'key': 'sectorFraction'},
    {'path': 'constant/geometryMetadata', 'kind': 'sector-normalized-list',
     'key': 'sectorLocations', 'preserve_terminal': 1.0, 'paired_list_key': 'sectorData'},
]
```

键在声明文件中须唯一。不存在末值保持或配对列表关系时省略对应检查。本入口支持重复的数据格式和旧版schema-version-1角度计划。成功返回证明坐标及声明的元数据回读、保留ID与既有单元连接；不凭此扩展到未声明的物理绑定。
