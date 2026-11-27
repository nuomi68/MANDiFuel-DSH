"""Normalized signatures of the reviewed OFFBEAT constant-property rod input family."""
FINGERPRINTS = {
    '0/T': 'b4aa088fb1033e40c96ff625022d0dd575a50d02d749630fe21556100e3c83e6',
    'constant/solverDict': '628aeaae22786fa5713e8b4f71a2f02e929b980dcb1500748c3881594c14027b',
    'system/controlDict': 'acdc99d3cc852578897b5319c0d2fca8eca6855a44980a14daade55a587a4f6f',
    'system/fvSchemes': '6b67254dc0aa68e8a935c16c9af5caaf726105116857d51ad142c355eb514c59',
    'system/fvSolution': '8d9c29cb9d9b7177b4c69ea6a6d9836f5388428802698204afbf74e41bb75f1b',
    'constant/polyMesh/boundary': '1b64bd263a9bf6fca25dced63aa53295153b9fc9f354c613ee576f1f8da9d07b',
}

# Solid fuel to the axis, a constant three-node power history, fixed time step
# and the reviewed native probes/sets function objects.
SOLID_ROD = {
    **FINGERPRINTS,
    '0/T': '9b18a3b6eca405cd0c57cde797f905c29b152ab1f1af0471aeaf3e17d74bed63',
    'constant/solverDict': 'a7db110df7e446d593260968a4c3ac1c2544922fe242f3d7199f0cfa4117f6ca',
    'system/controlDict': '9325f479b420ee003b7003a911f65636fb2f2d9eb65efe94a12daf318e860bef',
    'constant/polyMesh/boundary': '6e6df625d5080d379d607a4af7578ac90a8b6438d96324c6569891596d7fd33d',
}

# Same constant properties and two gap faces. The steadyState discretisation
# writes the native heat balances and patch integrals at each saved iteration.
STEADY_HEAT_BALANCE = {
    **SOLID_ROD,
    'constant/solverDict': 'c40c66acb93610c9ca6d14a69d2203d479b8fe6ad28e9111bf6bc824ac140fab',
    'system/controlDict': '7dfd48ad30daaf8a83a54d506b405377265658ab2f0888d55c0c925ec57ec50d',
    'system/fvSchemes': 'd37b4e955f1732bd2be141fa4388f8aeb6ebec9141b84e3a5d1221f93679678d',
}
