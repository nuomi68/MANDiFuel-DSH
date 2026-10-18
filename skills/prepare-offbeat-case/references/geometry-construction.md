# New rod geometry

When the requested rod structure no longer fits the existing arrangement, build
replacement geometry in the target using a suitable rod template or generator.

| Target geometry | Geometry input and construction |
| --- | --- |
| 1D radial rod | `rodDict`, `geometryType: '1D'`, consumed by `rodMaker.py`. |
| 2D r-z continuous fuel column | `rodDict`, `geometryType: '2Dsmeared'`. Block names, radii, heights, offsets and cell counts describe the axial sections. |
| 2D r-z discrete pellets | `rodDict`, `geometryType: '2Ddiscrete'`. `nPelletsFuel` splits each fuel block; the source generator also supports its defined dish and chamfer inputs. |
| 2D r-theta cross-section | The cross-section template's explicit `blockMeshDict` or supplied imported mesh. `rodMaker.py` is an r-z generator, not an r-theta generator. |
| Full-circumference 3D fuel/cladding rod | `rod3Ddict.json` consumed by `rod3Dmaker.py`. The native version constructs one axial segment with fixed fuel/cladding regions; its array inputs use the first entry. It does not provide a general rod assembly or a cladding-only switch. |
| Cladding-only specimen | A cladding-only template's annular `blockMeshDict`, such as the pseudo-PUZRY case. Its region and boundary definitions already represent the specimen. |

Run a supplied generator in the isolated target with its parameter file. Native
`rodMaker.py` and `rod3Dmaker.py` write `blockMeshDict` in the working directory;
place the result at `system/blockMeshDict` when that dictionary is required.

`blockMesh` generates the mesh from the dictionary during Execute. A generated
dictionary provides geometry, cell zones and mesh patch names; the target's
material assignments and field boundary entries must use the resulting names.
Shared interfaces use shared connections; contact surfaces may need distinct
paired patches. Coordinate scaling alone cannot create a missing interface.
