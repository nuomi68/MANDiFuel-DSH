#!/usr/bin/env python3
"""Retrieve OFFBEAT case cards with embedding and taxonomy indexes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Protocol

try:
    from .build_index import (
        EMBEDDING_SCHEMA_VERSION,
        LABEL_FACETS,
        SCHEMA_VERSION,
        TAXONOMY_SCHEMA_VERSION,
        VOCABULARY_SCHEMA_VERSION,
        validate_corpus,
    )
    from .providers import (
        JsonCache,
        OpenAICompatibleClient,
        ProviderError,
        sha256_text,
        stable_json_hash,
    )
except ImportError:
    from build_index import (  # type: ignore[no-redef]
        EMBEDDING_SCHEMA_VERSION,
        LABEL_FACETS,
        SCHEMA_VERSION,
        TAXONOMY_SCHEMA_VERSION,
        VOCABULARY_SCHEMA_VERSION,
        validate_corpus,
    )
    from providers import (  # type: ignore[no-redef]
        JsonCache,
        OpenAICompatibleClient,
        ProviderError,
        sha256_text,
        stable_json_hash,
    )

ROOT = Path(__file__).resolve().parent
DEFAULT_INDEX = ROOT / "index"
DEFAULT_CORPUS = ROOT / "data" / "offbeat_case_cards_compact_138.json"
MAX_QUERY_CHARS = 16_000
CONFIDENCE_THRESHOLD = 0.5
EMBEDDING_WEIGHT = 0.35
TAXONOMY_WEIGHT = 0.65
QUERY_MAPPING_CACHE_SCHEMA_VERSION = "offbeat-query-mapping-cache.1"
QUERY_MAPPER_PROMPT_VERSION = "offbeat-query-mapper-prompt.3"
QUERY_MAPPER_SCHEMA_VERSION = "offbeat-query-mapper-schema.1"
EMBEDDING_CACHE_SCHEMA_VERSION = "offbeat-embedding-cache.1"
CJK_RE = re.compile(r"[\u3400-\u9fff]")
FACET_WEIGHTS = {
    "case_intent": 0.08,
    "system_or_component": 0.14,
    "reactor_or_fuel_context": 0.10,
    "geometry": 0.12,
    "physics_modules": 0.18,
    "solver_or_model_features": 0.06,
    "driving_condition": 0.10,
    "output_targets": 0.12,
    "sibling_discriminator": 0.20,
}
COVERAGE_FACETS = ("geometry",)

SYSTEM_PROMPT = """You map a user query to an existing OFFBEAT case-card taxonomy.

Use only the provided taxonomy vocabulary.
Do not invent new labels.
If no label fits a facet, return null for that facet.
If a facet is ambiguous, return null for that facet.
case_intent describes the purpose of a suitable source case. The user's plan
to sweep parameters or optimize a design does not by itself mean that the source
must be a parameter_test or verification_benchmark. Leave this facet null unless
the request establishes a source-case purpose.
Map explicitly requested coupled physics compositionally using the supported
core module labels. Do not select a narrow catalog-family physics label solely
because the user's component name overlaps with that label.
Treat every facet as an independent semantic coordinate. Map a label only when
the request explicitly supports that concept in the same facet. Do not infer a
physics module from requested outputs, geometry, component, or reactor context.
Do not infer a sibling discriminator from geometry or any other engineering
facet; map it only when the request explicitly states that catalog identity or
variant distinction.
If the user query is Chinese or mixed Chinese-English, also return a fluent English
translation in translated_query_for_embedding and use an English sentence for
query_rewrite_for_embedding.
For any non-English query, query_rewrite_for_embedding must be suitable for embedding
against English OFFBEAT case descriptions.
Return strict JSON only.
"""


class QueryError(ValueError):
    """Raised when retrieval inputs or generated indexes cannot be trusted."""


class MappingProvider(Protocol):
    base_url: str
    model: str

    def complete_json(self, system_prompt: str, user_prompt: str) -> str: ...


class EmbeddingProvider(Protocol):
    base_url: str
    model: str
    dimension: int | None

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QueryError(f"cannot read JSON file {path}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise QueryError(f"cannot read index evidence {path}: {exc}") from exc


def _label_values(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if str(item).strip()]


def _mapping_schema(facets: list[str]) -> dict[str, Any]:
    return {
        "mapped_labels": {facet: None for facet in facets},
        "confidence": {facet: 0.0 for facet in facets},
        "overall_confidence": 0.0,
        "query_language": "unknown",
        "translated_query_for_embedding": None,
        "query_rewrite_for_embedding": "English retrieval rewrite of the user query",
        "unmapped_terms": [],
    }


def _contains_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text or ""))


def _build_user_prompt(
    query_text: str,
    vocabulary: dict[str, list[str]],
    facets: list[str],
) -> str:
    language_hint = (
        "The query contains Chinese. Return translated_query_for_embedding as a fluent English sentence. "
        "Use that English meaning, not the original Chinese text, for query_rewrite_for_embedding.\n"
        if _contains_cjk(query_text)
        else ""
    )
    return (
        "Map the user query to the allowed OFFBEAT taxonomy labels.\n"
        "Allowed labels are grouped by facet. Use exact label strings only.\n"
        "For list-like matches, return an array of existing label strings. For one match, return a string.\n"
        "Ignore labels that are not useful for retrieval. Use null for ambiguous or absent facets.\n"
        f"{language_hint}"
        "Return exactly this JSON shape, with numeric confidence values from 0 to 1:\n"
        f"{json.dumps(_mapping_schema(facets), ensure_ascii=False, indent=2)}\n\n"
        f"User query:\n{query_text}\n\n"
        "Allowed taxonomy vocabulary:\n"
        f"{json.dumps(vocabulary, ensure_ascii=False, indent=2)}"
    )


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    return match.group(1).strip() if match else stripped


def _validate_mapping(
    raw: Any,
    query_text: str,
    vocabulary: dict[str, list[str]],
    facets: list[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise QueryError("mapping provider returned a non-object JSON value")
    result = _mapping_schema(facets)
    allowed = {facet: set(values) for facet, values in vocabulary.items()}
    raw_mapped = raw.get("mapped_labels", {})
    raw_confidence = raw.get("confidence", {})
    if not isinstance(raw_mapped, dict):
        raw_mapped = {}
    if not isinstance(raw_confidence, dict):
        raw_confidence = {}

    for facet in facets:
        valid_values = [
            value
            for value in _label_values(raw_mapped.get(facet))
            if value in allowed.get(facet, set())
        ]
        if not valid_values:
            result["mapped_labels"][facet] = None
        elif len(valid_values) == 1:
            result["mapped_labels"][facet] = valid_values[0]
        else:
            result["mapped_labels"][facet] = list(dict.fromkeys(valid_values))
        try:
            confidence = float(raw_confidence.get(facet, 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        result["confidence"][facet] = max(0.0, min(confidence, 1.0))

    try:
        overall = float(raw.get("overall_confidence", 0.0))
    except (TypeError, ValueError):
        overall = 0.0
    result["overall_confidence"] = max(0.0, min(overall, 1.0))

    language = str(raw.get("query_language") or "").strip().lower()
    result["query_language"] = (
        language
        if language in {"en", "zh", "mixed", "unknown"}
        else "zh"
        if _contains_cjk(query_text)
        else "en"
    )
    translated = raw.get("translated_query_for_embedding")
    translated_text = str(translated).strip() if translated else None
    rewrite = raw.get("query_rewrite_for_embedding") or translated_text
    rewrite_text = str(rewrite).strip() if rewrite else query_text
    result["translated_query_for_embedding"] = translated_text or (
        rewrite_text
        if _contains_cjk(query_text) and rewrite_text != query_text
        else None
    )
    result["query_rewrite_for_embedding"] = rewrite_text
    unmapped = raw.get("unmapped_terms", [])
    result["unmapped_terms"] = (
        [str(term) for term in unmapped]
        if isinstance(unmapped, list)
        else [str(unmapped)]
    )
    return result


def _provider_identity(
    provider: MappingProvider | EmbeddingProvider,
    *,
    compatible_provider_name: str,
) -> dict[str, Any]:
    dimension = getattr(provider, "dimension", None)
    return {
        "provider": compatible_provider_name,
        "model": str(getattr(provider, "model", None) or "unspecified"),
        "dimension": int(dimension) if dimension is not None else None,
        "base_url": str(getattr(provider, "base_url", None) or "unspecified"),
    }


def _map_query(
    query_text: str,
    *,
    provider: MappingProvider,
    vocabulary: dict[str, list[str]],
    facets: list[str],
    cache: JsonCache,
) -> tuple[dict[str, Any], dict[str, Any]]:
    provider_identity = _provider_identity(
        provider,
        compatible_provider_name="rag.providers.OpenAICompatibleClient.chat",
    )
    schema = _mapping_schema(facets)
    identity = {
        "cache_schema_version": QUERY_MAPPING_CACHE_SCHEMA_VERSION,
        "provider": provider_identity,
        "prompt_version": QUERY_MAPPER_PROMPT_VERSION,
        "prompt_sha256": sha256_text(SYSTEM_PROMPT),
        "mapping_schema_version": QUERY_MAPPER_SCHEMA_VERSION,
        "mapping_schema_sha256": stable_json_hash(schema),
    }
    fingerprint = stable_json_hash(identity)
    namespace = f"query_mappings_{fingerprint}"
    vocabulary_hash = stable_json_hash(vocabulary)
    key = sha256_text(f"{fingerprint}\n{query_text}\n{vocabulary_hash}")
    query_hash = sha256_text(query_text)
    telemetry = {
        "operation": "query_mapping",
        "source": "cache_hit",
        "provider_request_performed": False,
        "provider": provider_identity,
        "cache_namespace": namespace,
        "cache_key_sha256": key,
        "input_sha256": query_hash,
    }
    cached = cache.get(namespace, key)
    if cached is not None:
        if not isinstance(cached, dict) or "mapping" not in cached:
            raise QueryError("cached query mapping is invalid")
        return (
            _validate_mapping(cached["mapping"], query_text, vocabulary, facets),
            telemetry,
        )

    telemetry["source"] = "realtime_provider_request"
    telemetry["provider_request_performed"] = True
    content = provider.complete_json(
        SYSTEM_PROMPT,
        _build_user_prompt(query_text, vocabulary, facets),
    )
    try:
        parsed = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise ProviderError("mapping provider returned invalid JSON") from exc
    mapping = _validate_mapping(parsed, query_text, vocabulary, facets)
    cache.set(
        namespace,
        key,
        {
            "cache_identity": identity,
            "query_sha256": query_hash,
            "vocabulary_hash": vocabulary_hash,
            "mapping": mapping,
        },
    )
    return mapping, telemetry


def _embed_query(
    text: str,
    *,
    provider: EmbeddingProvider,
    cache: JsonCache,
) -> tuple[list[float], dict[str, Any]]:
    provider_identity = _provider_identity(
        provider,
        compatible_provider_name="rag.providers.OpenAICompatibleClient.embeddings",
    )
    identity = {
        "schema_version": EMBEDDING_CACHE_SCHEMA_VERSION,
        "provider": provider_identity,
    }
    fingerprint = stable_json_hash(identity)
    namespace = f"embeddings_{fingerprint}"
    text_hash = sha256_text(text)
    key = sha256_text(f"{fingerprint}\n{text_hash}")
    telemetry = {
        "operation": "query_embedding",
        "source": "cache_hit",
        "provider_request_performed": False,
        "provider": provider_identity,
        "cache_namespace": namespace,
        "cache_key_sha256": key,
        "input_sha256": text_hash,
    }
    cached = cache.get(namespace, key)
    if cached is not None:
        if not isinstance(cached, dict) or not isinstance(
            cached.get("embedding"), list
        ):
            raise QueryError("cached query embedding is invalid")
        return [float(value) for value in cached["embedding"]], telemetry

    telemetry["source"] = "realtime_provider_request"
    telemetry["provider_request_performed"] = True
    vectors = provider.embed_texts([text])
    if len(vectors) != 1:
        raise ProviderError("embedding provider returned an unexpected record count")
    embedding = [float(value) for value in vectors[0]]
    cache.set(
        namespace,
        key,
        {
            "cache_identity": identity,
            "text_sha256": text_hash,
            "embedding": embedding,
        },
    )
    return embedding, telemetry


def _validate_index(
    index_dir: Path,
    corpus_path: Path,
) -> tuple[
    list[str],
    list[dict[str, Any]],
    dict[str, list[str]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    manifest_path = index_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != SCHEMA_VERSION
    ):
        raise QueryError("RAG manifest schema is unsupported; rebuild the index")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise QueryError("RAG manifest output evidence is missing")
    for name in (
        "description_embeddings.json",
        "taxonomy_index.json",
        "vocabulary.json",
    ):
        evidence = outputs.get(name)
        path = index_dir / name
        if (
            not isinstance(evidence, dict)
            or evidence.get("sha256") != _sha256_file(path)
            or evidence.get("bytes") != path.stat().st_size
        ):
            raise QueryError(f"RAG index output changed or is missing: {name}")
    corpus_evidence = manifest.get("corpus")
    if not isinstance(corpus_evidence, dict) or corpus_evidence.get(
        "sha256"
    ) != _sha256_file(corpus_path):
        raise QueryError("RAG corpus changed; rebuild the index")

    _, facets, cards = validate_corpus(_read_json(corpus_path))
    if facets != list(LABEL_FACETS) or facets != list(FACET_WEIGHTS):
        raise QueryError(
            "RAG label facets do not match the supported semantic coordinate system"
        )
    if (
        manifest.get("card_count") != len(cards)
        or manifest.get("label_facets") != facets
    ):
        raise QueryError("RAG manifest and corpus disagree")
    vocabulary_root = _read_json(index_dir / "vocabulary.json")
    taxonomy = _read_json(index_dir / "taxonomy_index.json")
    descriptions = _read_json(index_dir / "description_embeddings.json")
    if (
        not isinstance(vocabulary_root, dict)
        or vocabulary_root.get("schema_version") != VOCABULARY_SCHEMA_VERSION
        or vocabulary_root.get("facets") != facets
        or not isinstance(vocabulary_root.get("labels"), dict)
    ):
        raise QueryError("RAG taxonomy vocabulary is invalid")
    if (
        not isinstance(taxonomy, dict)
        or taxonomy.get("schema_version") != TAXONOMY_SCHEMA_VERSION
        or taxonomy.get("facets") != facets
        or not isinstance(taxonomy.get("facet_terms"), dict)
    ):
        raise QueryError("RAG taxonomy index is invalid")
    embedding = manifest.get("embedding")
    if (
        not isinstance(embedding, dict)
        or not isinstance(descriptions, dict)
        or descriptions.get("schema_version") != EMBEDDING_SCHEMA_VERSION
        or descriptions.get("model") != embedding.get("model")
        or descriptions.get("dimension") != embedding.get("dimension")
        or not isinstance(descriptions.get("records"), list)
        or len(descriptions["records"]) != len(cards)
    ):
        raise QueryError("RAG description embedding index is invalid")
    return (
        facets,
        cards,
        vocabulary_root["labels"],
        taxonomy,
        descriptions,
        manifest,
    )


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise QueryError(f"embedding dimensions differ: {len(left)} != {len(right)}")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    low = min(scores.values())
    high = max(scores.values())
    if high == low:
        value = 1.0 if high > 0 else 0.0
        return {key: value for key in scores}
    return {key: (value - low) / (high - low) for key, value in scores.items()}


def _embedding_scores(
    description_index: dict[str, Any], query_embedding: list[float]
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for record in description_index["records"]:
        if not isinstance(record, dict) or not isinstance(
            record.get("embedding"), list
        ):
            raise QueryError("RAG description embedding record is invalid")
        card_path = str(record.get("card_path") or "")
        if not card_path or card_path in scores:
            raise QueryError("RAG description embedding card path is invalid")
        scores[card_path] = _cosine(
            query_embedding,
            [float(value) for value in record["embedding"]],
        )
    return _normalize_scores(scores)


def _taxonomy_scores(
    taxonomy: dict[str, Any],
    mapping: dict[str, Any],
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    mapped_labels = mapping.get("mapped_labels", {})
    confidence = mapping.get("confidence", {})
    raw_scores: dict[str, float] = {}
    matched: dict[str, dict[str, list[str]]] = {}
    accepted_facet_weight = 0.0
    terms = taxonomy["facet_terms"]
    for facet, weight in FACET_WEIGHTS.items():
        values = list(dict.fromkeys(_label_values(mapped_labels.get(facet))))
        try:
            facet_confidence = float(confidence.get(facet, 0.0))
        except (TypeError, ValueError):
            facet_confidence = 0.0
        if not values or facet_confidence < CONFIDENCE_THRESHOLD:
            continue
        facet_terms = terms.get(facet, {})
        if not isinstance(facet_terms, dict):
            raise QueryError(f"RAG taxonomy facet is invalid: {facet}")
        valid_values = [
            value
            for value in values
            if isinstance(facet_terms.get(value), list) and facet_terms.get(value)
        ]
        if not valid_values:
            continue
        effective_weight = weight * facet_confidence
        accepted_facet_weight += effective_weight
        facet_matches: dict[str, list[str]] = {}
        for value in valid_values:
            paths = facet_terms.get(value, [])
            for card_path_value in paths:
                card_path = str(card_path_value)
                labels = facet_matches.setdefault(card_path, [])
                if value not in labels:
                    labels.append(value)
        for card_path, labels in facet_matches.items():
            match_fraction = len(labels) / len(valid_values)
            raw_scores[card_path] = raw_scores.get(card_path, 0.0) + (
                effective_weight * match_fraction
            )
            matched.setdefault(card_path, {})[facet] = labels
    if not raw_scores:
        return {}, {}
    denominator = accepted_facet_weight or max(raw_scores.values()) or 1.0
    normalized = {
        path: min(score / denominator, 1.0) for path, score in raw_scores.items()
    }
    simplified = {
        path: {
            facet: values[0] if len(values) == 1 else values
            for facet, values in facets.items()
        }
        for path, facets in matched.items()
    }
    return normalized, simplified


def _rank_with_facet_coverage(
    ranked_paths: list[str],
    *,
    limit: int,
    cards_by_path: dict[str, dict[str, Any]],
    mapping: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    """Keep score order while reserving room for requested fidelity geometries."""
    mapped_labels = mapping.get("mapped_labels", {})
    confidence = mapping.get("confidence", {})
    required_paths: list[str] = []
    requested: dict[str, list[str]] = {}
    promoted: list[dict[str, str]] = []

    for facet in COVERAGE_FACETS:
        values = list(dict.fromkeys(_label_values(mapped_labels.get(facet))))
        try:
            facet_confidence = float(confidence.get(facet, 0.0))
        except (TypeError, ValueError):
            facet_confidence = 0.0
        if len(values) < 2 or facet_confidence < CONFIDENCE_THRESHOLD:
            continue
        requested[facet] = values
        if len(values) > limit:
            continue
        per_label_limit = 2 if 2 * len(values) <= limit else 1
        for value in values:
            matching_paths = [
                candidate_path
                for candidate_path in ranked_paths
                if value
                in _label_values(
                    cards_by_path[candidate_path].get("labels", {}).get(facet)
                )
            ][:per_label_limit]
            for path in matching_paths:
                if path not in required_paths:
                    required_paths.append(path)
                    promoted.append({"facet": facet, "label": value, "card_path": path})

    selected = set(required_paths)
    for path in ranked_paths:
        if len(selected) >= limit:
            break
        selected.add(path)
    selected_paths = [path for path in ranked_paths if path in selected][:limit]
    score_only_paths = set(ranked_paths[:limit])
    promoted = [item for item in promoted if item["card_path"] not in score_only_paths]
    covered = {
        facet: [
            value
            for value in values
            if any(
                value in _label_values(cards_by_path[path].get("labels", {}).get(facet))
                for path in selected_paths
            )
        ]
        for facet, values in requested.items()
    }
    return selected_paths, {
        "facets": list(COVERAGE_FACETS),
        "requested_labels": requested,
        "covered_labels": covered,
        "promoted": promoted,
    }


def _resolved_reference(
    card_path: str, case_library_root: Path | None
) -> dict[str, Any]:
    if case_library_root is None:
        return {
            "card_path": card_path,
            "case_library_root": None,
            "resolved_path": None,
            "available": False,
        }
    root = case_library_root.expanduser().resolve()
    candidate = (root / card_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise QueryError(f"card path escapes case-library root: {card_path}") from exc
    return {
        "card_path": card_path,
        "case_library_root": str(root),
        "resolved_path": str(candidate),
        "available": candidate.is_dir(),
    }


def _default_cache_dir() -> Path:
    configured = os.environ.get("MANDIFUEL_RAG_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    return ROOT.parent / ".cache" / "rag"


def _default_clients(
    *, embedding_model: str, embedding_dimension: int
) -> tuple[OpenAICompatibleClient, OpenAICompatibleClient]:
    timeout = float(os.environ.get("MANDIFUEL_RAG_TIMEOUT_SECONDS", "120"))
    mapping_key_name = os.environ.get(
        "MANDIFUEL_RAG_MAPPING_API_KEY_ENV", "DEEPSEEK_API_KEY"
    )
    embedding_key_name = os.environ.get(
        "MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV", "DASHSCOPE_API_KEY"
    )
    mapping = OpenAICompatibleClient(
        base_url=os.environ.get(
            "MANDIFUEL_RAG_MAPPING_BASE_URL", "https://api.deepseek.com"
        ),
        model=os.environ.get("MANDIFUEL_RAG_MAPPING_MODEL", "deepseek-chat"),
        api_key=os.environ.get(mapping_key_name)
        or os.environ.get("DSH_MANDIFUEL_MAPPING_API_KEY"),
        timeout_seconds=timeout,
    )
    embedding = OpenAICompatibleClient(
        base_url=os.environ.get(
            "MANDIFUEL_RAG_EMBEDDING_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        model=os.environ.get("MANDIFUEL_RAG_EMBEDDING_MODEL", embedding_model),
        api_key=os.environ.get(embedding_key_name)
        or os.environ.get("DSH_MANDIFUEL_EMBEDDING_API_KEY"),
        timeout_seconds=timeout,
        dimension=int(
            os.environ.get(
                "MANDIFUEL_RAG_EMBEDDING_DIMENSION", str(embedding_dimension)
            )
        ),
    )
    return mapping, embedding


def query(
    engineering_request: str,
    *,
    limit: int = 5,
    index_dir: Path = DEFAULT_INDEX,
    corpus_path: Path = DEFAULT_CORPUS,
    cache_dir: Path | None = None,
    case_library_root: Path | None = None,
    mapping_provider: MappingProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    include_ablation_rankings: bool = False,
) -> dict[str, Any]:
    """Run both semantic branches and return ranked card evidence."""
    if (
        not isinstance(engineering_request, str)
        or not engineering_request.strip()
        or "\x00" in engineering_request
        or len(engineering_request) > MAX_QUERY_CHARS
    ):
        raise QueryError(
            f"query must contain 1 to {MAX_QUERY_CHARS} characters without NUL"
        )
    if not 1 <= limit <= 20:
        raise QueryError("limit must be between 1 and 20")

    index_path = index_dir.resolve()
    corpus = corpus_path.resolve()
    facets, cards, vocabulary, taxonomy, descriptions, manifest = _validate_index(
        index_path, corpus
    )
    embedding_contract = manifest["embedding"]
    default_mapping, default_embedding = _default_clients(
        embedding_model=str(embedding_contract["model"]),
        embedding_dimension=int(embedding_contract["dimension"]),
    )
    mapper = mapping_provider or default_mapping
    embedder = embedding_provider or default_embedding
    if (
        str(getattr(embedder, "model", "")) != embedding_contract["model"]
        or int(getattr(embedder, "dimension", 0) or 0)
        != embedding_contract["dimension"]
    ):
        raise QueryError("query embedding provider does not match the bundled index")

    cache = JsonCache((cache_dir or _default_cache_dir()).resolve())
    mapping, mapping_trace = _map_query(
        engineering_request,
        provider=mapper,
        vocabulary=vocabulary,
        facets=facets,
        cache=cache,
    )
    embedding_query = str(
        mapping.get("query_rewrite_for_embedding") or engineering_request
    )
    query_embedding, embedding_trace = _embed_query(
        embedding_query,
        provider=embedder,
        cache=cache,
    )
    if len(query_embedding) != int(embedding_contract["dimension"]):
        raise QueryError("query embedding dimension does not match the bundled index")

    embedding_scores = _embedding_scores(descriptions, query_embedding)
    taxonomy_scores, matched_labels = _taxonomy_scores(taxonomy, mapping)
    final_scores = {
        path: EMBEDDING_WEIGHT * embedding_scores.get(path, 0.0)
        + TAXONOMY_WEIGHT * taxonomy_scores.get(path, 0.0)
        for path in set(embedding_scores) | set(taxonomy_scores)
    }
    cards_by_path = {str(card["card_path"]): card for card in cards}
    if set(final_scores) != set(cards_by_path):
        raise QueryError("RAG indexes and corpus contain different card paths")
    score_ranked_paths = sorted(
        final_scores,
        key=lambda path: (
            final_scores[path],
            embedding_scores.get(path, 0.0),
            taxonomy_scores.get(path, 0.0),
            path,
        ),
        reverse=True,
    )
    ranked_paths, coverage = _rank_with_facet_coverage(
        score_ranked_paths,
        limit=limit,
        cards_by_path=cards_by_path,
        mapping=mapping,
    )
    ablation_rankings: dict[str, list[str]] | None = None
    if include_ablation_rankings:
        embedding_only = sorted(
            cards_by_path,
            key=lambda path: (-embedding_scores.get(path, 0.0), path),
        )[:limit]
        coordinates_only = sorted(
            cards_by_path,
            key=lambda path: (-taxonomy_scores.get(path, 0.0), path),
        )[:limit]
        ablation_rankings = {
            "embedding_only": embedding_only,
            "semantic_coordinates_only": coordinates_only,
            "fused": ranked_paths,
        }
    candidates: list[dict[str, Any]] = []
    for rank, card_path in enumerate(ranked_paths, start=1):
        card = cards_by_path[card_path]
        description = card.get("description", {})
        candidates.append(
            {
                "rank": rank,
                "score": round(final_scores[card_path], 6),
                "score_components": {
                    "embedding": round(embedding_scores.get(card_path, 0.0), 6),
                    "taxonomy": round(taxonomy_scores.get(card_path, 0.0), 6),
                },
                "card_name": card.get("card_name"),
                "card_path": card_path,
                "labels": card.get("labels"),
                "matched_labels": matched_labels.get(card_path, {}),
                "retrieval_summary": (
                    description.get("retrieval_summary")
                    if isinstance(description, dict)
                    else None
                ),
                "sibling_discriminator": (
                    description.get("sibling_discriminator")
                    if isinstance(description, dict)
                    else None
                ),
                "do_not_use_for": card.get("do_not_use_for", []),
                "input_card_reference": _resolved_reference(
                    card_path, case_library_root
                ),
            }
        )

    result = {
        "status": "ok",
        "interface": "mandifuel-rag-query.v2",
        "engineering_request": engineering_request,
        "embedding_query": embedding_query,
        "query_mapping": mapping,
        "candidate_count": len(candidates),
        "corpus_card_count": len(cards),
        "fusion": {
            "strategy": "fixed_taxonomy_heavy_with_mapped_geometry_coverage",
            "embedding_weight": EMBEDDING_WEIGHT,
            "taxonomy_weight": TAXONOMY_WEIGHT,
            "coverage": coverage,
        },
        "provider_telemetry": {
            "mapping": mapping_trace,
            "embedding": embedding_trace,
            "cache": cache.summary(),
        },
        "index_evidence": {
            "manifest_sha256": _sha256_file(index_path / "manifest.json"),
            "corpus_sha256": manifest["corpus"]["sha256"],
            "embedding": embedding_contract,
            "label_facets": facets,
        },
        "evidence_scope": "ranked_case_cards_only",
        "candidates": candidates,
        "warnings": [
            "Ranking is retrieval evidence, not an engineering suitability decision.",
            "Inspect labels and do_not_use_for before choosing a card.",
            "A card reference is not runnable until its resolved directory is inspected.",
        ],
    }
    if ablation_rankings is not None:
        result["ablation_rankings"] = ablation_rankings
        result["ablation_scope"] = {
            "embedding_only": "mapped-rewrite embedding score",
            "semantic_coordinates_only": "taxonomy score with path-only tie breaking",
            "fused": "production fusion including mapped-geometry coverage",
        }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query")
    source.add_argument("--query-file", type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--cache-dir", type=Path, default=_default_cache_dir())
    parser.add_argument(
        "--case-library-root",
        type=Path,
        default=(
            Path(os.environ["MANDIFUEL_CASE_LIBRARY_ROOT"])
            if os.environ.get("MANDIFUEL_CASE_LIBRARY_ROOT")
            else None
        ),
    )
    parser.add_argument("--compact", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        request = (
            args.query_file.read_text(encoding="utf-8")
            if args.query_file is not None
            else args.query
        )
        result = query(
            request,
            limit=args.limit,
            index_dir=args.index_dir,
            corpus_path=args.corpus,
            cache_dir=args.cache_dir,
            case_library_root=args.case_library_root,
        )
    except (OSError, QueryError, ProviderError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "interface": "mandifuel-rag-query.v2",
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if args.compact else 2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
