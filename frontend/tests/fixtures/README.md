# Workbench parser fixtures

`radial-52` is a small two-region wedge mesh with 40 fuel cells and 12 cladding
cells, a radial gap, and a length of 0.12 m. Mesh and input dictionaries were
retained from the project's G01 mesh40-12 test inputs. OpenFOAM file notices
are preserved; repository licensing applies. No execution receipts, logs,
session history or solver output fields are included.

The saved-time file `radial-52/1/T` is **synthetic test data**:
`T[i] = 1156.7 - (1156.7 - 650) * i / 51`, for `i = 0..51`, in kelvin.
Its deliberately simple values exercise file arrivals, field selection,
unit handling, export, and mesh caching. They make no claim about a physical
solution or solver accuracy. Tests create further vector and tensor fields in
temporary directories. This fixture requires neither an OFFBEAT installation
nor any files under `runs/` or `work/`.
