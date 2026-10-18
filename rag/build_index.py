#!/usr/bin/env python3
"""Build or verify the provider-backed OFFBEAT dual RAG index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from .providers import OpenAICompatibleClient, ProviderError
except ImportError:
    from providers import OpenAICompatibleClient, ProviderError  # type: ignore[no-redef]

SCHEMA_VERSION = "mandifuel-rag-index.v2"
EMBEDDING_SCHEMA_VERSION = "mandifuel-description-embeddings.v1"
TAXONOMY_SCHEMA_VERSION = "mandifuel-taxonomy-index.v1"
VOCABULARY_SCHEMA_VERSION = "mandifuel-taxonomy-vocabulary.v1"
ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = ROOT / "data" / "offbeat_case_cards_compact_138.json"
DEFAULT_INDEX = ROOT / "index"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v3"
DEFAULT_EMBEDDING_DIMENSION = 1024
LABEL_FACETS = (
    "case_intent",
    "system_or_component",
    "reactor_or_fuel_context",
    "geometry",
    "physics_modules",
    "solver_or_model_features",
    "driving_condition",
    "output_targets",
    "sibling_discriminator",
)


class BuildError(ValueError):
    """Raised when source data cannot produce a trustworthy dual index."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read JSON source {path}: {exc}") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        sort_keys=True,
    )
    return f"{rendered}\n".encode()


def label_values(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if str(item).strip()]


def validate_corpus(
    value: Any,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    if not isinstance(value, dict) or not isinstance(value.get("schema_version"), str):
        raise BuildError("corpus root and schema_version are required")
    facets = value.get("label_facets")
    if (
        not isinstance(facets, list)
        or not facets
        or not all(isinstance(item, str) and item.strip() for item in facets)
        or len(facets) != len(set(facets))
    ):
        raise BuildError("corpus label_facets must be unique non-empty strings")
    if facets != list(LABEL_FACETS):
        raise BuildError(
            "corpus label_facets do not match the supported semantic coordinate system"
        )
    cards = value.get("cards")
    if not isinstance(cards, list) or not cards:
        raise BuildError("corpus.cards must be a non-empty array")
    if value.get("total_cards") != len(cards):
        raise BuildError("corpus total_cards does not match cards")

    paths: set[str] = set()
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise BuildError(f"cards[{index}] must be an object")
        for key in (
            "card_name",
            "card_path",
            "labels",
            "description",
            "retrieval_text",
        ):
            if key not in card:
                raise BuildError(f"cards[{index}].{key} is required")
        card_path = card["card_path"]
        if (
            not isinstance(card_path, str)
            or not card_path.strip()
            or card_path in paths
            or card_path.startswith("/")
            or "\\" in card_path
            or ".." in Path(card_path).parts
        ):
            raise BuildError(f"cards[{index}].card_path is unsafe or duplicated")
        labels = card["labels"]
        if not isinstance(labels, dict) or set(labels) != set(facets):
            raise BuildError(
                f"cards[{index}].labels must contain exactly the declared label_facets"
            )
        retrieval_text = card["retrieval_text"]
        if not isinstance(retrieval_text, str) or not retrieval_text.strip():
            raise BuildError(f"cards[{index}].retrieval_text must be non-empty text")
        paths.add(card_path)
    return value, facets, cards


def _build_vocabulary(
    cards: list[dict[str, Any]], facets: list[str]
) -> dict[str, list[str]]:
    return {
        facet: sorted(
            {
                label
                for card in cards
                for label in label_values(card["labels"].get(facet))
            }
        )
        for facet in facets
    }


def _build_taxonomy(cards: list[dict[str, Any]], facets: list[str]) -> dict[str, Any]:
    facet_terms: dict[str, dict[str, list[str]]] = {}
    for facet in facets:
        labels: dict[str, list[str]] = {}
        for card in cards:
            for label in label_values(card["labels"].get(facet)):
                labels.setdefault(label, []).append(str(card["card_path"]))
        facet_terms[facet] = {
            label: sorted(paths) for label, paths in sorted(labels.items())
        }
    return {
        "schema_version": TAXONOMY_SCHEMA_VERSION,
        "facets": facets,
        "facet_terms": facet_terms,
    }


def _validate_vectors(
    cards: list[dict[str, Any]],
    vectors: dict[str, list[float]],
    dimension: int,
) -> None:
    expected_paths = {str(card["card_path"]) for card in cards}
    if set(vectors) != expected_paths:
        missing = sorted(expected_paths - set(vectors))
        extra = sorted(set(vectors) - expected_paths)
        raise BuildError(
            f"embedding paths differ from corpus; missing={missing[:3]}, extra={extra[:3]}"
        )
    for card_path, vector in vectors.items():
        if len(vector) != dimension:
            raise BuildError(
                f"embedding dimension mismatch for {card_path}: {len(vector)} != {dimension}"
            )


def _vectors_from_legacy(
    path: Path, cards: list[dict[str, Any]], dimension: int
) -> dict[str, list[float]]:
    root = _read_json(path)
    records = root.get("records") if isinstance(root, dict) else None
    if not isinstance(records, list):
        raise BuildError("legacy description index has no records")
    cards_by_path = {str(card["card_path"]): card for card in cards}
    vectors: dict[str, list[float]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise BuildError("legacy description record is invalid")
        card_path = str(record.get("card_path") or "")
        card = cards_by_path.get(card_path)
        if card is None or record.get("retrieval_text") != card["retrieval_text"]:
            raise BuildError(
                f"legacy description text differs from corpus: {card_path}"
            )
        embedding = record.get("embedding")
        if not isinstance(embedding, list):
            raise BuildError(f"legacy description vector is invalid: {card_path}")
        vectors[card_path] = [float(value) for value in embedding]
    _validate_vectors(cards, vectors, dimension)
    return vectors


def _vectors_from_existing(
    path: Path, cards: list[dict[str, Any]], model: str, dimension: int
) -> dict[str, list[float]]:
    root = _read_json(path)
    if (
        not isinstance(root, dict)
        or root.get("schema_version") != EMBEDDING_SCHEMA_VERSION
        or root.get("model") != model
        or root.get("dimension") != dimension
        or not isinstance(root.get("records"), list)
    ):
        raise BuildError("existing description embedding index is incompatible")
    cards_by_path = {str(card["card_path"]): card for card in cards}
    vectors: dict[str, list[float]] = {}
    for record in root["records"]:
        card_path = str(record.get("card_path") or "")
        card = cards_by_path.get(card_path)
        if card is None or record.get("retrieval_sha256") != _sha256_text(
            card["retrieval_text"]
        ):
            raise BuildError(
                "corpus retrieval text changed; rebuild with --refresh-embeddings"
            )
        embedding = record.get("embedding")
        if not isinstance(embedding, list):
            raise BuildError(f"existing description vector is invalid: {card_path}")
        vectors[card_path] = [float(value) for value in embedding]
    _validate_vectors(cards, vectors, dimension)
    return vectors


def _refresh_vectors(
    cards: list[dict[str, Any]],
    *,
    model: str,
    dimension: int,
    base_url: str,
    api_key: str | None,
    batch_size: int,
) -> dict[str, list[float]]:
    client = OpenAICompatibleClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        dimension=dimension,
        timeout_seconds=float(os.environ.get("MANDIFUEL_RAG_TIMEOUT_SECONDS", "120")),
    )
    vectors: dict[str, list[float]] = {}
    for start in range(0, len(cards), batch_size):
        batch = cards[start : start + batch_size]
        embedded = client.embed_texts([str(card["retrieval_text"]) for card in batch])
        for card, vector in zip(batch, embedded, strict=True):
            vectors[str(card["card_path"])] = vector
    _validate_vectors(cards, vectors, dimension)
    return vectors


def build_payloads(
    corpus_path: Path,
    *,
    vectors: dict[str, list[float]],
    embedding_model: str,
    embedding_dimension: int,
) -> dict[str, bytes]:
    corpus_root, facets, cards = validate_corpus(_read_json(corpus_path))
    _validate_vectors(cards, vectors, embedding_dimension)
    embedding_index = {
        "schema_version": EMBEDDING_SCHEMA_VERSION,
        "model": embedding_model,
        "dimension": embedding_dimension,
        "records": [
            {
                "card_path": card["card_path"],
                "retrieval_sha256": _sha256_text(card["retrieval_text"]),
                "embedding": vectors[str(card["card_path"])],
            }
            for card in cards
        ],
    }
    vocabulary = {
        "schema_version": VOCABULARY_SCHEMA_VERSION,
        "facets": facets,
        "labels": _build_vocabulary(cards, facets),
    }
    taxonomy = _build_taxonomy(cards, facets)
    payloads = {
        "description_embeddings.json": _json_bytes(embedding_index),
        "taxonomy_index.json": _json_bytes(taxonomy),
        "vocabulary.json": _json_bytes(vocabulary),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "card_count": len(cards),
        "source_schema_version": corpus_root["schema_version"],
        "label_facets": facets,
        "corpus": {
            "path": "../data/offbeat_case_cards_compact_138.json",
            "sha256": _sha256_bytes(corpus_path.read_bytes()),
        },
        "embedding": {
            "model": embedding_model,
            "dimension": embedding_dimension,
        },
        "outputs": {
            name: {"sha256": _sha256_bytes(content), "bytes": len(content)}
            for name, content in sorted(payloads.items())
        },
    }
    payloads["manifest.json"] = _json_bytes(manifest, pretty=True)
    return payloads


def write_index(payloads: dict[str, bytes], index_dir: Path) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    unexpected = sorted(
        path.name for path in index_dir.glob("*.json") if path.name not in set(payloads)
    )
    if unexpected:
        raise BuildError(f"unexpected generated index files: {', '.join(unexpected)}")
    for name, content in payloads.items():
        temporary = index_dir / f".{name}.tmp"
        temporary.write_bytes(content)
        temporary.replace(index_dir / name)


def check_index(payloads: dict[str, bytes], index_dir: Path) -> None:
    for name, expected in payloads.items():
        path = index_dir / name
        if not path.is_file() or path.read_bytes() != expected:
            raise BuildError(f"generated index is missing or stale: {path}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--legacy-description-index", type=Path)
    parser.add_argument("--refresh-embeddings", action="store_true")
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get(
            "MANDIFUEL_RAG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
        ),
    )
    parser.add_argument(
        "--embedding-dimension",
        type=int,
        default=int(
            os.environ.get(
                "MANDIFUEL_RAG_EMBEDDING_DIMENSION",
                str(DEFAULT_EMBEDDING_DIMENSION),
            )
        ),
    )
    parser.add_argument("--embedding-batch-size", type=int, default=10)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.legacy_description_index and args.refresh_embeddings:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "legacy import and embedding refresh are mutually exclusive",
                }
            ),
            file=sys.stderr,
        )
        return 2
    try:
        corpus_path = args.corpus.resolve()
        index_dir = args.index_dir.resolve()
        _, _, cards = validate_corpus(_read_json(corpus_path))
        if args.legacy_description_index:
            vectors = _vectors_from_legacy(
                args.legacy_description_index.resolve(),
                cards,
                args.embedding_dimension,
            )
        elif args.refresh_embeddings:
            key_name = os.environ.get(
                "MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV", "DASHSCOPE_API_KEY"
            )
            vectors = _refresh_vectors(
                cards,
                model=args.embedding_model,
                dimension=args.embedding_dimension,
                base_url=os.environ.get(
                    "MANDIFUEL_RAG_EMBEDDING_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ),
                api_key=os.environ.get(key_name),
                batch_size=max(1, args.embedding_batch_size),
            )
        else:
            vectors = _vectors_from_existing(
                index_dir / "description_embeddings.json",
                cards,
                args.embedding_model,
                args.embedding_dimension,
            )
        payloads = build_payloads(
            corpus_path,
            vectors=vectors,
            embedding_model=args.embedding_model,
            embedding_dimension=args.embedding_dimension,
        )
        if args.check:
            check_index(payloads, index_dir)
            action = "checked"
        else:
            write_index(payloads, index_dir)
            action = "built"
    except (BuildError, OSError, ProviderError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 1
    manifest = json.loads(payloads["manifest.json"])
    print(
        json.dumps(
            {
                "status": "ok",
                "action": action,
                "card_count": manifest["card_count"],
                "label_facet_count": len(manifest["label_facets"]),
                "embedding": manifest["embedding"],
                "index_dir": str(index_dir),
                "manifest_sha256": _sha256_bytes(payloads["manifest.json"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
