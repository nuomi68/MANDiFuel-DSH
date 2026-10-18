"""Provider and cache primitives for the Skill-owned RAG interface."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class ProviderError(RuntimeError):
    """Raised when a configured semantic provider cannot return valid data."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256_text(payload)


class JsonCache:
    """Small atomic JSON cache shared by concurrent RAG queries."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self._counter_lock = threading.Lock()

    def get(self, namespace: str, key: str) -> Any | None:
        path = self._path(namespace, key)
        if not path.is_file():
            with self._counter_lock:
                self.misses += 1
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError(
                f"RAG cache record is unreadable: {path}: {exc}"
            ) from exc
        with self._counter_lock:
            self.hits += 1
        return value

    def set(self, namespace: str, key: str, value: Any) -> None:
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        )
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(path)
        with self._counter_lock:
            self.writes += 1

    def summary(self) -> dict[str, int]:
        with self._counter_lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "writes": self.writes,
            }

    def _path(self, namespace: str, key: str) -> Path:
        return self.root / namespace.replace("/", "_") / f"{key}.json"


class OpenAICompatibleClient:
    """Minimal standard-library client for chat JSON and text embeddings."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_seconds: float = 120.0,
        dimension: int | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = float(timeout_seconds)
        self.dimension = dimension

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        response = self._post(
            "chat/completions",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "mapping provider response has no message content"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("mapping provider returned empty content")
        return content

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }
        if self.dimension is not None:
            payload["dimensions"] = self.dimension
        response = self._post("embeddings", payload)
        records = response.get("data") if isinstance(response, dict) else None
        if not isinstance(records, list) or len(records) != len(texts):
            raise ProviderError(
                "embedding provider returned an unexpected record count"
            )
        ordered = sorted(records, key=lambda item: int(item.get("index", 0)))
        vectors: list[list[float]] = []
        for record in ordered:
            embedding = record.get("embedding") if isinstance(record, dict) else None
            if not isinstance(embedding, list):
                raise ProviderError("embedding provider returned an invalid vector")
            vector = [float(value) for value in embedding]
            if self.dimension is not None and len(vector) != self.dimension:
                raise ProviderError(
                    f"embedding dimension mismatch: expected {self.dimension}, got {len(vector)}"
                )
            vectors.append(vector)
        return vectors

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError(f"API key is unavailable for model {self.model}")
        request = urllib.request.Request(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise ProviderError(
                f"provider HTTP {exc.code} for model {self.model}: "
                f"{self._redact(detail)}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(
                f"provider request failed for model {self.model}: {exc}"
            ) from exc
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("provider returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ProviderError("provider returned a non-object JSON response")
        return value

    def _redact(self, message: str) -> str:
        if self.api_key:
            return message.replace(self.api_key, "[REDACTED]")
        return message
