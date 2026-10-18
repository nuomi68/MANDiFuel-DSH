# Sector angles and angular metadata

Use `cylindrical-angle-map` for the named UNV 2411 nodes or explicit block mesh.
For generator-owned geometry, edit its angle input and regenerate the dictionary;
use the map for any separately required retained coordinates. A supplied UNV is
an imported-mesh input, not a `rodDict` or `blockMeshDict` parameter source.

```python
from geometry_ops import apply
readback = apply(case, {
    "operation": {"type": "cylindrical-angle-map",
                  "source_span_degrees": 90, "target_span_degrees": 60},
    "artifacts": [{"path": "mesh/main.unv", "format": "unv-2411"}],
})
```

A block dictionary uses `format: "openfoam-block-mesh"`.

Defaults are `axis: "z"`, `origin: [0,0,0]`, `source_start_degrees: 0`,
`target_start_degrees: 0` and `require_boundary_coverage: true`. The origin uses
**stored coordinates**, with the same meaning in all declared artifacts. Mapping
preserves radius and axial position. Set coverage false only when another explicit
representation establishes the sector. `describe(case, artifact)` returns UNV
counts and bounds in stored units if needed; UNV applies to all declared nodes.

Optional top-level `couplings` update actual angular metadata in the same operation:

```python
couplings = [
    {"path": "constant/geometryMetadata", "kind": "sector-fraction", "key": "sectorFraction"},
    {"path": "constant/geometryMetadata", "kind": "sector-normalized-list", "key": "sectorLocations",
     "preserve_terminal": 1.0, "paired_list_key": "sectorData"},
]
```

Keys must be unique in the declared file. Omit terminal preservation or paired-list
checking when those relationships are absent. Repeated artifact formats and legacy
schema-version-1 angle plans are supported by this entry point.

The successful return certifies coordinate and declared metadata readback, retained
IDs and the existing element connections.
