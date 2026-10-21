import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from backend.app.core.config import settings
from backend.app.integrations.embeddings.base import (
    EmbeddingProvider,
    EmbeddingProviderUnconfiguredError,
)
from backend.app.integrations.embeddings.openai_provider import OpenAIEmbeddingProvider
from backend.app.integrations.embeddings.mock_provider import MockEmbeddingProvider
from backend.app.integrations.embeddings.ollama_provider import OllamaEmbeddingProvider
from backend.app.models.code_chunk import CodeChunk

logger = logging.getLogger(__name__)


def get_embedding_provider(provider_type: Optional[str] = None) -> EmbeddingProvider:
    """Factory to retrieve the configured EmbeddingProvider."""
    target_type = (provider_type or settings.EMBEDDING_PROVIDER or settings.AI_PROVIDER or "ollama").lower()

    if target_type == "mock":
        return MockEmbeddingProvider(dimension=settings.EMBEDDING_DIMENSION)
    elif target_type == "ollama":
        return OllamaEmbeddingProvider(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.EMBEDDING_MODEL,
            dimension=settings.EMBEDDING_DIMENSION,
            timeout_seconds=settings.EMBEDDING_TIMEOUT_SECONDS,
        )
    elif target_type in ("openai", "azure"):
        return OpenAIEmbeddingProvider(
            api_key=settings.EMBEDDING_API_KEY,
            model=settings.EMBEDDING_MODEL,
            dimension=settings.EMBEDDING_DIMENSION,
            base_url=settings.EMBEDDING_BASE_URL,
        )
    else:
        # Default to Ollama provider instance
        return OllamaEmbeddingProvider()


from backend.app.integrations.llm.service import get_llm_provider
from backend.app.db.session import get_db_diagnostics


class EmbeddingService:
    @classmethod
    def get_status(cls, db: Optional[Session] = None) -> Dict[str, Any]:
        """Provides truthful diagnostic report on embedding configuration and database vector counts."""
        provider = get_embedding_provider()
        status = provider.get_configuration_status()

        total_chunks = 0
        embedded_chunks = 0
        if db is not None:
            try:
                total_chunks = db.query(CodeChunk).count()
                embedded_chunks = db.query(CodeChunk).filter(CodeChunk.embedding.isnot(None)).count()
            except Exception as e:
                logger.debug(f"Unable to query chunk counts: {e}")

        # LLM diagnostics
        llm_provider = get_llm_provider()
        llm_status = llm_provider.get_configuration_status()

        # Database diagnostics
        db_diag = get_db_diagnostics()

        status["total_chunks"] = total_chunks
        status["embedded_chunks"] = embedded_chunks
        status["unembedded_chunks"] = max(0, total_chunks - embedded_chunks)
        status["service_available"] = status.get("service_available", False)
        status["model_available"] = status.get("model_available", False)
        status["verified_dimension"] = status.get("verified_dimension")
        status["llm_provider"] = llm_provider.provider_name
        status["llm_model"] = llm_provider.model_name
        status["llm_service_available"] = llm_status.get("service_available", False)
        status["llm_model_available"] = llm_status.get("model_available", False)
        status["database_connected"] = db_diag.get("connected", False)
        status["pgvector_available"] = db_diag.get("pgvector_available", False)
        return status

    @classmethod
    async def embed_new_chunks(
        cls,
        db: Session,
        chunks: List[CodeChunk],
        provider: Optional[EmbeddingProvider] = None,
        repository_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Embeds newly created or modified CodeChunks using persisted chunk primary keys.
        Ensures repository scoping to prevent cross-repository corruption or data leakage.
        Reuses existing embeddings for matching content hashes and models to prevent duplicate API spend.
        Handles missing or deleted records explicitly without crashing on StaleDataError.
        Supports arbitrary batch sizes with safe transaction boundaries.
        Never generates fake vectors when the provider is unconfigured.
        """
        active_provider = provider or get_embedding_provider()

        if not active_provider.is_configured:
            return {
                "success": False,
                "embedded_count": 0,
                "reused_count": 0,
                "skipped_count": len(chunks),
                "reason": f"Embedding provider '{active_provider.provider_name}' is unconfigured. Check OLLAMA_BASE_URL or API configuration in backend/.env.",
            }

        if not chunks:
            return {
                "success": True,
                "embedded_count": 0,
                "reused_count": 0,
                "skipped_count": 0,
            }

        # Ensure any newly created chunks in session have IDs assigned
        if any(getattr(c, "id", None) is None for c in chunks):
            db.flush()

        # Resolve repository_id fallback from chunks if not passed explicitly
        if repository_id is None:
            for c in chunks:
                rid = getattr(c, "repository_id", None)
                if rid is not None:
                    repository_id = rid
                    break

        # Extract stable descriptor representations using persisted primary keys
        chunk_descriptors = []
        for c in chunks:
            cid = getattr(c, "id", None)
            c_repo_id = repository_id if repository_id is not None else getattr(c, "repository_id", None)
            c_text = getattr(c, "chunk_text", "")
            c_hash = getattr(c, "content_hash", "")
            c_emb = getattr(c, "embedding", None)
            c_model = getattr(c, "embedding_model", None)
            chunk_descriptors.append({
                "id": cid,
                "repository_id": c_repo_id,
                "text": c_text,
                "content_hash": c_hash,
                "embedding": c_emb,
                "embedding_model": c_model,
                "orm_obj": c,
            })

        to_embed = []
        reused_count = 0
        already_embedded_count = 0
        hash_vector_cache: Dict[str, List[float]] = {}

        for item in chunk_descriptors:
            if item["id"] is None:
                continue

            # Idempotence: Skip chunks that already have valid embeddings with the current model
            if item["embedding"] is not None and item["embedding_model"] == active_provider.model_name:
                already_embedded_count += 1
                continue

            # Check in-memory batch hash cache first to prevent redundant database or API lookups
            if item["content_hash"] in hash_vector_cache:
                reused_vec = hash_vector_cache[item["content_hash"]]
                stmt = (
                    update(CodeChunk)
                    .where(
                        CodeChunk.id == item["id"],
                        CodeChunk.repository_id == item["repository_id"],
                    )
                    .values(
                        embedding=reused_vec,
                        embedding_model=active_provider.model_name,
                    )
                )
                res = db.execute(stmt)
                if res.rowcount > 0:
                    reused_count += res.rowcount
                    orm_obj = item.get("orm_obj")
                    if orm_obj is not None:
                        try:
                            set_committed_value(orm_obj, "embedding", reused_vec)
                            set_committed_value(orm_obj, "embedding_model", active_provider.model_name)
                        except Exception:
                            pass
                continue

            # Check if identical content hash was previously embedded with the same model
            existing_identical = (
                db.query(CodeChunk.embedding)
                .filter(
                    CodeChunk.content_hash == item["content_hash"],
                    CodeChunk.embedding_model == active_provider.model_name,
                    CodeChunk.embedding.isnot(None),
                )
                .first()
            )

            if existing_identical and existing_identical[0] is not None:
                reused_vec = list(existing_identical[0])
                hash_vector_cache[item["content_hash"]] = reused_vec
                stmt = (
                    update(CodeChunk)
                    .where(
                        CodeChunk.id == item["id"],
                        CodeChunk.repository_id == item["repository_id"],
                    )
                    .values(
                        embedding=reused_vec,
                        embedding_model=active_provider.model_name,
                    )
                )
                res = db.execute(stmt)
                if res.rowcount > 0:
                    reused_count += res.rowcount
                    orm_obj = item.get("orm_obj")
                    if orm_obj is not None:
                        try:
                            set_committed_value(orm_obj, "embedding", reused_vec)
                            set_committed_value(orm_obj, "embedding_model", active_provider.model_name)
                        except Exception:
                            pass
                else:
                    logger.warning(
                        f"Chunk {item['id']} for repository {item['repository_id']} not found during reuse update."
                    )
            else:
                to_embed.append(item)

        if reused_count > 0:
            db.commit()

        if not to_embed:
            return {
                "success": True,
                "embedded_count": 0,
                "reused_count": reused_count,
                "skipped_count": 0,
                "already_embedded_count": already_embedded_count,
            }

        batch_size = max(1, getattr(settings, "EMBEDDING_BATCH_SIZE", 32))
        total_embedded = 0
        total_skipped = 0

        for i in range(0, len(to_embed), batch_size):
            batch = to_embed[i : i + batch_size]
            batch_texts = [item["text"] for item in batch]

            try:
                vectors = await active_provider.embed_batch(batch_texts)
            except Exception as embed_err:
                logger.error(f"Provider failed embedding batch of {len(batch_texts)} items: {embed_err}")
                db.rollback()
                return {
                    "success": False,
                    "embedded_count": total_embedded,
                    "reused_count": reused_count,
                    "skipped_count": len(to_embed) - total_embedded,
                    "error": str(embed_err),
                }

            if len(vectors) != len(batch):
                err_msg = f"Embedding provider returned {len(vectors)} vectors, expected {len(batch)}."
                logger.error(err_msg)
                db.rollback()
                return {
                    "success": False,
                    "embedded_count": total_embedded,
                    "reused_count": reused_count,
                    "skipped_count": len(to_embed) - total_embedded,
                    "error": err_msg,
                }

            try:
                batch_updated = 0
                for item, vec in zip(batch, vectors):
                    target_id = item["id"]
                    target_repo = item["repository_id"]

                    stmt = (
                        update(CodeChunk)
                        .where(
                            CodeChunk.id == target_id,
                            CodeChunk.repository_id == target_repo,
                        )
                        .values(
                            embedding=vec,
                            embedding_model=active_provider.model_name,
                        )
                    )
                    res = db.execute(stmt)
                    if res.rowcount > 0:
                        batch_updated += res.rowcount
                        hash_vector_cache[item["content_hash"]] = vec
                        orm_obj = item.get("orm_obj")
                        if orm_obj is not None:
                            try:
                                set_committed_value(orm_obj, "embedding", vec)
                                set_committed_value(orm_obj, "embedding_model", active_provider.model_name)
                            except Exception:
                                pass
                    else:
                        logger.warning(
                            f"CodeChunk record {target_id} in repository {target_repo} was not found (missing or deleted)."
                        )
                        total_skipped += 1

                db.commit()
                total_embedded += batch_updated

            except Exception as db_err:
                logger.error(f"Database error committing embedding batch: {db_err}")
                db.rollback()
                return {
                    "success": False,
                    "embedded_count": total_embedded,
                    "reused_count": reused_count,
                    "skipped_count": len(to_embed) - total_embedded,
                    "error": str(db_err),
                }

        return {
            "success": True,
            "embedded_count": total_embedded,
            "reused_count": reused_count,
            "skipped_count": total_skipped,
            "already_embedded_count": already_embedded_count,
        }
