#!/usr/bin/env python3
"""Perform deterministic static audits of the compact OFFBEAT case corpus."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    from .build_index import validate_corpus
except ImportError:
    from build_index import validate_corpus  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = ROOT / "data" / "offbeat_case_cards_compact_138.json"
DEFAULT_INDEX = ROOT / "index"
LEGACY_DATA = "database/offbeat_card_rag/data"
LEGACY_REVISION = "8140fb3"
FORBIDDEN = re.compile(
    r"documented case facts|documented identity|taxonomy labels|"
    r"case-local evidence|distinguishing evidence|"
    r"\buse this case\b|\bchoose this case\b|\bbest used\b|"
    r"\buse when\b|\bselect only\b",
    re.IGNORECASE,
)
SOURCE_LOCATOR = re.compile(
    r"\b(?:README|Allrun|solverDict|controlDict|blockMeshDict|dynamicMeshDict|"
    r"sphereDict|rodDict|sampleDict|chfTableDict|porosityOptions|TuOFFBEATdict|"
    r"sampleRadialProfile|rod3Dmaker|fieldAverage|globalOptions|lhrTimes|lhrValues|"
    r"enthalpyVolAverage)\b|"
    r"\b(?:system|constant|0)/\S+|\b\S+\.(?:csv|dat|ods|py|txt|xlsx?)\b",
    re.IGNORECASE,
)
WEAK_PLACEHOLDER = re.compile(
    r"\bofficial\b|"
    r"\bspecific [^.]{0,80}\btest\b|"
    r"\b(?:generic )?bimaterial (?:block|cylinder|skew block) case [12]\b|"
    r"\b(?:decay chain fp diffusion variant|fp diffusion temperature profile case|"
    r"fp diffusion release fraction case) [0-9][a-z]\b",
    re.IGNORECASE,
)
VERIFIED_STATUSES = {
    "verified_from_case_files",
    "verified_from_reviewed_evidence",
}
INTENTIONAL_SHARED_INPUT = {
    frozenset(
        {
            "Cases/Verification/trisoFpDiffusion/case_4a",
            "Cases/Verification/trisoFpDiffusion/case_4b",
            "Cases/Verification/trisoFpDiffusion/case_4c",
        }
    )
}


class AuditError(RuntimeError):
    """Raised when one or more corpus invariants fail."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_records(case_root: Path, *, input_only: bool) -> list[tuple[str, str, str]]:
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
        digest = os.readlink(path) if path.is_symlink() else _sha256(path)
        records.append((relative, "symlink" if path.is_symlink() else "file", digest))
    return records


def _case_digest(case_root: Path, *, input_only: bool) -> str:
    payload = json.dumps(
        _case_records(case_root, input_only=input_only),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _duplicate_groups(
    cards: list[dict[str, Any]],
    provenance_key: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for card in cards:
        provenance = card.get("provenance")
        if isinstance(provenance, dict):
            digest = str(provenance.get(provenance_key, ""))
            if digest:
                groups[digest].append(str(card["card_path"]))
    return [
        {"sha256": digest, "paths": sorted(paths)}
        for digest, paths in sorted(groups.items())
        if len(paths) > 1
    ]


def _case_id_from_path(card_path: str) -> str:
    for prefix in ("Cases/Verification/", "Cases/testCases/", "Cases/restart/"):
        if card_path.startswith(prefix):
            return card_path[len(prefix) :]
    raise AuditError(f"unrecognized case path: {card_path}")


def _historical_case_hash(repository: Path, revision: str, card_path: str) -> str:
    case_id = _case_id_from_path(card_path)
    safe = case_id.replace("/", "__")
    relative = f"{LEGACY_DATA}/cases/{safe}/filesystem_profile.yaml"
    completed = subprocess.run(
        ["git", "-C", str(repository), "show", f"{revision}:{relative}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise AuditError(f"cannot read historical filesystem profile for {card_path}")
    match = re.search(r"^\s*case_hash:\s*sha256:([0-9a-f]{64})\s*$", completed.stdout, re.MULTILINE)
    if not match:
        raise AuditError(f"historical filesystem profile has no case_hash: {card_path}")
    return match.group(1)


def _positive_text(card: dict[str, Any]) -> str:
    return " ".join(
        [
            str(card["labels"]),
            str(card["description"]),
            str(card["retrieval_text"]),
        ]
    ).lower()


def _batch_name(index: int) -> str:
    if index <= 35:
        return "01_general_verification"
    if index <= 82:
        return "02_triso_families"
    if index <= 113:
        return "03_water_restart_damage_exercise"
    return "04_generic_and_remaining_tests"


def audit(
    corpus_path: Path,
    *,
    official_root: Path | None = None,
    legacy_repo: Path | None = None,
    legacy_revision: str = LEGACY_REVISION,
    index_dir: Path | None = None,
) -> dict[str, Any]:
    root = json.loads(corpus_path.read_text(encoding="utf-8"))
    _, _, cards = validate_corpus(root)
    errors: list[str] = []
    warnings: list[str] = []

    if len(cards) != 137:
        errors.append(f"expected 137 de-duplicated cards, found {len(cards)}")

    summaries = [str(card["description"].get("retrieval_summary", "")) for card in cards]
    retrievals = [str(card["retrieval_text"]) for card in cards]
    if len(set(summaries)) != len(summaries):
        duplicates = [value for value, count in collections.Counter(summaries).items() if count > 1]
        errors.append(f"duplicate retrieval summaries: {duplicates[:3]}")
    if len(set(retrievals)) != len(retrievals):
        errors.append("retrieval_text values are not unique")

    family_summaries: dict[str, set[str]] = collections.defaultdict(set)
    feature_counts: collections.Counter[str] = collections.Counter()
    batch_stats: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)

    for index, card in enumerate(cards):
        card_path = str(card["card_path"])
        description = card.get("description")
        provenance = card.get("provenance")
        if not isinstance(description, dict) or not all(
            isinstance(description.get(key), str) and description[key].strip()
            for key in ("canonical_profile", "retrieval_summary", "sibling_discriminator")
        ):
            errors.append(f"incomplete description: {card_path}")
            continue
        if FORBIDDEN.search(json.dumps(description, ensure_ascii=False)) or FORBIDDEN.search(
            str(card["retrieval_text"])
        ):
            errors.append(f"authorization/template phrase in retrieval prose: {card_path}")
        if "Excludes:" in str(card["retrieval_text"]):
            errors.append(f"negative terms leaked into embedding text: {card_path}")
        positive_prose = " ".join(
            [
                description["canonical_profile"],
                description["retrieval_summary"],
                description["sibling_discriminator"],
                str(card["retrieval_text"]),
            ]
        )
        if SOURCE_LOCATOR.search(positive_prose):
            errors.append(f"source locator leaked into retrieval prose: {card_path}")
        if re.search(r"\bnot\b|\brather than\b|\binstead of\b", positive_prose, re.IGNORECASE):
            errors.append(f"off-domain contrast leaked into positive prose: {card_path}")
        if WEAK_PLACEHOLDER.search(positive_prose):
            errors.append(f"weak placeholder description remains: {card_path}")
        if not isinstance(provenance, dict) or not provenance.get("review_status"):
            errors.append(f"missing provenance: {card_path}")
            continue
        if "uncertainties" in card:
            errors.append(f"formal card contains uncertainties metadata: {card_path}")
        if provenance["review_status"] not in VERIFIED_STATUSES:
            errors.append(f"unverified provenance status: {card_path}")
        for hash_key in (
            "historical_case_sha256",
            "official_case_tree_sha256",
            "official_case_input_sha256",
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get(hash_key, ""))):
                errors.append(f"missing or invalid {hash_key}: {card_path}")
        official_files = provenance.get("official_case_files")
        if not isinstance(official_files, list) or not official_files:
            errors.append(f"missing official case-file hashes: {card_path}")
        if "/home/" in json.dumps(provenance, ensure_ascii=False) or re.search(
            r'"\s*:\s*"/', json.dumps(provenance, ensure_ascii=False)
        ):
            errors.append(f"machine-absolute provenance leaked into corpus: {card_path}")

        discriminator = str(card["labels"]["sibling_discriminator"])
        if ":" not in discriminator:
            errors.append(f"invalid sibling discriminator: {card_path}")
            family = "invalid"
            primary = ""
        else:
            family, primary = discriminator.split(":", 1)
        if primary.replace("_", " ").lower() not in description["canonical_profile"].lower():
            errors.append(f"fine-grained purpose is inconsistent with description: {card_path}")
        family_summaries[family].add(description["retrieval_summary"])
        feature_counts.update(card["labels"]["solver_or_model_features"])
        batch = batch_stats[_batch_name(index)]
        batch["cards"] += 1
        batch[str(provenance["review_status"])] += 1

        if official_root is not None:
            case_root = official_root / card_path
            if not case_root.is_dir():
                errors.append(f"official case directory missing: {card_path}")
            for record in provenance.get("official_case_files", []):
                relative = str(record.get("path", ""))
                evidence_path = case_root / relative
                if not evidence_path.is_file():
                    errors.append(f"provenance file missing: {card_path}/{relative}")
                elif _sha256(evidence_path) != record.get("sha256"):
                    errors.append(f"provenance hash mismatch: {card_path}/{relative}")
            if case_root.is_dir():
                actual_tree = _case_digest(case_root, input_only=False)
                actual_input = _case_digest(case_root, input_only=True)
                if actual_tree != provenance.get("official_case_tree_sha256"):
                    errors.append(f"official tree hash mismatch: {card_path}")
                if actual_input != provenance.get("official_case_input_sha256"):
                    errors.append(f"official input hash mismatch: {card_path}")
        if legacy_repo is not None:
            historical_hash = _historical_case_hash(
                legacy_repo,
                legacy_revision,
                card_path,
            )
            if historical_hash != provenance.get("historical_case_sha256"):
                errors.append(f"historical case hash mismatch: {card_path}")

    by_path = {str(card["card_path"]): card for card in cards}
    historical_duplicate_groups = _duplicate_groups(cards, "historical_case_sha256")
    tree_duplicate_groups = _duplicate_groups(cards, "official_case_tree_sha256")
    input_duplicate_groups = _duplicate_groups(cards, "official_case_input_sha256")
    exact_duplicate_groups = [*historical_duplicate_groups, *tree_duplicate_groups]
    if exact_duplicate_groups:
        errors.append("exact duplicate cases remain in the formal corpus")

    intentional_input_groups: list[dict[str, Any]] = []
    unclassified_input_groups: list[dict[str, Any]] = []
    for group in input_duplicate_groups:
        paths = frozenset(str(path) for path in group["paths"])
        if paths in INTENTIONAL_SHARED_INPUT:
            allrun_by_path = {
                path: next(
                    record["sha256"]
                    for record in by_path[path]["provenance"]["official_case_files"]
                    if record["path"] == "Allrun"
                )
                for path in paths
            }
            intentional_input_groups.append(
                {
                    **group,
                    "differentiating_file": "Allrun",
                    "tree_differing_paths": ["Allrun"],
                    "differentiating_sha256": dict(sorted(allrun_by_path.items())),
                    "case_purposes": {
                        path: by_path[path]["description"]["retrieval_summary"]
                        for path in sorted(paths)
                    },
                }
            )
            if len(set(allrun_by_path.values())) != len(paths):
                errors.append("TRISO FP 4a/4b/4c shared inputs lack distinct Allrun evidence")
            if official_root is not None:
                tree_records = {
                    path: {
                        relative: (kind, digest)
                        for relative, kind, digest in _case_records(
                            official_root / path,
                            input_only=False,
                        )
                    }
                    for path in paths
                }
                relative_paths = set().union(*(records for records in tree_records.values()))
                differing_paths = sorted(
                    relative
                    for relative in relative_paths
                    if len({records.get(relative) for records in tree_records.values()}) > 1
                )
                if differing_paths != ["Allrun"]:
                    errors.append(
                        "TRISO FP 4a/4b/4c differ outside their intended Allrun scripts: "
                        f"{differing_paths}"
                    )
        else:
            unclassified_input_groups.append(group)
    if unclassified_input_groups:
        errors.append("unclassified cases share all key solver inputs")

    expected_geometry = {
        "Cases/testCases/generic_pwr_2D_rTheta": "2D_rTheta",
        "Cases/testCases/porosity/testCase2DrTheta": "2D_rTheta",
        "Cases/Verification/trisoModulesTest/testPyC_alpha_spherical": "1D_spherical",
        "Cases/Verification/trisoModulesTest/hollowsphere_1D": "1D_spherical",
        "Cases/Verification/trisoModulesTest/sphere_1D": "1D_spherical",
        "Cases/Verification/trisoModulesTest/sphere_vhgr": "1D_spherical",
    }
    for path, expected in expected_geometry.items():
        actual = by_path[path]["labels"]["geometry"]
        if actual != expected:
            errors.append(f"explicit case geometry changed: {path}: {actual!r} != {expected!r}")

    generic_mox = by_path["Cases/testCases/generic_mox_1D"]
    mox_context = generic_mox["labels"]["reactor_or_fuel_context"]
    if "MOX" not in mox_context or "fast_reactor" not in mox_context or "LWR" in mox_context:
        errors.append("generic_mox_1D lost its solver-declared MOX fast-reactor context")

    coarse_intents = collections.Counter(str(card["labels"]["case_intent"]) for card in cards)
    allowed_coarse_intents = {
        "verification_benchmark",
        "analytical_comparison",
        "code_comparison",
        "material_model_test",
        "exercise_case",
        "engineering_tutorial",
        "module_test",
        "restart_test",
        "solver_feature_test",
        "parameter_test",
    }
    if set(coarse_intents) - allowed_coarse_intents:
        errors.append(f"unsupported coarse case intents: {sorted(set(coarse_intents) - allowed_coarse_intents)}")
    if len(coarse_intents) > 10:
        errors.append(f"case_intent is not coarse-grained: {len(coarse_intents)} values")
    benchmark_cards = [
        card for path, card in by_path.items() if "/trisoBenchmarks/" in path
    ]
    diffusion_cards = [
        card for path, card in by_path.items() if "/trisoFpDiffusion/" in path
    ]
    for card in benchmark_cards:
        positive = _positive_text(card)
        if "fission_product_diffusion" in positive or "fpdiffusion" in positive:
            errors.append(f"TRISO mechanics/diffusion family mix-up: {card['card_path']}")
    for card in diffusion_cards:
        physics = card["labels"]["physics_modules"]
        features = card["labels"]["solver_or_model_features"]
        if "fission_product_diffusion" not in physics or "elementTransportSolver=FpDiffusion" not in features:
            errors.append(f"TRISO diffusion identity missing: {card['card_path']}")

    mechanics_4b = by_path.get("Cases/Verification/trisoBenchmarks/case_4b")
    diffusion_4b = by_path.get("Cases/Verification/trisoFpDiffusion/case_4b")
    if mechanics_4b:
        text = _positive_text(mechanics_4b)
        if "constantcreepprincipalstress" not in text or "creep no swelling" not in text:
            errors.append("trisoBenchmarks/case_4b lost its creep/no-swelling identity")
    if diffusion_4b and "fission_product_diffusion" not in _positive_text(diffusion_4b):
        errors.append("trisoFpDiffusion/case_4b lost its diffusion identity")

    for suffix in ("case_3c", "case_3d", "case_4a", "case_4b", "case_4c"):
        card = by_path[f"Cases/Verification/trisoFpDiffusion/{suffix}"]
        if any("stress" in target for target in card["labels"]["output_targets"]):
            errors.append(f"negative stress wording created an output label: {card['card_path']}")

    for card in diffusion_cards:
        if re.search(r"mechanic|stress|thermomechanical", card["retrieval_text"], re.IGNORECASE):
            errors.append(f"TRISO diffusion embedding contains off-domain mechanics: {card['card_path']}")
        if card["labels"]["physics_modules"] != ["fission_product_diffusion"]:
            errors.append(f"TRISO diffusion inherited a non-transport physics module: {card['card_path']}")
        if "temperature" in card["labels"]["output_targets"]:
            errors.append(f"prescribed TRISO FP temperature became an output: {card['card_path']}")
        if "release_fraction" not in card["labels"]["output_targets"]:
            errors.append(f"TRISO FP release benchmark lost its release output: {card['card_path']}")

    fp_expectations = {
        "case_1a": ("1473.15 K", "0.4673"),
        "case_1b": ("1873.15 K", "0.99999959"),
        "case_2a": ("1473.15 K", "0.0265125"),
        "case_2b": ("1873.15 K", "0.994653"),
        "case_3a": ("1873.15 K", "1.54447e-4"),
        "case_3b": ("2073.15 K", "0.210283"),
        "case_3c": ("2073.15 K", "0.225066"),
        "case_3d": ("SiC crackFpRelease", "0.999992"),
        "case_3e": ("IPyC and OPyC crackFpRelease", "checked against 1"),
        "case_4a": ("1273.15 K and 1873.15 K", "0.000235404 and 0.403467"),
        "case_4b": ("1273.15 K and 2073.15 K", "0.210138 and 0.862284"),
        "case_4c": ("1273.15 K, 1873.15 K and 2073.15 K", "0.223638 and 0.915856"),
        "case_4d": ("final remaining inventory", "0.999866 and 0.988044"),
        "case_5a": ("one uninterrupted run", "2.7116e-17 and 6.78835e-6"),
        "case_5b": ("8.712e7 s", "0.000315053 and 0.398419"),
    }
    for suffix, snippets in fp_expectations.items():
        text = by_path[f"Cases/Verification/trisoFpDiffusion/{suffix}"]["retrieval_text"]
        if any(snippet.lower() not in text.lower() for snippet in snippets):
            errors.append(f"TRISO FP purpose lacks case-specific Allrun evidence: {suffix}")

    fp_4b = by_path["Cases/Verification/trisoFpDiffusion/case_4b"]
    if set(fp_4b["labels"]["driving_condition"]) != {
        "temperature_history",
        "prescribed_temperature",
    }:
        errors.append("trisoFpDiffusion/case_4b lost its prescribed two-stage temperature input")

    multimat_expected = {
        "biMaterialBlock1": ("pressure_loading", "1 MPa pressure"),
        "biMaterialBlock2": ("traction_loading", "traction (0 1e6 0)"),
        "biMaterialCylinder1": ("pressure_loading", "1e7 Pa pressure"),
        "biMaterialCylinder1_frictionalContact": ("frictional_contact", "frictionCoefficient is 1e60"),
        "biMaterialCylinder2": ("torque_loading", "fixedTorque boundary with torque 1"),
        "biMaterialSkewBlock1": ("pressure_loading", "1 MPa pressure"),
        "biMaterialSkewBlock2": ("traction_loading", "traction (0 1e6 0)"),
    }
    for suffix, (driving, evidence) in multimat_expected.items():
        card = by_path[f"Cases/Verification/multiMaterial/{suffix}"]
        if driving not in card["labels"]["driving_condition"] or evidence not in card["retrieval_text"]:
            errors.append(f"multiMaterial loading identity changed: {suffix}")
    block2 = by_path["Cases/Verification/multiMaterial/biMaterialBlock2"]
    if "frictional_contact" in block2["labels"]["driving_condition"]:
        errors.append("biMaterialBlock2 was confused with the frictional cylinder")

    benchmark_7 = by_path["Cases/Verification/trisoBenchmarks/case_7"]
    if "thermal creep variant" in benchmark_7["retrieval_text"].lower() or not all(
        value in benchmark_7["retrieval_text"]
        for value in ("1.0e8 s", "3.95923e7 Pa", "9.0048e6 Pa")
    ):
        errors.append("trisoBenchmarks/case_7 lost its long-irradiation swelling identity")

    for suffix, values in {
        "case_10": ("2.487393346e9", "6.56211e6", "-1.7035e8"),
        "case_11": ("3.561803753e9", "3.19538e7", "-8.42427e7"),
    }.items():
        text = by_path[f"Cases/Verification/trisoBenchmarks/{suffix}"]["retrieval_text"]
        if any(value not in text for value in values):
            errors.append(f"trisoBenchmarks/{suffix} lost its power/flux benchmark identity")

    beta = by_path["Cases/Verification/testBetaFraction"]
    if "neutronics" in beta["labels"]["physics_modules"] or set(beta["labels"]["output_targets"]) != {
        "beta_phase_fraction",
        "temperature",
    }:
        errors.append("testBetaFraction was confused with delayed-neutron beta")
    if not {"thermal_conduction", "material_phase_transformation"}.issubset(
        beta["labels"]["physics_modules"]
    ):
        errors.append("testBetaFraction lost its thermal phase-transformation identity")

    porosity_rtheta = by_path["Cases/testCases/porosity/testCase2DrTheta"]
    if "neutronics" in porosity_rtheta["labels"]["physics_modules"]:
        errors.append("porosity r-theta cross section was confused with neutronics")
    hydrogen_ingress = by_path["Cases/Verification/hydrogenTransport/hydrogenIngress"]
    if "coolant_heat_transfer" in hydrogen_ingress["labels"]["physics_modules"]:
        errors.append("hydrogen ingress from coolant was confused with coolant heat transfer")

    for path in ("Cases/testCases/generic_pwr_1D", "Cases/testCases/generic_mox_1D"):
        card = by_path[path]
        if not {"thermal_conduction", "solid_mechanics"}.issubset(card["labels"]["physics_modules"]):
            errors.append(f"fuel-rod thermomechanics lost coupled thermal/mechanics physics: {path}")
        if not {"temperature", "stress_or_strain", "rod_internal_pressure"}.issubset(
            card["labels"]["output_targets"]
        ):
            errors.append(f"fuel-rod thermomechanics lost resolved outputs: {path}")

    generic_triso = by_path["Cases/testCases/generic_TRISO_1D"]
    if not {"thermal_conduction", "solid_mechanics"}.issubset(
        generic_triso["labels"]["physics_modules"]
    ) or not {"temperature", "stress_or_strain", "particle_internal_pressure"}.issubset(
        generic_triso["labels"]["output_targets"]
    ):
        errors.append("generic TRISO template lost thermomechanics/particle-pressure outputs")

    for path in (
        "Cases/Verification/corrosion/fixedInnerHeatFlux",
        "Cases/Verification/corrosion/fixedInterfaceTemperature",
    ):
        if "oxide_thickness" not in by_path[path]["labels"]["output_targets"]:
            errors.append(f"corrosion case lost oxide-thickness output: {path}")

    for suffix in ("case6", "case6_solved"):
        exercise = by_path[f"Cases/testCases/exerciseOFFBEAT/{suffix}"]
        if "fission_gas_release" not in exercise["labels"]["output_targets"]:
            errors.append(f"exercise {suffix} lost its SCIANTIX FGR output")

    for path, card in by_path.items():
        outputs = card["labels"]["output_targets"]
        ambiguous = {
            "gas_or_contact_pressure",
            "coolant_or_wall_temperature",
            "stress_or_displacement",
        }.intersection(outputs)
        if ambiguous:
            errors.append(f"ambiguous output label remains on {path}: {sorted(ambiguous)}")

    for path, card in by_path.items():
        features = card["labels"]["solver_or_model_features"]
        if "elementTransport=byList" in features:
            errors.append(f"generic byList dispatcher remains a model feature: {path}")
        if "neutronicsSolver=diffusion" in features:
            errors.append(f"background diffusion solver remains a model feature: {path}")
        if "burnup=Lassmann" in features:
            errors.append(f"generic Lassmann burnup scaffolding remains: {path}")
        if "LimbackCreepModel" in features and "cladding creep" not in _positive_text(card):
            errors.append(f"Limback creep feature is unrelated to case purpose: {path}")

    sodium_analytical = by_path["Cases/Verification/NaCoolantChannelModel/vsAnalytical"]
    if re.search(r"\bTRACE\b", sodium_analytical["retrieval_text"], re.IGNORECASE):
        errors.append("Na analytical embedding contains the TRACE sibling")

    enrichment = by_path[
        "Cases/Verification/neutronics/cylindricalPellet/testDifferentEnrichments/baseCase"
    ]
    radius = by_path[
        "Cases/Verification/neutronics/cylindricalPellet/testDifferentRadii/baseCase"
    ]
    if re.search(r"\bradi(?:us|i)\b", enrichment["retrieval_text"], re.IGNORECASE):
        errors.append("enrichment-sweep embedding contains the radius sibling")
    if re.search(r"\benrichment\b", radius["retrieval_text"], re.IGNORECASE):
        errors.append("radius-sweep embedding contains the enrichment sibling")

    coolant_temperature = by_path[
        "Cases/testCases/test_coolantChannel/generic_pwr_1D_coolantTemperature"
    ]
    if re.search(r"\benthalpy\b", coolant_temperature["retrieval_text"], re.IGNORECASE):
        errors.append("coolant-temperature embedding contains the enthalpy sibling")

    laser = by_path["Cases/Verification/laserHeating"]
    if laser["labels"]["physics_modules"] != ["thermal_conduction"]:
        errors.append("laserHeating inherited non-thermal physics from negative prose")
    if laser["labels"]["output_targets"] != ["temperature"]:
        errors.append("laserHeating inherited a non-temperature output from substring matching")
    if "temperature_history" in laser["labels"]["driving_condition"]:
        errors.append("laserHeating was confused with a prescribed temperature history")

    plate = by_path["Cases/Verification/plateHole"]
    if "species_concentration" in plate["labels"]["output_targets"]:
        errors.append("plateHole stress concentration was confused with species concentration")
    if "gas_or_contact_pressure" in plate["labels"]["output_targets"]:
        errors.append("plateHole pressure loading was confused with gas/contact pressure output")
    if "pressure_loading" not in plate["labels"]["driving_condition"]:
        errors.append("plateHole lost its pressure-loading condition")

    for path, card in by_path.items():
        if "/neutronics/" in path and "species_concentration" in card["labels"]["output_targets"]:
            errors.append(f"neutronics diffusion was confused with species transport: {path}")

    enthalpy_cards = [
        card
        for path, card in by_path.items()
        if "enthalpyModel" in path
    ]
    for card in enthalpy_cards:
        if "coolant_enthalpy" not in card["labels"]["output_targets"]:
            errors.append(f"coolant enthalpy identity was collapsed: {card['card_path']}")

    if coolant_temperature["labels"]["output_targets"] != ["coolant_temperature"]:
        errors.append("coolant-temperature case does not expose a specific coolant-temperature output")

    ria = by_path["Cases/testCases/test_coolantChannel/generic_bwr_2D_RIA_stagnantFlow"]
    if "coolant_mass_flow" in ria["labels"]["driving_condition"]:
        errors.append("stagnant-flow RIA case inherited a coolant mass-flow condition")
    if not {"transient_linear_heat_rate", "RIA_power_pulse", "constant_pressure"}.issubset(
        ria["labels"]["driving_condition"]
    ) or not {"coolant_enthalpy", "coolant_temperature"}.issubset(
        ria["labels"]["output_targets"]
    ):
        errors.append("stagnant-flow RIA case lost its pulse/pressure/enthalpy identity")

    for path, card in by_path.items():
        if "/waterCoolantChannel/" in path:
            if set(card["labels"]["output_targets"]) != {"wall_temperature", "TRACE_deviation"}:
                errors.append(f"TRACE comparison has non-wall-temperature outputs: {path}")

    actinides = by_path["Cases/Verification/actinidesRedistribution"]
    if "actinide_form_factor" not in actinides["labels"]["output_targets"] or not all(
        value in actinides["retrieval_text"]
        for value in ("AmRedistribution", "PuRedistribution", "PuFormFactor", "AmFormFactor")
    ):
        errors.append("actinidesRedistribution lost its Am/Pu radial form-factor identity")

    beam = by_path.get("Cases/Verification/beamBending")
    if beam:
        if beam["labels"]["system_or_component"] != ["structural_solid"]:
            errors.append("beamBending is not classified as a structural solid")
        if beam["labels"]["reactor_or_fuel_context"]:
            errors.append("beamBending carries an unsupported fuel/reactor context")

    if official_root is not None:
        benchmark_solver = (
            official_root
            / "Cases/Verification/trisoBenchmarks/case_4b/constant/solverDict"
        ).read_text(encoding="utf-8", errors="replace")
        diffusion_solver = (
            official_root
            / "Cases/Verification/trisoFpDiffusion/case_4b/constant/solverDict"
        ).read_text(encoding="utf-8", errors="replace")
        if not re.search(r"\belementTransport\s+fromLatestTime\s*;", benchmark_solver):
            errors.append("official trisoBenchmarks/case_4b elementTransport evidence changed")
        if "constantCreepPrincipalStress" not in benchmark_solver:
            errors.append("official trisoBenchmarks/case_4b creep evidence changed")
        if "FpDiffusion" not in diffusion_solver:
            errors.append("official trisoFpDiffusion/case_4b diffusion evidence changed")

        fp_allrun_tokens = {
            "case_1a": ("CsExpected=0.4673",),
            "case_1b": ("CsExpected=0.99999959",),
            "case_2a": ("CsExpected=0.0265125",),
            "case_2b": ("CsExpected=0.994653",),
            "case_3a": ("CsExpected=1.54447e-4",),
            "case_3b": ("CsExpected=0.210283",),
            "case_3c": ("CsExpected=0.225066", "sampleDict"),
            "case_3d": ("crackFpRelease -set true", "CsExpected=0.999992"),
            "case_3e": ("crackFpRelease -set true", "CsExpected=1", "KrExpected=1"),
            "case_4a": ('new_value="1873.15"', "CsExpected=0.000235404", "AgExpected=0.403467"),
            "case_4b": ('new_value="2073.15"', "CsExpected=0.210138", "AgExpected=0.862284"),
            "case_4c": ('new_value1="1873.15"', 'new_value2="2073.15"', "CsExpected=0.223638", "AgExpected=0.915856"),
            "case_4d": ('new_value1="1873.15"', 'new_value2="2073.15"', "CsExpected=0.999866", "AgExpected=0.988044"),
            "case_5a": ("CsExpected=2.7116e-17", "AgExpected=6.78835e-06"),
            "case_5b": ("endTime -set 8.712e7", "CsExpected=0.000315053", "AgExpected=0.398419"),
        }
        for suffix, tokens in fp_allrun_tokens.items():
            allrun = (
                official_root / f"Cases/Verification/trisoFpDiffusion/{suffix}/Allrun"
            ).read_text(encoding="utf-8", errors="replace")
            if any(token not in allrun for token in tokens):
                errors.append(f"official TRISO FP Allrun evidence changed: {suffix}")

        beta_allrun = (
            official_root / "Cases/Verification/testBetaFraction/Allrun"
        ).read_text(encoding="utf-8", errors="replace")
        if not all(value in beta_allrun for value in ("Massih model", "0.401681", "900) (50 1400) (100 900")):
            errors.append("official testBetaFraction phase-transition evidence changed")

        block2_displacement = (
            official_root / "Cases/Verification/multiMaterial/biMaterialBlock2/0/D"
        ).read_text(encoding="utf-8", errors="replace")
        cylinder2_displacement = (
            official_root / "Cases/Verification/multiMaterial/biMaterialCylinder2/0/D"
        ).read_text(encoding="utf-8", errors="replace")
        if "traction        uniform (0 1e6 0)" not in block2_displacement:
            errors.append("official biMaterialBlock2 shear-traction evidence changed")
        if not re.search(r"\btype\s+fixedTorque\s*;", cylinder2_displacement):
            errors.append("official biMaterialCylinder2 torque evidence changed")

        ria_root = official_root / "Cases/testCases/test_coolantChannel/generic_bwr_2D_RIA_stagnantFlow"
        ria_solver = (ria_root / "constant/solverDict").read_text(
            encoding="utf-8", errors="replace"
        )
        ria_pressure = (ria_root / "constant/lists/systemPressure").read_text(
            encoding="utf-8", errors="replace"
        )
        if "calculateEnthalpy   true" not in ria_solver or "101325" not in ria_pressure:
            errors.append("official stagnant-flow RIA enthalpy/pressure evidence changed")

        mox_solver = (
            official_root
            / "Cases/testCases/generic_mox_1D/constant/solverDict"
        ).read_text(encoding="utf-8", errors="replace")
        if not re.search(r'\breactorType\s+"FBR"\s*;', mox_solver):
            errors.append("official generic_mox_1D FBR evidence changed")

        spherical_readme = (
            official_root
            / "Cases/Verification/trisoModulesTest/testPyC_alpha_spherical/README"
        ).read_text(encoding="utf-8", errors="replace")
        if not re.search(r"\b1-d spherical case\b", spherical_readme, re.IGNORECASE):
            errors.append("official spherical module geometry evidence changed")

    index_status: dict[str, Any] = {"checked": False}
    if index_dir is not None:
        index_status = {"checked": True, "fresh": False}
        manifest_path = index_dir / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            recorded = manifest.get("corpus", {}).get("sha256")
            actual = _sha256(corpus_path)
            index_status.update({"recorded_corpus_sha256": recorded, "actual_corpus_sha256": actual})
            index_status["fresh"] = recorded == actual
            if recorded != actual:
                warnings.append("embedding/index manifest is stale after corpus rebuild")
        else:
            warnings.append("index manifest is missing")

    status_counts = collections.Counter(
        card["provenance"]["review_status"] for card in cards if isinstance(card.get("provenance"), dict)
    )
    report = {
        "status": "failed" if errors else "ok",
        "card_count": len(cards),
        "unique_retrieval_summaries": len(set(summaries)),
        "unique_retrieval_texts": len(set(retrievals)),
        "family_count": len(family_summaries),
        "coarse_case_intents": dict(sorted(coarse_intents.items())),
        "review_status": dict(sorted(status_counts.items())),
        "max_solver_feature_frequency": max(feature_counts.values(), default=0),
        "duplicate_audit": {
            "historical_source_checked": legacy_repo is not None,
            "historical_case_hash_groups": historical_duplicate_groups,
            "current_full_tree_hash_groups": tree_duplicate_groups,
            "exact_duplicate_groups": exact_duplicate_groups,
            "shared_key_input_groups": input_duplicate_groups,
            "intentional_variant_groups": intentional_input_groups,
            "unclassified_shared_input_groups": unclassified_input_groups,
        },
        "batches": {name: dict(values) for name, values in sorted(batch_stats.items())},
        "index": index_status,
        "warnings": warnings,
        "errors": errors,
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--official-root", type=Path)
    parser.add_argument("--legacy-repo", type=Path)
    parser.add_argument("--legacy-revision", default=LEGACY_REVISION)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = audit(
        args.corpus.resolve(),
        official_root=args.official_root.resolve() if args.official_root else None,
        legacy_repo=args.legacy_repo.resolve() if args.legacy_repo else None,
        legacy_revision=args.legacy_revision,
        index_dir=args.index_dir.resolve() if args.index_dir else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        raise AuditError(f"case-card audit found {len(report['errors'])} errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
