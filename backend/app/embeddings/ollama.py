"""Embeddings from a local Ollama server (POST /api/embed)."""

import logging

import httpx

from app.errors import AppError

BATCH_SIZE = 32
log = logging.getLogger(__name__)


class OllamaEmbeddingProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        dimension: int,
        query_prefix: str = "",
        document_prefix: str = "",
        timeout: float = 120.0,  # the first call may wait for Ollama to load the model
    ) -> None:
        self.model = model
        self.model_id = f"ollama/{model}"
        self._dimension = dimension
        self._query_prefix = query_prefix
        self._document_prefix = document_prefix
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            vectors.extend(self._embed([self._document_prefix + text for text in batch]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self._query_prefix + text])[0]

    def check(self) -> str | None:
        try:
            response = self._client.get("/api/tags", timeout=3)
            response.raise_for_status()
        except httpx.HTTPError:
            return "Ollama isn't reachable. Start the Ollama app or run `ollama serve`."
        installed = {model["name"] for model in response.json().get("models", [])}
        if self.model not in installed and f"{self.model}:latest" not in installed:
            return f"Model '{self.model}' isn't installed. Run `ollama pull {self.model}`."
        return None

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []
        try:
            # truncate=False: an over-long input is an error, never silently embedded in part.
            response = self._client.post(
                "/api/embed", json={"model": self.model, "input": inputs, "truncate": False}
            )
        except httpx.TransportError as exc:
            log.error("ollama request failed", extra={"error": repr(exc)})
            raise AppError(
                "EMBEDDING_UNAVAILABLE",
                "The embedding service is unavailable. Please try again once it's running.",
                503,
            ) from exc
        if response.is_error:
            log.error(
                "ollama returned an error",
                extra={"status": response.status_code, "body": response.text[:500]},
            )
            raise AppError("EMBEDDING_FAILED", "The embedding service returned an error.", 502)

        vectors = response.json().get("embeddings") or []
        if len(vectors) != len(inputs) or any(len(v) != self._dimension for v in vectors):
            log.error(
                "unexpected embedding shape",
                extra={"expected_dimension": self._dimension, "count": len(vectors)},
            )
            raise AppError(
                "EMBEDDING_FAILED",
                "The embedding model returned vectors of an unexpected size.",
                502,
            )
        return vectors
