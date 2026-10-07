"""The embedding interface the application depends on, and the factory that picks one.

Adding a provider (e.g. Vertex AI) means: one new module implementing EmbeddingProvider, one new
branch below, and its settings in config.py. Nothing else changes.
"""

from typing import Protocol

from app.config import Settings
from app.embeddings.ollama import OllamaEmbeddingProvider


class EmbeddingProvider(Protocol):
    model_id: str
    """Names the vector space, e.g. 'ollama/nomic-embed-text'. Stored with every document so
    vectors from different models are never compared."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def check(self) -> str | None:
        """None when ready to embed, otherwise a short description of the problem."""
        ...


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    return OllamaEmbeddingProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embedding_model,
        dimension=settings.embedding_dimension,
        query_prefix=settings.ollama_query_prefix,
        document_prefix=settings.ollama_document_prefix,
    )
