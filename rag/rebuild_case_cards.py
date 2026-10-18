#!/usr/bin/env python3
"""Rebuild the compact OFFBEAT case-card corpus from auditable evidence.

This is a development-time curation tool.  It intentionally reads an official
OFFBEAT case tree and the reviewed semantic material preserved in a historical
MANDiFuel git revision.  Runtime retrieval reads only the generated compact
JSON and does not depend on either external tree.

The historical compact corpus and retrieval evals are deliberately not inputs:
they contain the family mix-ups this tool is intended to prevent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = ROOT / "data" / "offbeat_case_cards_compact_138.json"
LEGACY_DATA = "database/offbeat_card_rag/data"
LEGACY_REVISION = "8140fb3"
LABEL_FACETS = [
    "case_intent",
    "system_or_component",
    "reactor_or_fuel_context",
    "geometry",
    "physics_modules",
    "solver_or_model_features",
    "driving_condition",
    "output_targets",
    "sibling_discriminator",
]

INACTIVE_SWITCHES = {"", "none", "fromLatestTime", "byZone", "byMaterial"}
SPECIAL_MODEL_TERMS = (
    "FpDiffusion",
    "constantCreepPrincipalStress",
    "correlationCreepPrincipalStress",
    "MonolithicSiCCreepModel",
    "PARFUMUEBufferCreepModel",
    "PyCPARFUME",
    "BufferPARFUME",
    "SiCPARFUME",
    "SiCSnead",
    "UO2MATPRO",
    "UO2FRAPCON",
    "growthBISONZy",
    "LimbackCreepModel",
    "smearedCracking",
    "isotropicCracking",
)


class RebuildError(RuntimeError):
    """Raised when source evidence cannot support a deterministic rebuild."""


@dataclass(frozen=True)
class Profile:
    case_id: str
    family: str
    child: str | None
    official_path: str
    purpose: str
    supported_intents: list[str]
    not_for: list[str]
    distinguishing_features: list[str]
    review_status: str
    geometry_dimension: str | None
    geometry_coordinate: str | None
    geometry_generator: str | None
    geometry_regions: list[str]
    initial_fields: list[str]
    model_switches: dict[str, str]
    materials: list[str]
    historical_case_hash: str
    historical_hashes: dict[str, str]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _git_read(repository: Path, revision: str, relative_path: str) -> str:
    command = ["git", "-C", str(repository), "show", f"{revision}:{relative_path}"]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr else "git show failed"
        raise RebuildError(f"cannot read {revision}:{relative_path}: {detail}")
    return completed.stdout


def _yaml_unquote(value: str) -> str | None:
    value = value.strip()
    if value in {"", "null", "~"}:
        return None
    if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
        value = value[1:-1]
    return value


def _yaml_section(lines: list[str], key: str) -> list[str]:
    """Extract and de-indent one block from generated, simple YAML profiles."""

    match_index = None
    match_indent = 0
    pattern = re.compile(rf"^(\s*){re.escape(key)}:\s*(?:&\S+)?\s*$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            match_index = index
            match_indent = len(match.group(1))
            break
    if match_index is None:
        return []
    result: list[str] = []
    for line in lines[match_index + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= match_indent:
            break
        remove = min(len(line), match_indent + 2)
        result.append(line[remove:])
    return result


def _yaml_map(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^([^:#][^:]*):\s*(.*?)\s*$", line)
        if match and not line.startswith((" ", "-")):
            value = _yaml_unquote(match.group(2))
            if value is not None:
                result[match.group(1).strip()] = value
    return result


def _yaml_list(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        match = re.match(r"^-\s+(.*?)\s*$", line)
        if match:
            value = _yaml_unquote(match.group(1))
            if value is not None:
                result.append(value)
    return result


def _root_scalar(lines: list[str], key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}:\s*(.*?)\s*$", "\n".join(lines), re.MULTILINE)
    return _yaml_unquote(match.group(1)) if match else None


def _safe_case_dir(case_id: str) -> str:
    return case_id.replace("/", "__")


def _case_id_from_path(card_path: str) -> str:
    for prefix in ("Cases/Verification/", "Cases/testCases/", "Cases/restart/"):
        if card_path.startswith(prefix):
            return card_path[len(prefix) :]
    raise RebuildError(f"unrecognized official case path: {card_path}")


def _load_profile(
    legacy_repository: Path,
    revision: str,
    case_id: str,
) -> Profile:
    safe = _safe_case_dir(case_id)
    prefix = f"{LEGACY_DATA}/cases/{safe}"
    semantic_lines = _git_read(
        legacy_repository, revision, f"{prefix}/semantic_profile.yaml"
    ).splitlines()
    filesystem_lines = _git_read(
        legacy_repository, revision, f"{prefix}/filesystem_profile.yaml"
    ).splitlines()

    actual_case_id = _root_scalar(filesystem_lines, "case_id")
    if actual_case_id != case_id:
        raise RebuildError(f"profile identity mismatch: {case_id!r} != {actual_case_id!r}")

    purpose = _yaml_map(_yaml_section(semantic_lines, "purpose")).get("primary")
    family = _root_scalar(semantic_lines, "family")
    if not purpose or not family:
        raise RebuildError(f"semantic profile is incomplete: {case_id}")
    geometry = _yaml_section(filesystem_lines, "geometry")
    fields = _yaml_section(filesystem_lines, "fields")
    solver_dict = _yaml_section(filesystem_lines, "solver_dict")
    fingerprint = _yaml_section(filesystem_lines, "fingerprint")
    geometry_values = _yaml_map(geometry)
    review_values = _yaml_map(_yaml_section(semantic_lines, "manual_review"))
    child_value = _root_scalar(semantic_lines, "child")

    return Profile(
        case_id=case_id,
        family=family,
        child=child_value,
        official_path=_root_scalar(filesystem_lines, "official_path") or "",
        purpose=purpose,
        supported_intents=_yaml_list(_yaml_section(semantic_lines, "supported_intents")),
        not_for=_yaml_list(_yaml_section(semantic_lines, "not_for")),
        distinguishing_features=_yaml_list(
            _yaml_section(semantic_lines, "distinguishing_features")
        ),
        review_status=review_values.get("status", "unknown"),
        geometry_dimension=geometry_values.get("dimension"),
        geometry_coordinate=geometry_values.get("coordinate_system"),
        geometry_generator=geometry_values.get("generator"),
        geometry_regions=_yaml_list(_yaml_section(geometry, "regions")),
        initial_fields=_yaml_list(_yaml_section(fields, "initial_fields")),
        model_switches=_yaml_map(_yaml_section(solver_dict, "model_switches")),
        materials=_yaml_list(_yaml_section(solver_dict, "materials")),
        historical_case_hash=_yaml_map(fingerprint).get("case_hash", ""),
        historical_hashes=_yaml_map(_yaml_section(fingerprint, "key_file_hashes")),
    )


# These cases had no reviewed case-level overlay at 8140fb3.  The replacements
# below are deliberately narrow and tied to case-local names, README text, or
# active dictionary settings; they do not claim general solver capability.
DRAFT_OVERRIDES: dict[str, dict[str, Any]] = {
    "beamBending": {
        "primary": "tapered_beam_bending_and_shear_verification",
        "intents": ["beam_bending", "shear_stress", "structural_verification"],
        "features": [
            "README identifies case IV of the Su and Zhou tapered-beam analysis",
            "the end patch applies a transverse traction in the small-strain mechanics setup",
        ],
        "not_for": ["fuel rod thermomechanics", "thermal conduction validation"],
    },
    "gapVolume": {
        "primary": "two_dimensional_gap_volume_verification",
        "intents": ["gap_volume", "FRAPCON_gap_gas", "axisymmetric_fuel_rod"],
        "features": [
            "the axisymmetric wedge mesh has 100 fuel and 120 cladding axial cells",
            "fuelOuter starts at 293 K and the FRAPCON gap-volume model is active",
        ],
        "not_for": ["heated fuel boundary variant", "one-dimensional reduced mesh"],
    },
    "gapVolume1D": {
        "primary": "reduced_mesh_gap_volume_verification",
        "intents": ["gap_volume", "FRAPCON_gap_gas", "reduced_axisymmetric_mesh"],
        "features": [
            "the reduced wedge mesh has 10 fuel and 12 cladding axial cells",
            "fuelOuter starts at 293 K and the FRAPCON gap-volume model is active",
        ],
        "not_for": ["heated fuel boundary variant", "fine axial mesh"],
    },
    "gapVolumeHeatedFuel": {
        "primary": "two_dimensional_heated_fuel_gap_volume_verification",
        "intents": ["gap_volume", "FRAPCON_gap_gas", "heated_fuel_boundary"],
        "features": [
            "fuelOuter temperature ramps from 293 K to 500 K",
            "the axisymmetric wedge mesh has 100 fuel and 120 cladding axial cells",
        ],
        "not_for": ["unheated gap-volume baseline", "one-dimensional reduced mesh"],
    },
    "gapVolumeHeatedFuel1D": {
        "primary": "reduced_mesh_heated_fuel_gap_volume_verification",
        "intents": ["gap_volume", "FRAPCON_gap_gas", "heated_fuel_boundary"],
        "features": [
            "fuelOuter temperature ramps from 293 K to 500 K",
            "the reduced wedge mesh has 10 fuel and 12 cladding axial cells",
        ],
        "not_for": ["unheated gap-volume baseline", "fine axial mesh"],
    },
    "heatConservation": {
        "primary": "fuel_rod_heat_conservation_verification",
        "intents": ["heat_conservation", "linear_heat_rate", "gap_heat_transfer"],
        "features": [
            "timeDependentLhgr supplies heat to the fuel region",
            "the fuel-cladding wedge retains an active FRAPCON gap model",
        ],
        "not_for": ["gap-volume-only verification", "structural force balance"],
    },
    "hydrogenTransport/heatingCooling2": {
        "primary": "heating_and_cooling_hydrogen_transport_cycle",
        "intents": ["hydrogen_transport", "thermal_cycle", "hydrogen_redistribution"],
        "features": [
            "the byList element-transport setup evolves Cpp and Css fields",
            "the case contains both heating and cooling temperature histories",
        ],
        "not_for": ["external hydrogen ingress boundary", "corrosion uptake source"],
    },
    "laserHeating": {
        "primary": "laser_heat_source_verification",
        "intents": ["laser_heating", "volumetric_heat_source", "thermal_verification"],
        "features": [
            "solverDict activates laserHeatSource in the fuel region",
            "mechanics and conduction solvers are not advanced by this source-only case",
        ],
        "not_for": ["linear heat rate fuel rod", "mechanical laser shock"],
    },
    "plateHole": {
        "primary": "pressurized_plate_with_hole_large_strain_verification",
        "intents": ["plate_with_hole", "stress_concentration", "large_strain_mechanics"],
        "features": [
            "the hole boundary carries a 1 MPa pressure load",
            "Allrun compares small-strain and total- and updated-Lagrangian mechanics solvers",
        ],
        "not_for": ["fuel pellet geometry", "thermal expansion benchmark"],
    },
    "testUserParameters": {
        "primary": "user_parameters_dictionary_regression",
        "intents": ["user_parameters", "dictionary_substitution", "regression_test"],
        "features": [
            "Allrun edits system/userParameters before executing the fuel-rod fixture",
            "the surrounding PWR model is test scaffolding rather than the test subject",
        ],
        "not_for": ["coolant channel validation", "fuel-performance reference template"],
    },
    "thickCylinderExpansion": {
        "primary": "internally_pressurized_thick_cylinder_expansion",
        "intents": ["thick_cylinder", "pressure_expansion", "large_strain_mechanics"],
        "features": [
            "the cladding-only cylindrical mesh applies 0.1 MPa at its inner surface",
            "largeStrainUpdLag and pressure smoothing are configured",
        ],
        "not_for": ["fuel-cladding gap", "plate-with-hole stress concentration"],
    },
    "volumeConservationLargeStrain": {
        "primary": "large_strain_volume_conservation_verification",
        "intents": ["volume_conservation", "large_strain_mechanics", "solver_comparison"],
        "features": [
            "Allrun compares smallStrain with largeStrainUpdLag",
            "the cladding-only cylindrical deformation is postprocessed for volume change",
        ],
        "not_for": ["thermal conservation", "fuel swelling correlation"],
    },
    "baseCase": {
        "primary": "restart_workflow_base_case",
        "intents": ["restart", "time_restart", "fuel_rod_fixture"],
        "features": [
            "the path is the base calculation for the Cases/restart workflow",
            "the rodDict geometry contains fuel and cladding regions with restart fields",
        ],
        "not_for": ["standalone reference benchmark", "completed restart continuation"],
    },
    "trisoModulesTest/testBuffer_k": {
        "primary": "buffer_thermal_conductivity_module_test",
        "intents": ["TRISO_buffer", "thermal_conductivity", "module_test"],
        "features": [
            "the buffer material property fixture writes and probes k",
            "fast-flux input accompanies the single-property conductivity check",
        ],
        "not_for": ["buffer swelling", "TRISO particle stress benchmark"],
    },
    "trisoModulesTest/testBuffer_swelling": {
        "primary": "buffer_swelling_module_test",
        "intents": ["TRISO_buffer", "irradiation_swelling", "module_test"],
        "features": [
            "the buffer material activates BufferPARFUME swelling",
            "the fast-flux history drives the isolated material-property fixture",
        ],
        "not_for": ["buffer conductivity", "multilayer TRISO benchmark"],
    },
    "trisoModulesTest/testPyC_E_nu": {
        "primary": "pyrocarbon_elastic_constants_module_test",
        "intents": ["pyrocarbon", "Young_modulus", "Poisson_ratio", "module_test"],
        "features": [
            "the PyC material activates PyCPARFUME Young-modulus behavior",
            "the fixture isolates elastic-property output under fast flux",
        ],
        "not_for": ["pyrocarbon creep", "pyrocarbon thermal expansion"],
    },
    "trisoModulesTest/testPyC_alpha": {
        "primary": "pyrocarbon_cartesian_thermal_expansion_module_test",
        "intents": ["pyrocarbon", "thermal_expansion", "orthotropy", "module_test"],
        "features": [
            "the README defines a one-element Cartesian heating test from 673.15 K to 1673.15 K",
            "PyCPARFUME thermal expansion is checked through strain and displacement",
        ],
        "not_for": ["spherical thermal expansion", "irradiation swelling"],
    },
    "trisoModulesTest/testPyC_alpha_spherical": {
        "primary": "pyrocarbon_spherical_thermal_expansion_module_test",
        "intents": ["pyrocarbon", "spherical_thermal_expansion", "orthotropy", "module_test"],
        "features": [
            "the README defines a one-dimensional spherical analytical displacement comparison",
            "a deliberately anisotropic BAF separates radial and tangential expansion",
        ],
        "not_for": ["Cartesian thermal expansion", "irradiation swelling"],
    },
    "trisoModulesTest/testPyC_creep": {
        "primary": "pyrocarbon_irradiation_creep_module_test",
        "intents": ["pyrocarbon", "irradiation_creep", "module_test"],
        "features": [
            "the PyC material uses a creep constitutive model under fast flux",
            "epsilonCreep output isolates the creep response",
        ],
        "not_for": ["SiC creep", "pyrocarbon swelling"],
    },
    "trisoModulesTest/testPyC_swelling": {
        "primary": "pyrocarbon_irradiation_swelling_module_test",
        "intents": ["pyrocarbon", "irradiation_swelling", "BISON_comparison", "module_test"],
        "features": [
            "the README compares radial and tangential PyC swelling strain with BISON",
            "PyCPARFUME swelling is driven to 5e25 n/m2 fluence",
        ],
        "not_for": ["pyrocarbon creep", "buffer swelling"],
    },
    "trisoModulesTest/testSiC_creep": {
        "primary": "silicon_carbide_irradiation_creep_module_test",
        "intents": ["silicon_carbide", "irradiation_creep", "module_test"],
        "features": [
            "MonolithicSiCCreepModel is checked against the README analytical creep strain",
            "the fixture uses 600 K, 50 MPa and a prescribed fast-neutron flux",
        ],
        "not_for": ["PyC creep", "SiC elastic-property suite"],
    },
    "trisoModulesTest/testSiC_k_Cp_E_alpha": {
        "primary": "silicon_carbide_thermophysical_properties_module_test",
        "intents": [
            "silicon_carbide",
            "thermal_conductivity",
            "heat_capacity",
            "Young_modulus",
            "thermal_expansion",
            "module_test",
        ],
        "features": [
            "the one-dimensional temperature-gradient fixture checks k, Cp, E and alpha",
            "SiCPARFUME and SiCSnead property models are active",
        ],
        "not_for": ["SiC creep", "full TRISO particle mechanics"],
    },
    "trisoModulesTest/testSwellingMATPRO": {
        "primary": "uo2_matpro_swelling_module_test",
        "intents": ["UO2", "MATPRO_swelling", "volumetric_heating", "module_test"],
        "features": [
            "the UO2 material activates UO2MATPRO swelling and timeDependentVhgr",
            "epsilonSwelling is probed in an isolated fuel material fixture",
        ],
        "not_for": ["TRISO coating swelling", "fission-product diffusion"],
    },
    "generic_TRISO_1D": {
        "primary": "generic_full_triso_one_dimensional_template",
        "intents": ["TRISO_particle", "spherical_thermomechanics", "gap_gas", "SCIANTIX_FGR"],
        "features": [
            "the spherical mesh contains Kernel, Buffer, IPyC, SiC and OPyC regions",
            "TRISO gap gas, SCIANTIX FGR and incremental updated mechanics are active",
        ],
        "not_for": ["fission-product coating diffusion", "single-property module test"],
    },
    "graphite_stringer": {
        "primary": "graphite_stringer_thermal_fixture",
        "intents": ["graphite_stringer", "solid_conduction", "thermal_fixture"],
        "features": [
            "the single stringer region advances Q and T fields",
            "constant graphite-like properties support an isolated conduction case",
        ],
        "not_for": ["fuel rod template", "graphite irradiation mechanics"],
    },
    "smearedCrackingExample": {
        "primary": "fuel_smeared_cracking_example",
        "intents": ["smeared_cracking", "fuel_damage", "fuel_rod_thermomechanics"],
        "features": [
            "solverDict activates the smearedCracking damage model",
            "the fuel-cladding fixture couples linear heat rate, mechanics and FRAPCON gap gas",
        ],
        "not_for": ["Mazars damage", "isotropicCracking damage"],
    },
    "test_createTuFields": {
        "primary": "temperature_uncertainty_field_generation_test",
        "intents": ["Tu_fields", "field_generation", "utility_regression"],
        "features": [
            "system/TuOFFBEATdict is the subject of this utility test",
            "rod3Dmaker assets provide the mesh fixture without an OFFBEAT solverDict",
        ],
        "not_for": ["fuel-performance solve", "temperature solution extraction"],
    },
}


# Reviewed overlays remain useful evidence, but a small number contain terse or
# incorrect historical summaries.  These replacements are backed by current
# case-local dictionaries and verification scripts and deliberately take
# precedence over the historical prose.
VERIFIED_SEMANTIC_OVERRIDES: dict[str, dict[str, Any]] = {
    "hydrogenTransport/heatingCooling1": {
        "primary": "300_to_650_K_hydrogen_heating_cooling_rate_cycle",
        "intents": [
            "hydrogen_transport",
            "heating_cooling_cycle",
            "hydrogen_redistribution",
            "heating_rate_sensitivity",
        ],
        "features": [
            "the boundary temperature repeatedly cycles between 300 and 650 K",
            "the four heating and cooling rates are 100, 10, 1 and 0.1 K/min",
        ],
        "not_for": ["300 to 800 K hydrogen cycle", "external hydrogen ingress boundary"],
    },
    "hydrogenTransport/heatingCooling2": {
        "primary": "300_to_800_K_hydrogen_heating_cooling_rate_cycle",
        "intents": [
            "hydrogen_transport",
            "heating_cooling_cycle",
            "hydrogen_redistribution",
            "heating_rate_sensitivity",
        ],
        "features": [
            "the boundary temperature repeatedly cycles between 300 and 800 K",
            "the four heating and cooling rates are 100, 10, 1 and 0.1 K/min",
        ],
        "not_for": ["300 to 650 K hydrogen cycle", "external hydrogen ingress boundary"],
    },
    "actinidesRedistribution": {
        "primary": "americium_and_plutonium_radial_form_factor_verification",
        "intents": [
            "actinide_transport",
            "Am_redistribution",
            "Pu_redistribution",
            "radial_form_factor",
        ],
        "features": [
            "solverDict runs AmRedistribution and PuRedistribution through elementTransport byList in UPuO2",
            "sampleRadialProfile extracts PuFormFactor and AmFormFactor",
        ],
        "not_for": ["fission product release", "uranium enrichment sweep"],
    },
    "corrosion/fixedInnerHeatFlux": {
        "primary": "oxide_growth_with_inner_heat_flux_verification",
        "intents": ["cladding_corrosion", "oxide_thickness", "prescribed_heat_flux", "convective_outer_boundary"],
        "features": [
            "solverDict couples timeDependentLhgr, fuelRodGap and a 600 K outer convectiveHTC boundary to the corrosion model",
            "Allrun checks oxideThickness against 3.09346e-5 m",
        ],
        "not_for": ["fixed interface temperature corrosion"],
    },
    "corrosion/fixedInterfaceTemperature": {
        "primary": "oxide_growth_with_fixed_outer_interface_temperature_verification",
        "intents": ["cladding_corrosion", "oxide_thickness", "prescribed_interface_temperature"],
        "features": [
            "the cladding outer interface is fixed at 550 K while cladInner is zeroGradient",
            "Allrun checks oxideThickness against 2.73908e-5 m",
        ],
        "not_for": ["inner heat flux corrosion"],
    },
    "multiMaterial/biMaterialBlock1": {
        "primary": "bimaterial_block_pressure_loading_verification",
        "intents": ["multi_material_mechanics", "bimaterial_block", "pressure_loading", "interface_stress"],
        "features": [
            "0/D applies uniform 1 MPa pressure and zero traction to the loaded patch",
            "left and right cell-zone materials exercise the multi-material interface correction",
        ],
        "not_for": ["shear traction", "frictional contact"],
    },
    "multiMaterial/biMaterialBlock2": {
        "primary": "bimaterial_block_shear_traction_verification",
        "intents": ["multi_material_mechanics", "bimaterial_block", "shear_traction", "interface_stress"],
        "features": [
            "0/D applies uniform traction (0 1e6 0) and zero pressure to the loaded patch",
            "left and right cell-zone materials exercise the multi-material interface correction",
        ],
        "not_for": ["pressure-loaded block", "frictional contact"],
    },
    "multiMaterial/biMaterialCylinder1": {
        "primary": "concentric_bimaterial_cylinder_internal_pressure_verification",
        "intents": ["multi_material_mechanics", "bimaterial_cylinder", "internal_pressure", "interface_stress"],
        "features": [
            "0/D applies 1e7 Pa pressure at the inner cylinder boundary",
            "inner and outer material regions are joined by a cyclicAMI interface",
        ],
        "not_for": ["fixed torque", "frictional gap contact"],
    },
    "multiMaterial/biMaterialCylinder1_frictionalContact": {
        "primary": "concentric_bimaterial_cylinder_frictional_gap_contact_verification",
        "intents": ["multi_material_mechanics", "bimaterial_cylinder", "frictional_gap_contact", "internal_pressure"],
        "features": [
            "0/D applies 1e7 Pa inner pressure and couples the two interfaces with frictionalGapContact",
            "the interface frictionCoefficient is 1e60",
        ],
        "not_for": ["bonded cyclicAMI interface", "fixed torque"],
    },
    "multiMaterial/biMaterialCylinder2": {
        "primary": "bimaterial_cylinder_fixed_torque_torsion_verification",
        "intents": ["multi_material_mechanics", "bimaterial_cylinder", "fixed_torque", "torsion"],
        "features": [
            "0/D applies a fixedTorque boundary with torque 1",
            "the torque boundary sets pressure and traction to zero on the concentric material cylinder",
        ],
        "not_for": ["internal pressure", "frictional gap contact"],
    },
    "multiMaterial/biMaterialSkewBlock1": {
        "primary": "skew_bimaterial_block_pressure_loading_verification",
        "intents": ["multi_material_mechanics", "skew_block", "pressure_loading", "mesh_skewness"],
        "features": [
            "0/D applies uniform 1 MPa pressure and zero traction to the skew block",
            "the left and right material regions exercise interface stress on the skew mesh",
        ],
        "not_for": ["shear-loaded skew block", "frictional contact"],
    },
    "multiMaterial/biMaterialSkewBlock2": {
        "primary": "skew_bimaterial_block_shear_traction_verification",
        "intents": ["multi_material_mechanics", "skew_block", "shear_traction", "mesh_skewness"],
        "features": [
            "0/D applies uniform traction (0 1e6 0) and zero pressure to the skew block",
            "the left and right material regions exercise interface stress on the skew mesh",
        ],
        "not_for": ["pressure-loaded skew block", "frictional contact"],
    },
    "testBetaFraction": {
        "primary": "zircaloy_beta_phase_transition_thermal_cycle_verification",
        "intents": ["zircaloy_phase_transformation", "beta_phase_fraction", "temperature_history", "Massih_comparison"],
        "features": [
            "Allrun compares the Zircaloy phase-transition model with Massih equilibrium and plus-minus reference curves",
            "a 900-1400-900 K cycle and a slow equilibrium ramp check beta phase fraction 0.401681 at 1150 K",
        ],
        "not_for": ["neutronics", "delayed neutron fraction"],
    },
    "trisoBenchmarks/case_7": {
        "primary": "three_layer_long_irradiation_alternate_pyc_swelling_stress_benchmark",
        "intents": ["TRISO_benchmark_comparison", "coating_stress", "three_layer_coating", "long_irradiation", "PyC_swelling_coefficients"],
        "features": [
            "the fast-flux history extends to 1.0e8 s with alternate IPyC and OPyC PyCCorrelation radial and tangential coefficients",
            "Allrun checks IPyC tangential stress 3.95923e7 Pa and SiC tangential stress 9.0048e6 Pa",
        ],
        "not_for": ["case_6 irradiation duration", "thermal creep model test"],
    },
    "trisoBenchmarks/case_10": {
        "primary": "full_triso_lower_power_flux_pressure_and_sic_stress_benchmark",
        "intents": ["TRISO_benchmark_comparison", "particle_internal_pressure", "SiC_stress", "lower_power_flux_condition"],
        "features": [
            "vhgr is 2.487393346e9 W/m3, fast flux is 1.708707315e14 n/cm2/s and coating Tref is 1346 K",
            "Allrun checks particle pressure 6.56211e6 Pa and SiC stress -1.7035e8 Pa",
        ],
        "not_for": ["higher power and flux condition"],
    },
    "trisoBenchmarks/case_11": {
        "primary": "full_triso_higher_power_flux_pressure_and_sic_stress_benchmark",
        "intents": ["TRISO_benchmark_comparison", "particle_internal_pressure", "SiC_stress", "higher_power_flux_condition"],
        "features": [
            "vhgr is 3.561803753e9 W/m3, fast flux is 2.374169e14 n/cm2/s and coating Tref is 1608 K",
            "Allrun checks particle pressure 3.19538e7 Pa and SiC stress -8.42427e7 Pa",
        ],
        "not_for": ["lower power and flux condition"],
    },
    "trisoFpDiffusion/case_1a": {
        "primary": "kernel_only_1473K_cs_release_fraction_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "kernel_only", "prescribed_temperature"],
        "features": [
            "the Kernel-only FpDiffusion case prescribes 1473.15 K",
            "Allrun checks the Cs release fraction against 0.4673",
        ],
        "not_for": ["multilayer coating diffusion", "mechanics"],
    },
    "trisoFpDiffusion/case_1b": {
        "primary": "kernel_only_1873K_cs_release_fraction_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "kernel_only", "prescribed_temperature"],
        "features": [
            "the Kernel-only FpDiffusion case prescribes 1873.15 K with initialCsConcentration 1",
            "Allrun checks the Cs release fraction against 0.99999959",
        ],
        "not_for": ["multilayer coating diffusion", "mechanics"],
    },
    "trisoFpDiffusion/case_2a": {
        "primary": "kernel_buffer_ipyc_1473K_cs_release_fraction_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "Kernel_Buffer_IPyC", "prescribed_temperature"],
        "features": [
            "the Kernel-Buffer-IPyC FpDiffusion stack prescribes 1473.15 K for Cs transport",
            "Allrun checks the Cs release fraction against 0.0265125",
        ],
        "not_for": ["Kernel-only diffusion", "mechanics"],
    },
    "trisoFpDiffusion/case_2b": {
        "primary": "kernel_buffer_ipyc_1873K_cs_release_fraction_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "Kernel_Buffer_IPyC", "prescribed_temperature"],
        "features": [
            "the Kernel-Buffer-IPyC FpDiffusion stack prescribes 1873.15 K and includes Cs and Kr transport entries",
            "Allrun checks the Cs release fraction against 0.994653",
        ],
        "not_for": ["Kernel-only diffusion", "mechanics"],
    },
    "trisoFpDiffusion/case_3a": {
        "primary": "full_coating_1873K_cs_release_fraction_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "full_coating_stack", "prescribed_temperature"],
        "features": [
            "the spherical Kernel-Buffer-IPyC-SiC-OPyC transport stack is held at 1873.15 K",
            "Allrun checks the Cs release fraction against 1.54447e-4",
        ],
        "not_for": ["mechanics", "temperature solution"],
    },
    "trisoFpDiffusion/case_3b": {
        "primary": "full_coating_2073K_cs_release_fraction_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "full_coating_stack", "prescribed_temperature"],
        "features": [
            "the spherical Kernel-Buffer-IPyC-SiC-OPyC transport stack is held at 2073.15 K",
            "Allrun checks the Cs release fraction against 0.210283",
        ],
        "not_for": ["mechanics", "temperature solution"],
    },
    "trisoFpDiffusion/case_3c": {
        "primary": "full_coating_radial_temperature_gradient_cs_release_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "prescribed_temperature_gradient", "radial_sampling"],
        "features": [
            "the full coating stack uses 1873.15 K internally and 2073.15 K at the outer boundary",
            "Allrun checks Cs release fraction 0.225066 and executes sampleDict",
        ],
        "not_for": ["mechanics", "temperature solution"],
    },
    "trisoFpDiffusion/case_3d": {
        "primary": "two_run_sic_crack_cs_cumulative_release_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "SiC_crack_release", "two_stage_restart", "prescribed_temperature_gradient"],
        "features": [
            "Allrun enables SiC crackFpRelease for the second solve and accumulates Cs released over both runs",
            "the cumulative Cs release fraction is checked against 0.999992",
        ],
        "not_for": ["single-run release", "mechanics"],
    },
    "trisoFpDiffusion/case_3e": {
        "primary": "two_run_pyc_crack_cs_kr_cumulative_release_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "krypton_release_fraction", "PyC_crack_release", "two_stage_restart", "prescribed_temperature_gradient"],
        "features": [
            "Allrun enables IPyC and OPyC crackFpRelease for the second solve and accumulates Cs and Kr over both runs",
            "the cumulative Cs and Kr release fractions are each checked against 1",
        ],
        "not_for": ["single-run release", "mechanics"],
    },
    "trisoFpDiffusion/case_4a": {
        "primary": "two_stage_1273K_to_1873K_cs_ag_release_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "silver_release_fraction", "temperature_history"],
        "features": [
            "Allrun advances two stages at 1273.15 K and 1873.15 K",
            "cumulative Cs and Ag release fractions are checked against 0.000235404 and 0.403467",
        ],
        "not_for": ["single-stage temperature", "mechanics"],
    },
    "trisoFpDiffusion/case_4b": {
        "primary": "two_stage_1273K_to_2073K_cs_ag_release_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "silver_release_fraction", "temperature_history"],
        "features": [
            "Allrun advances two stages at 1273.15 K and 2073.15 K",
            "cumulative Cs and Ag release fractions are checked against 0.210138 and 0.862284",
        ],
        "not_for": ["single-stage temperature", "mechanics"],
    },
    "trisoFpDiffusion/case_4c": {
        "primary": "three_stage_1273K_1873K_2073K_cs_ag_release_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "silver_release_fraction", "temperature_history"],
        "features": [
            "Allrun advances three stages at 1273.15 K, 1873.15 K and 2073.15 K",
            "summed released amounts give Cs and Ag fractions 0.223638 and 0.915856",
        ],
        "not_for": ["remaining-inventory release calculation", "mechanics"],
    },
    "trisoFpDiffusion/case_4d": {
        "primary": "three_stage_remaining_inventory_cs_kr_release_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "krypton_release_fraction", "temperature_history", "remaining_inventory_method"],
        "features": [
            "Allrun advances 1273.15 K, 1873.15 K and 2073.15 K stages and derives release from final remaining inventory",
            "Cs and Kr release fractions are checked against 0.999866 and 0.988044",
        ],
        "not_for": ["summed released-amount calculation", "mechanics"],
    },
    "trisoFpDiffusion/case_5a": {
        "primary": "single_run_cyclic_temperature_low_cs_ag_release_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "silver_release_fraction", "temperature_history", "single_run"],
        "features": [
            "the prescribed table begins at 873.15 K and cycles to 1273.15 K during one uninterrupted run",
            "Allrun checks very low Cs and Ag release fractions 2.7116e-17 and 6.78835e-6",
        ],
        "not_for": ["extended high-temperature second stage", "mechanics"],
    },
    "trisoFpDiffusion/case_5b": {
        "primary": "extended_two_stage_temperature_cs_ag_cumulative_release_benchmark",
        "intents": ["fission_product_diffusion", "cesium_release_fraction", "silver_release_fraction", "temperature_history", "two_stage_restart"],
        "features": [
            "Allrun extends the prescribed history to 8.712e7 s and performs a second cumulative-release solve",
            "Cs and Ag release fractions are checked against 0.000315053 and 0.398419",
        ],
        "not_for": ["single uninterrupted low-release run", "mechanics"],
    },
    "generic_pwr_1D_newSCIANTIXinput": {
        "primary": "pwr_sciantix_revised_power_and_fuel_input_template",
        "intents": ["PWR_fuel_rod", "SCIANTIX_FGR", "revised_power_history", "fuel_input_parameters"],
        "features": [
            "the SCIANTIX fixture uses an LHGR history of 0, 20 and 10 kW/m and fuel grain radius 2.8e-5 m",
            "fuel resinteringDensityChange is 0.3 with elastic fuel rheology",
        ],
        "not_for": ["baseline generic PWR input", "SCIANTIX result extraction"],
    },
    "generic_rodlet_2D_rz": {
        "primary": "discrete_pellet_rodlet_rz_template",
        "intents": ["fuel_rod_thermomechanics", "axisymmetric_rz", "rodlet_template", "discrete_pellet_stack"],
        "features": [
            "rodDict uses geometryType 2Ddiscrete for the axisymmetric rodlet",
            "repeated fuelTop and fuelBottom coupled boundaries connect the pellet stack",
        ],
        "not_for": ["smeared pellet geometry", "single radial slice"],
    },
    "porosity/testCaseBISON/onlyFuel": {
        "primary": "fuel_only_pore_velocity_model_comparison",
        "intents": ["porosity_transport", "pore_velocity", "UPuO2_fuel", "radial_profile"],
        "features": [
            "Allrun compares UO2Sens, MOXLackey and vaporPressureMOX poreVelocityModel settings in a fuel-only UPuO2 mesh",
            "sampleRadialProfile extracts porosity while component outputs record pore velocity and gradT",
        ],
        "not_for": ["fuel-cladding mechanics", "neutronics"],
    },
    "test_coolantChannel/generic_bwr_2D_RIA_stagnantFlow": {
        "primary": "bwr_stagnant_flow_ria_power_pulse_enthalpy_case",
        "intents": [
            "coolant_heat_transfer",
            "stagnant_flow",
            "RIA_power_pulse",
            "transient_linear_heat_rate",
            "coolant_enthalpy",
            "coolant_temperature",
            "constant_system_pressure",
        ],
        "features": [
            "lhrTimes and lhrValues define a sharp RIA pulse from about 1.196 to 1.214 s while system pressure stays at 101325 Pa",
            "calculateEnthalpy is true and enthalpyVolAverage records the enthalpy field",
        ],
        "not_for": ["flowing coolant channel", "steady linear heat rate"],
    },
    "test_coolantChannel/generic_bwr_1D_enthalpyModel_parallel": {
        "primary": "bwr_enthalpy_parallel_execution_consistency",
        "intents": ["coolant_heat_transfer", "BWR_coolant_channel", "enthalpy_model", "parallel_execution"],
        "features": [
            "Allrun decomposes the mesh, executes runParallel offbeat and reconstructs the result",
            "the consistency check requires exactly one solver end marker before removing processor directories",
        ],
        "not_for": ["serial enthalpy execution", "coolant-temperature formulation"],
    },
}


def _exercise_override(case_id: str) -> dict[str, Any]:
    name = case_id.rsplit("/", 1)[-1]
    solved = name.endswith("_solved")
    stage = name.removesuffix("_solved")
    role = "completed reference" if solved else "learner starter"
    stage_data: dict[str, tuple[str, list[str], str]] = {
        "case1": (
            "thermal_baseline",
            ["thermal_conduction", "linear_heat_rate", "fixed_gap_conductance"],
            "constant fuel conductivity and a fixed gap conductance isolate radial heat transfer",
        ),
        "case1a": (
            "lower_fuel_conductivity_variant",
            ["thermal_conduction", "fuel_conductivity_sensitivity"],
            "the Case 1 variant sets fuel thermal conductivity to 2 W/m/K",
        ),
        "case1b": (
            "lower_gap_conductance_variant",
            ["thermal_conduction", "gap_conductance_sensitivity"],
            "the Case 1 variant sets gap conductance to 2000 W/m2/K",
        ),
        "case1c": (
            "annular_fuel_variant",
            ["thermal_conduction", "central_hole", "annular_fuel"],
            "the Case 1 variant adds a 0.75 mm central fuel hole",
        ),
        "case2": (
            "temperature_dependent_conductivity_and_burnup",
            ["thermal_conduction", "burnup", "temperature_dependent_conductivity"],
            "temperature-dependent UO2 conductivity and burnup extend the thermal baseline",
        ),
        "case3": (
            "thermomechanics_and_variable_gap",
            ["fuel_rod_thermomechanics", "gap_gas", "gap_closure"],
            "small-strain mechanics and a variable FRAPCON gap extend Case 2",
        ),
        "case3a": (
            "isotropic_fuel_cracking_variant",
            ["fuel_rod_thermomechanics", "isotropic_cracking", "gap_closure"],
            "isotropicCracking with up to 12 cracks extends the Case 3 mechanics setup",
        ),
        "case4": (
            "fuel_densification_and_relocation",
            ["fuel_densification", "fuel_relocation", "gap_closure"],
            "empirical densification and UO2FRAPCON relocation extend Case 3",
        ),
        "case5": (
            "cladding_creep_and_fast_flux",
            ["cladding_creep", "fast_flux", "fuel_rod_thermomechanics"],
            "Limback cladding creep and a time-dependent fast-flux profile extend Case 4",
        ),
        "case6": (
            "fission_gas_release_and_swelling",
            ["SCIANTIX_FGR", "fuel_swelling", "cladding_growth", "gap_gas"],
            "SCIANTIX FGR, UO2 swelling and Zircaloy growth extend Case 5",
        ),
        "case7": (
            "two_dimensional_smeared_geometry_transition",
            ["two_dimensional_fuel_rod", "axial_variation", "thermomechanics"],
            "the exercise transitions the complete one-dimensional physics set to a smeared r-z mesh",
        ),
        "case7a": (
            "two_dimensional_axial_mesh_variant",
            ["two_dimensional_fuel_rod", "axial_mesh_sensitivity", "thermomechanics"],
            "the completed r-z variant changes the axial discretization of the Case 7 mesh",
        ),
        "case8": (
            "two_dimensional_axial_power_profile",
            ["two_dimensional_fuel_rod", "axial_power_profile", "thermomechanics"],
            "the smeared r-z model resolves the prescribed axial power and fast-flux profiles",
        ),
        "case9": (
            "two_dimensional_discrete_pellet_stack",
            ["discrete_pellets", "pellet_contact", "two_dimensional_fuel_rod"],
            "rodDict builds ten discrete pellets with dish geometry and sliceMapper=byPellets",
        ),
    }
    if stage not in stage_data:
        raise RebuildError(f"unrecognized exercise case: {case_id}")
    semantic_name, intents, feature = stage_data[stage]
    return {
        "primary": f"offbeat_training_{semantic_name}_{'reference' if solved else 'starter'}",
        "intents": ["OFFBEAT_training", *intents],
        "features": [
            f"{name} is the {role} for this curriculum stage",
            feature,
        ],
        "not_for": ["verification benchmark", "production reference case"],
    }


def _component_labels(profile: Profile, text: str) -> list[str]:
    path = profile.official_path
    if profile.case_id == "testBetaFraction":
        return ["zirconium_material_fixture"]
    if profile.case_id == "actinidesRedistribution":
        return ["fuel_pellet"]
    if "NaCoolantChannelModel" in path:
        return ["sodium_channel", "coolant_channel"]
    if "waterCoolantChannel" in path or "test_coolantChannel" in path:
        return ["water_channel", "coolant_channel", "fuel_rod"]
    if "trisoFpDiffusion" in path:
        return ["TRISO_coating_transport"]
    if "trisoBenchmarks" in path:
        return ["TRISO_particle"]
    if "trisoModulesTest" in path:
        return ["TRISO_material_or_particle_fixture"]
    if "hydrogenTransport" in path or "/corrosion/" in path:
        return ["zirconium_cladding"]
    if "/multiMaterial/" in path or "BiMaterial" in path:
        return ["multi_material_solid"]
    if "/neutronics/" in path or "/porosity" in path:
        return ["fuel_pellet"]
    if any(term in path for term in ("beamBending", "plateHole", "thickCylinder", "volumeConservation")):
        return ["structural_solid"]
    if "graphite_stringer" in path:
        return ["graphite_structure"]
    if "test_createTuFields" in path:
        return ["field_generation_utility"]
    if "generic_TRISO" in path:
        return ["TRISO_particle"]
    if profile.family == "exerciseOFFBEAT":
        return ["fuel_rod"]
    if any(term in text.lower() for term in ("fuel rod", "fuel_rod", "gap volume", "gap_volume")):
        return ["fuel_rod"]
    return ["material_or_structure_fixture"]


def _context_labels(profile: Profile) -> list[str]:
    path = profile.official_path
    labels: list[str] = []
    if profile.case_id == "testBetaFraction":
        labels.append("zirconium_alloy")
    rules = (
        ("NaCoolantChannelModel", ("sodium_coolant", "SFR")),
        ("burnupFBR", ("fast_reactor",)),
        ("Case_ABWR", ("water_coolant", "ABWR")),
        ("Case_AP1000", ("water_coolant", "AP1000", "PWR")),
        ("Case_BWR4", ("water_coolant", "BWR4", "BWR")),
        ("Case_VVER440", ("water_coolant", "VVER440", "PWR")),
        ("generic_bwr", ("water_coolant", "BWR")),
        ("generic_pwr", ("water_coolant", "PWR")),
        ("exerciseOFFBEAT", ("LWR", "UO2_Zircaloy")),
        ("triso", ("TRISO",)),
        ("TRISO", ("TRISO",)),
        # The generic MOX case declares reactorType "FBR" in solverDict.
        # Keep the material and reactor context separate and do not infer LWR
        # from neighboring generic fuel-rod tutorials.
        ("generic_mox", ("MOX", "fast_reactor")),
        ("generic_PUZRY", ("zirconium_alloy",)),
        ("hydrogenTransport", ("zirconium_alloy",)),
        ("corrosion", ("zirconium_alloy",)),
        ("graphite", ("graphite",)),
    )
    for needle, values in rules:
        if needle in path:
            labels.extend(values)
    return _dedupe(labels)


def _geometry_label(profile: Profile) -> str:
    if profile.case_id in {
        "generic_pwr_2D_rTheta",
        "porosity/testCase2DrTheta",
    }:
        return "2D_rTheta"
    if profile.case_id in {
        "trisoModulesTest/hollowsphere_1D",
        "trisoModulesTest/sphere_1D",
        "trisoModulesTest/sphere_vhgr",
        "trisoModulesTest/testPyC_alpha_spherical",
    }:
        # These module fixtures are explicitly one-dimensional spherical in
        # their case identity and README.  The wedge mesh representation in a
        # filesystem profile is an implementation detail, not 2-D semantics.
        return "1D_spherical"
    dimension = (profile.geometry_dimension or "").lower()
    coordinate = (profile.geometry_coordinate or "").lower()
    generator = (profile.geometry_generator or "").lower()
    if "spherical" in coordinate or "sphere" in generator:
        return "1D_spherical" if "1d" in dimension or "sphere" in generator else "spherical"
    if "r-theta" in coordinate:
        return "2D_rTheta"
    if "r-z" in coordinate:
        return "2D_rZ_axisymmetric"
    if "radial" in coordinate:
        return "1D_radial" if "1d" in dimension else "radial"
    if "axisymmetric" in coordinate or "wedge" in coordinate:
        return "2D_axisymmetric_wedge"
    if "2d" in dimension:
        return "2D_reduced"
    if "1d" in dimension:
        return "1D_reduced"
    if "rod" in dimension or "cylindrical" in coordinate:
        return "fuel_rod_mesh"
    return "case_defined_mesh"


def _semantic_terms(primary: str, intents: list[str]) -> str:
    """Return normalized, positive curation fields only (never exclusions/prose)."""

    return " ".join([primary, *intents]).replace("_", " ").lower()


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _coarse_case_intent(profile: Profile, primary: str) -> str:
    path = profile.official_path
    if profile.family == "exerciseOFFBEAT":
        return "exercise_case"
    if path.startswith("Cases/restart/"):
        return "restart_test"
    if profile.case_id == "testUserParameters":
        return "parameter_test"
    if profile.case_id == "test_createTuFields":
        return "solver_feature_test"
    if profile.family == "trisoModulesTest":
        return "module_test"
    if profile.family == "damageModel" or profile.case_id == "testBetaFraction" or "model_test" in primary.lower():
        return "material_model_test"
    if "vsAnalytical" in path or "analytical" in primary.lower():
        return "analytical_comparison"
    if any(
        term in path or term in primary
        for term in ("vsTRACE", "waterCoolantChannel", "SERPENT", "BISON")
    ):
        return "code_comparison"
    if path.startswith("Cases/Verification/"):
        return "verification_benchmark"
    if any(
        term in path
        for term in (
            "/generic_",
            "/hotBiMaterial",
            "/graphite_stringer",
            "/smearedCrackingExample",
            "/porosity/",
        )
    ):
        return "engineering_tutorial"
    return "solver_feature_test"


def _physics_labels(profile: Profile, primary: str, intents: list[str]) -> list[str]:
    text = _semantic_terms(primary, intents)
    if profile.family == "trisoFpDiffusion":
        # Temperature fields in this family are prescribed inputs while
        # thermalSolver is fromLatestTime; the cases solve species transport.
        return ["fission_product_diffusion"]

    result: list[str] = []
    rules = (
        ((r"\bthermal\w*\b", r"\bthermomechan\w*\b", r"\bheat\w*\b", r"\bconduct\w*\b"), "thermal_conduction"),
        ((r"\bmechanic\w*\b", r"\bthermomechan\w*\b", r"\bstress\b", r"\bstrain\b", r"\bcreep\b", r"\bbending\b", r"\bexpansion\b", r"\bdensification\b", r"\brelocation\b"), "solid_mechanics"),
        ((r"\bhydrogen\b",), "hydrogen_transport"),
        ((r"\bactinide\w*\b",), "actinide_transport"),
        ((r"\bcorrosion\b", r"\boxide\b"), "cladding_corrosion"),
        ((r"\bporosity\b",), "porosity_evolution"),
        ((r"\bneutronic\w*\b", r"\benrichment\b", r"\bneutron flux\b"), "neutronics"),
        ((r"\bburnup\b",), "burnup"),
        ((r"\bgap gas\b", r"\bgap volume\b"), "gap_gas"),
        ((r"\bfission gas\b", r"\bfgr\b", r"\bsciantix\b"), "fission_gas_release"),
        ((r"\bdamage\b", r"\bcrack\w*\b"), "damage_mechanics"),
    )
    for patterns, label in rules:
        if _has(text, *patterns):
            result.append(label)
    thermal_scope = _has(
        text,
        r"\bthermal",
        r"\bthermomechan",
        r"\bheat",
        r"\btemperature",
        r"\bcoolant",
        r"\benthalpy",
        r"\btrace\b",
    )
    mechanics_scope = _has(
        text,
        r"\bmechanic",
        r"\bthermomechan",
        r"\bstress",
        r"\bstrain",
        r"\bcreep",
        r"\bbending",
        r"\btraction",
        r"\btorsion",
        r"\bdisplacement",
    )
    thermal_case_scope = thermal_scope or profile.family in {
        "trisoBenchmarks",
        "exerciseOFFBEAT",
        "hydrogenTransport",
        "porosity",
    } or "porosity" in profile.case_id.lower() or "gapVolume" in profile.case_id or profile.case_id == "generic_pwr_1D_newSCIANTIXinput"
    mechanics_case_scope = mechanics_scope or profile.family == "exerciseOFFBEAT" or "gapVolume" in profile.case_id or profile.case_id == "generic_pwr_1D_newSCIANTIXinput"
    if profile.model_switches.get("thermalSolver") == "solidConduction" and thermal_case_scope:
        result.append("thermal_conduction")
    if (
        profile.model_switches.get("mechanicsSolver") not in INACTIVE_SWITCHES | {"constant"}
        and mechanics_case_scope
    ):
        result.append("solid_mechanics")
    if (
        profile.model_switches.get("neutronicsSolver") not in INACTIVE_SWITCHES | {"constant"}
        and (profile.family == "neutronics" or _has(text, r"\bneutronic", r"\bneutron flux", r"\benrichment"))
    ):
        result.append("neutronics")
    if (
        profile.model_switches.get("fgr") not in INACTIVE_SWITCHES | {"constant"}
        and _has(text, r"\bfgr", r"\bsciantix", r"\bfission gas")
    ):
        result.append("fission_gas_release")
    if (
        profile.model_switches.get("corrosion") not in INACTIVE_SWITCHES | {"constant"}
        and _has(text, r"\bcorrosion", r"\boxide")
    ):
        result.append("cladding_corrosion")
    if profile.family in {"NaCoolantChannelModel", "waterCoolantChannel", "test_coolantChannel"}:
        result.append("coolant_heat_transfer")
    if profile.case_id == "testBetaFraction":
        result.append("material_phase_transformation")
    if profile.family == "trisoBenchmarks":
        result.extend(["solid_mechanics", "TRISO_thermomechanics"])
    if profile.family == "trisoModulesTest":
        result.append("module_verification")
    return _dedupe(result)


def _model_features(
    profile: Profile,
    solver_text: str,
    primary: str,
    intents: list[str],
) -> list[str]:
    solver_text = re.sub(r"/\*.*?\*/", "", solver_text, flags=re.DOTALL)
    solver_text = re.sub(r"//.*$", "", solver_text, flags=re.MULTILINE)
    result: list[str] = []
    allowed_switches = {
        "mechanicsSolver",
        "neutronicsSolver",
        "elementTransport",
        "heatSource",
        "burnup",
        "fastFlux",
        "corrosion",
        "gapGas",
        "fgr",
        "sliceMapper",
        "damageModel",
    }
    text = _semantic_terms(primary, intents)
    aligned_switches = {
        "mechanicsSolver": _has(text, r"\bmechanic", r"\bstress", r"\bstrain", r"\bcreep", r"\btorsion", r"\btraction", r"\bpressure"),
        "neutronicsSolver": profile.family == "neutronics" or _has(text, r"\bneutronic", r"\bneutron flux", r"\benrichment"),
        "elementTransport": profile.family in {"trisoFpDiffusion", "hydrogenTransport", "porosity"} or _has(text, r"\bactinide", r"\btransport"),
        "heatSource": _has(text, r"\bheat", r"\blhgr", r"\bvhgr", r"\bpower"),
        "burnup": _has(text, r"\bburnup"),
        "fastFlux": _has(text, r"\bfast flux", r"\bfluence", r"\birradiation", r"\bswelling", r"\bcreep"),
        "corrosion": _has(text, r"\bcorrosion", r"\boxide"),
        "gapGas": _has(text, r"\bgap gas", r"\bgap volume", r"\binternal pressure"),
        "fgr": _has(text, r"\bfgr", r"\bsciantix", r"\bfission gas"),
        "sliceMapper": _has(text, r"\bslice", r"\bpellet"),
        "damageModel": _has(text, r"\bdamage", r"\bcrack"),
    }
    for key, value in profile.model_switches.items():
        if key not in allowed_switches or value in INACTIVE_SWITCHES:
            continue
        if not aligned_switches.get(key, False):
            continue
        if key == "sliceMapper" and value == "autoAxialSlices":
            continue
        if key == "mechanicsSolver" and value == "smallStrain":
            continue
        if key == "neutronicsSolver" and value == "diffusion":
            continue
        if key == "elementTransport" and value == "byList":
            # The concrete transport solver belongs in a case-specific label;
            # the byList dispatcher itself is shared scaffolding.
            continue
        if key == "heatSource" and value == "timeDependentLhgr" and not _has(
            text,
            r"\blinear heat rate",
            r"\blhgr\b",
            r"\bpower history",
            r"\bheat conservation",
        ):
            continue
        result.append(f"{key}={value}")
    aligned_special_terms = {
        "FpDiffusion": profile.family == "trisoFpDiffusion",
        "constantCreepPrincipalStress": _has(text, r"\bcreep", r"\bcoating stress"),
        "correlationCreepPrincipalStress": _has(text, r"\bcreep", r"\bcoating stress"),
        "MonolithicSiCCreepModel": _has(text, r"\bsilicon carbide", r"\bsic") and _has(text, r"\bcreep"),
        "PARFUMUEBufferCreepModel": _has(text, r"\bbuffer") and _has(text, r"\bcreep"),
        "PyCPARFUME": _has(text, r"\bpyrocarbon", r"\bpyc"),
        "BufferPARFUME": _has(text, r"\bbuffer"),
        "SiCPARFUME": _has(text, r"\bsilicon carbide", r"\bsic"),
        "SiCSnead": _has(text, r"\bsilicon carbide", r"\bsic"),
        "UO2MATPRO": _has(text, r"\bmatpro"),
        "UO2FRAPCON": _has(text, r"\bfrapcon", r"\bdensification", r"\brelocation"),
        "growthBISONZy": _has(text, r"\bzircaloy growth", r"\bcladding growth"),
        "LimbackCreepModel": _has(text, r"\blimback", r"\bcladding creep"),
        "smearedCracking": _has(text, r"\bsmeared cracking"),
        "isotropicCracking": _has(text, r"\bisotropic cracking"),
    }
    for term in SPECIAL_MODEL_TERMS:
        if not aligned_special_terms.get(term, False):
            continue
        if term == "isotropicCracking":
            active = re.search(r"\bisotropicCracking\s+on\s*;", solver_text)
        else:
            active = re.search(rf"\b{re.escape(term)}\b", solver_text)
        if (
            active
            and f"damageModel={term}" not in result
            and not (profile.family == "trisoFpDiffusion" and term == "FpDiffusion")
        ):
            result.append(term)
    if profile.family == "trisoFpDiffusion" and "FpDiffusion" in solver_text:
        result.append("elementTransportSolver=FpDiffusion")
    if profile.case_id == "testUserParameters":
        result.append("userParameters")
    return _dedupe(result)


def _driving_labels(profile: Profile, primary: str, intents: list[str]) -> list[str]:
    text = _semantic_terms(primary, intents)
    result: list[str] = []
    rules = (
        ((r"\btemperature ramp\b", r"\btemperature history\b", r"\bheating transient\b", r"\bcooling transient\b", r"\bthermal cycle\b"), "temperature_history"),
        ((r"\bprescribed temperature\b", r"\bprescribed temperature gradient\b"), "prescribed_temperature"),
        ((r"\bheat flux\b",), "prescribed_heat_flux"),
        ((r"\binterface temperature\b",), "prescribed_interface_temperature"),
        ((r"\blinear heat rate\b", r"\blhgr\b"), "linear_heat_rate"),
        ((r"\bvolumetric heat\w*\b", r"\bvhgr\b"), "volumetric_heat_rate"),
        ((r"\bfast flux\b", r"\bfluence\b", r"\birradiation\b"), "fast_neutron_exposure"),
        ((r"\benrichment\b",), "fuel_enrichment"),
        ((r"\bradius sweep\b", r"\bdifferent radii\b"), "pellet_radius"),
        ((r"\blaser\b",), "laser_source"),
    )
    for patterns, label in rules:
        if _has(text, *patterns):
            result.append(label)
    if profile.family in {"NaCoolantChannelModel", "waterCoolantChannel", "test_coolantChannel"} and profile.case_id != "test_coolantChannel/generic_bwr_2D_RIA_stagnantFlow":
        result.append("coolant_mass_flow")
    if profile.case_id == "test_coolantChannel/generic_bwr_2D_RIA_stagnantFlow":
        result.extend(["transient_linear_heat_rate", "RIA_power_pulse", "constant_pressure"])
    if profile.case_id in {"plateHole", "thickCylinderExpansion"}:
        result.append("pressure_loading")
    if profile.case_id == "beamBending":
        result.append("traction_loading")
    if profile.case_id in {
        "multiMaterial/biMaterialBlock1",
        "multiMaterial/biMaterialCylinder1",
        "multiMaterial/biMaterialCylinder1_frictionalContact",
        "multiMaterial/biMaterialSkewBlock1",
    }:
        result.append("pressure_loading")
    if profile.case_id in {
        "multiMaterial/biMaterialBlock2",
        "multiMaterial/biMaterialSkewBlock2",
    }:
        result.append("traction_loading")
    if profile.case_id == "multiMaterial/biMaterialCylinder2":
        result.append("torque_loading")
    if profile.case_id == "multiMaterial/biMaterialCylinder1_frictionalContact":
        result.append("frictional_contact")
    if profile.family == "trisoFpDiffusion" and "temperature_history" in result:
        result.append("prescribed_temperature")
    return _dedupe(result)


def _output_labels(profile: Profile, primary: str, intents: list[str]) -> list[str]:
    text = _semantic_terms(primary, intents)
    result: list[str] = []
    physics = _physics_labels(profile, primary, intents)

    if profile.family == "trisoFpDiffusion":
        result.append("species_concentration")
        if _has(text, r"\brelease\b", r"\bbarrier\b"):
            result.append("release_fraction")
        return result

    if profile.family == "waterCoolantChannel":
        return ["wall_temperature", "TRACE_deviation"]

    if profile.family == "NaCoolantChannelModel":
        result.append("coolant_temperature")
        if "vsTRACE" in profile.case_id:
            result.append("TRACE_deviation")
        return _dedupe(result)

    if profile.family == "test_coolantChannel":
        if _has(text, r"\benthalpy\b"):
            result.append("coolant_enthalpy")
        if "coolantTemperature" in profile.case_id or _has(
            text, r"\bwall temperature\b", r"\bcoolant temperature\b", r"\btrace\b"
        ):
            result.append("coolant_temperature")
        if _has(text, r"\bdnb\b", r"\bchf\b"):
            result.append("critical_heat_flux_or_DNB")
        if profile.case_id == "test_coolantChannel/generic_bwr_2D_RIA_stagnantFlow":
            result.extend(["coolant_enthalpy", "coolant_temperature"])
        return _dedupe(result)

    if profile.family == "trisoBenchmarks":
        if _has(text, r"\bstress\b", r"\bmechanic\w*\b", r"\bcreep\b", r"\bswelling\b"):
            result.append("coating_stress_or_strain")
        if _has(text, r"\binternal pressure\b", r"\bgap gas pressure\b"):
            result.append("particle_internal_pressure")
        if _has(text, r"\bdisplacement\b"):
            result.append("coating_displacement")
        return _dedupe(result)

    if profile.family == "trisoModulesTest":
        if _has(text, r"\bcreep\b"):
            result.append("creep_strain")
        if _has(text, r"\bswelling\b"):
            result.append("swelling_strain")
        if _has(text, r"\byoung modulus\b", r"\bpoisson ratio\b", r"\belastic constants\b"):
            result.append("elastic_properties")
        if _has(text, r"\bthermal conductivity\b"):
            result.append("thermal_conductivity")
        if _has(text, r"\bheat capacity\b"):
            result.append("heat_capacity")
        if _has(text, r"\bthermal expansion\b"):
            result.append("thermal_expansion_or_displacement")
        if _has(text, r"\bgap volume\b"):
            result.extend(["gap_volume", "particle_internal_pressure"])
        if "thermal_conduction" in physics:
            result.append("temperature")
        if "solid_mechanics" in physics and not any(
            value in result
            for value in ("creep_strain", "swelling_strain", "elastic_properties")
        ):
            result.append("stress_or_strain")
        if _has(text, r"\bsphere", r"\bdisplacement") and "solid_mechanics" in physics:
            result.append("displacement")
        return _dedupe(result)

    if profile.case_id == "testBetaFraction":
        return ["beta_phase_fraction", "temperature"]

    if profile.family == "hydrogenTransport" or profile.case_id == "actinidesRedistribution":
        result.append("species_concentration")
    if profile.family == "neutronics":
        result.append("neutron_flux_or_power")
    if profile.case_id == "actinidesRedistribution":
        result.append("actinide_form_factor")
    if "porosity" in profile.case_id.lower():
        result.append("porosity")
    if _has(text, r"\bburnup\b"):
        result.append("burnup")
    if _has(text, r"\bthermal conductivity\b", r"\bconductivity sensitivity\b"):
        result.append("thermal_conductivity")
    if "thermal_conduction" in physics:
        result.append("temperature")
    if "solid_mechanics" in physics:
        result.append("stress_or_strain")
    if profile.case_id in {"beamBending", "thickCylinderExpansion", "volumeConservationLargeStrain"}:
        result.append("displacement")
    if "gapVolume" in profile.case_id:
        result.append("gap_volume")
    if _has(text, r"\bgap gas pressure\b"):
        result.append("rod_internal_pressure")
    if (
        profile.model_switches.get("gapGas") not in INACTIVE_SWITCHES | {"constant"}
        and ("generic_pwr" in profile.case_id or "generic_mox" in profile.case_id)
    ):
        result.append("rod_internal_pressure")
    if profile.case_id == "generic_TRISO_1D":
        result.append("particle_internal_pressure")
    if profile.case_id == "multiMaterial/biMaterialCylinder1_frictionalContact":
        result.append("contact_pressure")
    if "fission_gas_release" in physics:
        result.append("fission_gas_release")
    if "cladding_corrosion" in physics:
        result.append("oxide_thickness")
    if profile.case_id == "volumeConservationLargeStrain":
        result.append("volume_change")
    if "beta_fraction" in primary.lower():
        result.append("beta_fraction")
    if profile.case_id == "testUserParameters":
        result.append("user_parameter_substitution")
    return _dedupe(result)


def _sanitize_phrase(value: str) -> str:
    value = value.strip().rstrip(".")
    replacements = (
        (r"\buse when (?:the )?query (?:explicitly )?(?:asks for|mentions)\b", "is distinguished by"),
        (r"\buse for\b", "covers"),
        (r"\buse before\b", "precedes"),
        (r"\bselect only when\b", "is limited to cases where"),
        (r"\bsuitable for\b", "covers"),
        (r"\bdo not use merely for\b", "does not represent"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return " ".join(value.split())


def _positive_feature_clauses(values: Iterable[str]) -> list[str]:
    """Remove retrieval contrasts while retaining case-configuration negatives.

    Phrases such as ``swellingModel none``, ``IPyC false`` and ``no creep
    model`` identify the configuration itself.  Clauses such as ``not stress``
    or ``rather than enthalpy`` only name an off-domain sibling and belong in
    ``do_not_use_for``, not embedding text.
    """

    result: list[str] = []
    for value in values:
        for raw_clause in re.split(r"\s*;\s*", value):
            clause = raw_clause.strip().rstrip(".")
            if not clause:
                continue
            if re.match(r"^(?:not|does not|do not)\b", clause, flags=re.IGNORECASE):
                continue
            clause = re.split(
                r"\s+\b(?:rather than|instead of)\b",
                clause,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].rstrip(" ,")
            if re.search(r"\bnot\b", clause, flags=re.IGNORECASE):
                if re.search(r",\s*not\b", clause, flags=re.IGNORECASE):
                    clause = re.split(r",\s*not\b", clause, maxsplit=1, flags=re.IGNORECASE)[0]
                else:
                    # A mid-clause "not" (for example "solvers are not
                    # advanced") is an off-domain contrast rather than one of
                    # the explicit model-value facts retained above.
                    continue
            clause = clause.strip().rstrip(" ,")
            if clause and not re.search(r"\bquery\b", clause, flags=re.IGNORECASE):
                result.append(clause)
    return _dedupe(result)


SOURCE_LOCATOR = re.compile(
    r"\b(?:README|Allrun|solverDict|controlDict|blockMeshDict|dynamicMeshDict|"
    r"sphereDict|rodDict|sampleDict|chfTableDict|porosityOptions|TuOFFBEATdict|"
    r"sampleRadialProfile|rod3Dmaker|fieldAverage|globalOptions|lhrTimes|lhrValues|"
    r"enthalpyVolAverage)\b|"
    r"\b(?:system|constant|0)/\S+|\b\S+\.(?:csv|dat|ods|py|txt|xlsx?)\b",
    re.IGNORECASE,
)


def _naturalize_feature(value: str) -> str:
    """Turn evidence-locator prose into a case fact used for retrieval.

    Source filenames belong in ``provenance.official_case_files``.  The positive
    retrieval fields state the engineering fact established by those files so
    that a filename such as ``README`` cannot become a shared semantic feature.
    The final guard deliberately makes newly introduced locator prose a rebuild
    error instead of silently publishing it.
    """

    exact_rewrites = {
        "contains TRACE_Twall, TRACE_T0 and TRACE_qwall reference files": (
            "reference profiles provide wall temperature, inlet temperature and wall heat flux"
        ),
        "resultsSERPENT.csv and input_settings.txt are present": (
            "SERPENT burnup results and their irradiation inputs are included for comparison"
        ),
        "constant dynamicMeshDict and 0/pointDisplacement are present": (
            "the case includes mesh motion driven by a point-displacement field"
        ),
        "system/TuOFFBEATdict is the subject of this utility test": (
            "the utility generates temperature-uncertainty fields from a dedicated field specification"
        ),
        "rod3Dmaker assets provide the mesh fixture without an OFFBEAT solverDict": (
            "a three-dimensional rod mesh supplies the fixture without running an OFFBEAT solve"
        ),
        "contains gasPressures reference file and gasPressure.py": (
            "reference gas-pressure data and an analytical pressure calculation are included"
        ),
        "Allrun checks Cs release fraction 0.225066 and executes sampleDict": (
            "the verified Cs release fraction is 0.225066 and a radial concentration profile is sampled"
        ),
        "Allrun extends the prescribed history to 8.712e7 s and performs a second cumulative-release solve": (
            "the prescribed history extends to 8.712e7 s and a second cumulative-release calculation is performed"
        ),
        "Allrun decomposes the mesh, executes runParallel offbeat and reconstructs the result": (
            "the parallel calculation decomposes the mesh, runs OFFBEAT and reconstructs the result"
        ),
        "Allrun edits system/userParameters before executing the fuel-rod fixture": (
            "the regression changes the user-parameter dictionary before running the fuel-rod fixture"
        ),
        "README identifies case IV of the Su and Zhou tapered-beam analysis": (
            "the setup reproduces Case IV of the Su and Zhou tapered-beam analysis"
        ),
        "README identifies pseudo-PUZRY separate-effect burst-test tutorial": (
            "the setup is a pseudo-PUZRY separate-effect burst-test tutorial"
        ),
        "README describes UO2 solid cylindrical pellet with 7-hour irradiation power ramp": (
            "a solid cylindrical UO2 pellet follows a seven-hour irradiation power ramp"
        ),
        "README results include porosity conductivity power density and temperature radial plots": (
            "reported radial results include porosity, conductivity, power density and temperature"
        ),
        "README derives creep_rate and creep_strain analytical check": (
            "analytical creep-rate and creep-strain values provide the verification reference"
        ),
        "the README defines a one-element Cartesian heating test from 673.15 K to 1673.15 K": (
            "a one-element Cartesian body is heated from 673.15 K to 1673.15 K"
        ),
        "the README defines a one-dimensional spherical analytical displacement comparison": (
            "the case provides a one-dimensional spherical analytical displacement comparison"
        ),
        "the README compares radial and tangential PyC swelling strain with BISON": (
            "radial and tangential PyC swelling strains are compared with BISON"
        ),
        "MonolithicSiCCreepModel is checked against the README analytical creep strain": (
            "MonolithicSiCCreepModel is checked against the analytical creep-strain reference"
        ),
        "sampleDict samples E and nu": (
            "radial sampling records Young's modulus and Poisson's ratio"
        ),
        "2D_or_1D_reduced geometry generated by system/blockMeshDict": (
            "the mesh represents a two-dimensional r-theta cross-section"
        ),
        "porosityTransportDynMesh uses updateMesh on in porosityOptions": (
            "the porosity-transport model enables moving-mesh updates"
        ),
        "compared_analytical.ods reference": "an analytical solution provides the reference",
        "fieldAverage outputs epsilonCreep components": (
            "volume-averaged creep-strain components are recorded"
        ),
        "globalOptions angularFraction 0.25 with cladding fuel writeMaterialProperties regions": (
            "a quarter-circle angular domain contains cladding and fuel regions with material properties"
        ),
        (
            "lhrTimes and lhrValues define a sharp RIA pulse from about 1.196 to 1.214 s "
            "while system pressure stays at 101325 Pa"
        ): (
            "a sharp RIA linear-heat-rate pulse spans about 1.196 to 1.214 s while system "
            "pressure stays at 101325 Pa"
        ),
        "calculateEnthalpy is true and enthalpyVolAverage records the enthalpy field": (
            "coolant-enthalpy calculation is enabled and its volume average is recorded"
        ),
        "controlDict patch probes include Tcoolant heatFlux enthalpyCoolant": (
            "recorded patch quantities include coolant temperature, wall heat flux and coolant enthalpy"
        ),
        "sphereDict enables SiC only with IPyC false and OPyC false": (
            "the spherical coating stack contains only the SiC layer, without IPyC or OPyC"
        ),
        "sphereDict enables IPyC only with SiC false and OPyC false": (
            "the spherical coating stack contains only the IPyC layer, without SiC or OPyC"
        ),
        "sphereDict enables IPyC and SiC with OPyC false": (
            "the spherical coating stack contains IPyC and SiC without OPyC"
        ),
        "rodDict builds ten discrete pellets with dish geometry and sliceMapper=byPellets": (
            "the geometry contains ten discrete dished pellets with sliceMapper=byPellets"
        ),
        "rodDict geometryType 2Dsmeared fuel rod template": (
            "the geometry is a two-dimensional smeared fuel-rod template"
        ),
        "rodDict uses geometryType 2Ddiscrete for the axisymmetric rodlet": (
            "the axisymmetric rodlet uses two-dimensional discrete-pellet geometry"
        ),
        "the rodDict geometry contains fuel and cladding regions with restart fields": (
            "the geometry contains fuel and cladding regions with restart fields"
        ),
        "damageModel isotropicCracking case uses 1D radial rodDict geometry": (
            "the isotropic-cracking case uses one-dimensional radial geometry"
        ),
        "mazars case uses 1D radial rodDict geometry": (
            "the Mazars case uses one-dimensional radial geometry"
        ),
    }
    value = exact_rewrites.get(value, value)

    replacements = (
        (r"^contains TRACE_([A-Za-z0-9]+)_Twall\.txt reference data$", r"TRACE supplies reference wall-temperature data for \1"),
        (r"^0/D applies ", "the displacement boundary condition applies "),
        (r"^static porosity case has 0/poreVelocity field$", "the static porosity case solves for pore velocity"),
        (r"^README describes ", "the case models "),
        (r"^README verifies ", "the benchmark verifies "),
        (r"^Allrun checks (.+?) against (.+)$", r"the verified reference for \1 is \2"),
        (r"^Allrun checks (.+)$", r"the verified results include \1"),
        (r"^Allrun compares ", "the benchmark compares "),
        (r"^Allrun advances two stages at ", "the staged calculation uses "),
        (r"^Allrun advances three stages at ", "the staged calculation uses "),
        (
            r"^Allrun advances (.+) stages and derives release from final remaining inventory$",
            r"the staged calculation uses \1 stages and derives release from final remaining inventory",
        ),
        (r"^Allrun enables ", "the second calculation enables "),
        (r"^solverDict runs ", "the transport model runs "),
        (r"^solverDict couples ", "the case couples "),
        (r"^solverDict activates ", "the model activates "),
        (
            r"^solverDict burnup fromPower, gapGas TRISO and fgr SCIANTIX$",
            "burnup is derived from power, with TRISO gap gas and SCIANTIX fission-gas release",
        ),
        (r"^solverDict gapGas none and fgr none$", "gap-gas and fission-gas-release models are disabled"),
        (r"^solverDict comment verifies variation of E with fluence$", "Young's modulus varies with neutron fluence"),
        (r"^sampleRadialProfile extracts ", "radial-profile sampling records "),
        (
            r"^sphereDict enables IPyC, SiC and OPyC with rKernel ([0-9.]+) um$",
            r"the spherical particle contains IPyC, SiC and OPyC around a \1 um kernel",
        ),
        (
            r"^uses chfTableDict, inletTemperature and systemPressure inputs$",
            "the coolant-channel inputs include a critical-heat-flux table, inlet temperature and system pressure",
        ),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)

    if SOURCE_LOCATOR.search(value):
        raise RebuildError(f"source locator leaked into retrieval feature: {value}")
    return " ".join(value.split())


def _sentence(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value


def _human(value: str) -> str:
    return value.replace("_", " ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_file_records(case_root: Path, *, input_only: bool) -> list[tuple[str, str, str]]:
    records: list[tuple[str, str, str]] = []
    for path in sorted(case_root.rglob("*")):
        if not (path.is_file() or path.is_symlink()):
            continue
        relative = path.relative_to(case_root).as_posix()
        parts = relative.split("/")
        is_input = parts[0] in {"0", "constant", "system"} or (
            len(parts) == 1
            and (
                parts[0].endswith("Dict")
                or parts[0]
                in {
                    "rodMaker",
                    "rodMaker.py",
                    "sphereMaker",
                    "sphereMaker.py",
                    "createBlockMeshDict.py",
                }
            )
        )
        if input_only and not is_input:
            continue
        if path.is_symlink():
            records.append((relative, "symlink", os.readlink(path)))
        else:
            records.append((relative, "file", _sha256(path)))
    return records


def _case_digest(case_root: Path, *, input_only: bool) -> str:
    payload = json.dumps(
        _case_file_records(case_root, input_only=input_only),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verified_files(case_root: Path, profile: Profile) -> list[dict[str, str]]:
    candidates = ["constant/solverDict", "Allrun"]
    if profile.family == "trisoFpDiffusion":
        candidates.append("0/T")
    if profile.family == "hydrogenTransport" and profile.child in {
        "heatingCooling1",
        "heatingCooling2",
    }:
        candidates.append("0/T")
    if profile.family == "multiMaterial":
        candidates.append("0/D")
    if profile.case_id == "actinidesRedistribution":
        candidates.append("system/sampleRadialProfile")
    if profile.case_id == "testBetaFraction":
        candidates.extend(["0/T", "system/probes"])
    if profile.case_id == "test_coolantChannel/generic_bwr_2D_RIA_stagnantFlow":
        candidates.extend(
            [
                "constant/lists/lhrTimes",
                "constant/lists/lhrValues",
                "constant/lists/systemPressure",
                "system/enthalpyVolAverage",
            ]
        )
    candidates.extend(["README", "README.md"])
    if profile.geometry_generator:
        candidates.append(profile.geometry_generator)
    if profile.case_id == "test_createTuFields":
        candidates.insert(0, "system/TuOFFBEATdict")
    result: list[dict[str, str]] = []
    for relative in _dedupe(candidates):
        path = case_root / relative
        if path.is_file():
            result.append({"path": relative, "sha256": _sha256(path)})
    return result


def _validate_historical_inputs(case_root: Path, profile: Profile) -> None:
    if not case_root.is_dir():
        raise RebuildError(f"official case path is missing: {profile.official_path}")
    # Solver dictionaries carry the physics identity.  Refuse to apply a legacy
    # semantic overlay if that input has changed since the evidence snapshot.
    solver = case_root / "constant/solverDict"
    expected = profile.historical_hashes.get("constant/solverDict")
    if solver.is_file() and expected:
        actual = f"sha256:{_sha256(solver)}"
        if actual != expected:
            raise RebuildError(
                f"solverDict drift for {profile.case_id}: {actual} != {expected}"
            )


def _build_card(
    old_card: dict[str, Any],
    profile: Profile,
    overlay: dict[str, Any] | None,
    family_overlay: dict[str, Any] | None,
    official_root: Path,
    revision: str,
) -> dict[str, Any]:
    if profile.official_path != old_card["card_path"]:
        raise RebuildError(
            f"card/profile path mismatch: {old_card['card_path']} != {profile.official_path}"
        )
    case_root = official_root / profile.official_path
    _validate_historical_inputs(case_root, profile)
    solver_path = case_root / "constant/solverDict"
    solver_text = solver_path.read_text(encoding="utf-8", errors="replace") if solver_path.is_file() else ""

    verified_override = VERIFIED_SEMANTIC_OVERRIDES.get(profile.case_id)
    if verified_override is not None:
        semantic = verified_override
        evidence_status = "verified_from_case_files"
        semantic_source = "official_case_files"
    elif overlay is not None:
        semantic = {
            "primary": overlay["purpose"]["primary"],
            "intents": overlay.get("supported_intents", []),
            "features": overlay.get("distinguishing_features", []),
            "not_for": overlay.get("not_for", []),
        }
        has_term_evidence = bool(overlay.get("review_evidence"))
        evidence_status = (
            "verified_from_reviewed_evidence"
            if has_term_evidence
            else "verified_from_case_files"
        )
        semantic_source = f"{revision}:{LEGACY_DATA}/curation/case_semantics.json"
    else:
        semantic = (
            _exercise_override(profile.case_id)
            if profile.family == "exerciseOFFBEAT"
            else DRAFT_OVERRIDES.get(profile.case_id)
        )
        if semantic is None:
            raise RebuildError(f"draft case has no rebuild override: {profile.case_id}")
        evidence_status = "verified_from_case_files"
        semantic_source = f"{revision}:{LEGACY_DATA}/cases/{_safe_case_dir(profile.case_id)}/semantic_profile.yaml"

    primary = str(semantic["primary"])
    intents = _dedupe(str(value) for value in semantic.get("intents", []))
    raw_features = _dedupe(
        _sanitize_phrase(str(value)) for value in semantic.get("features", [])
    )
    features = _dedupe(_naturalize_feature(value) for value in _positive_feature_clauses(raw_features))
    exclusions = _dedupe(_sanitize_phrase(str(value)) for value in semantic.get("not_for", []))
    if not features:
        raise RebuildError(f"case has no distinguishing evidence: {profile.case_id}")

    family_domain = ""
    if family_overlay:
        domain = family_overlay.get("domain", {})
        family_domain = str(domain.get("primary") or "")
    semantic_text = " ".join([primary, *intents, *features, family_domain])
    model_features = _model_features(profile, solver_text, primary, intents)
    geometry = _geometry_label(profile)
    labels = {
        "case_intent": _coarse_case_intent(profile, primary),
        "system_or_component": _component_labels(profile, semantic_text),
        "reactor_or_fuel_context": _context_labels(profile),
        "geometry": geometry,
        "physics_modules": _physics_labels(profile, primary, intents),
        "solver_or_model_features": model_features,
        "driving_condition": _driving_labels(profile, primary, intents),
        "output_targets": _output_labels(profile, primary, intents),
        "sibling_discriminator": f"{profile.family}:{primary}",
    }

    primary_human = _human(primary)
    intent_human = ", ".join(_human(value) for value in intents[:5])
    canonical = (
        f"{profile.case_id} is a {primary_human}. "
        f"{_sentence('; '.join(features))}."
    )
    summary = primary_human
    if intent_human:
        summary += f" covering {intent_human}"
    summary += f" in {geometry.replace('_', ' ')} geometry; {features[0]}."
    child = profile.child or profile.case_id
    if profile.family == profile.case_id and child == profile.case_id:
        sibling = f"{_sentence(primary_human)}; {features[-1]}."
    else:
        sibling = (
            f"{child} is the {primary_human} variant within {profile.family}; "
            f"{features[-1]}."
        )
    retrieval_parts = [
        f"{profile.case_id} — {primary_human}",
        f"Geometry: {geometry.replace('_', ' ')}",
        f"Scope: {intent_human}" if intent_human else "",
        _sentence("; ".join(features)),
    ]
    retrieval_text = ". ".join(part for part in retrieval_parts if part).rstrip(".") + "."

    return {
        "card_name": old_card["card_name"],
        "card_path": profile.official_path,
        "labels": labels,
        "description": {
            "canonical_profile": canonical,
            "retrieval_summary": summary,
            "sibling_discriminator": sibling,
        },
        "retrieval_text": retrieval_text,
        "do_not_use_for": [_human(value) for value in exclusions],
        "provenance": {
            "semantic_source": semantic_source,
            "review_status": evidence_status,
            "historical_case_sha256": profile.historical_case_hash.removeprefix("sha256:"),
            "official_case_tree_sha256": _case_digest(case_root, input_only=False),
            "official_case_input_sha256": _case_digest(case_root, input_only=True),
            "official_case_files": _verified_files(case_root, profile),
        },
    }


def rebuild(
    corpus_path: Path,
    official_root: Path,
    legacy_repository: Path,
    revision: str,
) -> dict[str, Any]:
    try:
        current = json.loads(corpus_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RebuildError(f"cannot read current corpus {corpus_path}: {exc}") from exc
    cards = current.get("cards")
    if not isinstance(cards, list) or len(cards) != 137:
        raise RebuildError("rebuild requires the current, de-duplicated 137-card path set")

    case_semantics = json.loads(
        _git_read(
            legacy_repository,
            revision,
            f"{LEGACY_DATA}/curation/case_semantics.json",
        )
    )["overlays"]
    family_semantics = json.loads(
        _git_read(
            legacy_repository,
            revision,
            f"{LEGACY_DATA}/curation/family_semantics.json",
        )
    )["overlays"]

    rebuilt_cards: list[dict[str, Any]] = []
    for old_card in cards:
        card_path = str(old_card["card_path"])
        case_id = _case_id_from_path(card_path)
        profile = _load_profile(legacy_repository, revision, case_id)
        rebuilt_cards.append(
            _build_card(
                old_card,
                profile,
                case_semantics.get(case_id),
                family_semantics.get(profile.family),
                official_root,
                revision,
            )
        )

    return {
        "schema_version": "offbeat_case_cards_compact_v2",
        "purpose": (
            "Compact, evidence-backed OFFBEAT case identities for candidate retrieval. "
            "Descriptions report case-local facts and exclusions; they do not select a case, "
            "define user targets, or authorize parameter inheritance."
        ),
        "total_cards": len(rebuilt_cards),
        "label_facets": LABEL_FACETS,
        "cards": rebuilt_cards,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument(
        "--official-root",
        type=Path,
        required=True,
        help="Root containing the read-only Cases directory",
    )
    parser.add_argument(
        "--legacy-repo",
        type=Path,
        required=True,
        help="MANDiFuel git repository containing the reviewed historical revision",
    )
    parser.add_argument("--legacy-revision", default=LEGACY_REVISION)
    parser.add_argument("--check", action="store_true", help="Compare generated bytes without writing")
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = rebuild(
        args.corpus.resolve(),
        args.official_root.resolve(),
        args.legacy_repo.resolve(),
        args.legacy_revision,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if args.corpus.read_text(encoding="utf-8") != rendered:
            raise RebuildError(f"generated corpus differs from {args.corpus}")
        print(f"rebuild check passed: {result['total_cards']} cards")
        return 0
    args.corpus.write_text(rendered, encoding="utf-8")
    print(f"rebuilt {result['total_cards']} cards at {args.corpus}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
