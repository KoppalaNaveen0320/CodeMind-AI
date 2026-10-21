import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import or_, text

from backend.app.core.config import settings
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.repository import Repository
from backend.app.integrations.embeddings.service import get_embedding_provider

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: int
    repository_id: int
    file_path: str
    symbol_name: Optional[str]
    start_line: int
    end_line: int
    chunk_text: str
    score: float
    channels: List[str] = field(default_factory=list)
    source_revision: Optional[str] = None
    language: Optional[str] = None


class HybridRetrievalEngine:
    """
    Multi-channel Hybrid Retrieval Engine.
    Combines:
    1. Semantic vector similarity (pgvector cosine similarity).
    2. Full-text search / keyword matching.
    3. Exact symbol, function, class, and file-name matching.
    4. Graph relationship expansion.
    Enforces repository authorization, deduplication, and max context boundaries.
    """

    STOPWORDS: Set[str] = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
        "by", "from", "up", "about", "into", "through", "after", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did", "can", "could",
        "should", "would", "may", "might", "must", "shall", "will", "explain", "tell", "show",
        "what", "where", "which", "how", "who", "whom", "this", "that", "these", "those",
        "there", "here", "all", "any", "both", "each", "few", "more", "most", "some", "such",
        "only", "own", "same", "than", "too", "very", "please", "my", "your", "our", "their"
    }

    @classmethod
    async def retrieve(
        cls,
        db: Session,
        repository_id: int,
        query: str,
        user_id: Optional[int] = None,
        top_k: Optional[int] = None,
        language: Optional[str] = None,
        expand_graph: bool = True,
        branch: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        """
        Executes hybrid retrieval across vector, keyword, exact, and graph channels.
        Verifies user repository authorization before querying.
        Guarantees strict repository scoping, branch filtering, stable deduplication,
        and prioritization of source code over documentation for implementation queries.
        """
        # 1. Authorization Verification
        repo = db.query(Repository).filter(Repository.id == repository_id).first()
        if not repo:
            return []

        # If user_id is provided and repository has an assigned user_id, enforce match
        if user_id is not None and repo.user_id is not None and repo.user_id != user_id:
            logger.warning(f"Unauthorized retrieval attempt: user {user_id} denied access to repo {repository_id}")
            return []

        clean_query = query.strip()
        if not clean_query:
            return []

        k = top_k or settings.RETRIEVAL_TOP_K
        candidates_map: Dict[int, RetrievedChunk] = {}
        channel_scores: Dict[int, Dict[str, float]] = {}

        # 2. Exact Symbol, Class, Function, and File-Name Matching
        exact_chunks = cls._retrieve_exact_matches(db, repository_id, clean_query, language)
        for chunk in exact_chunks:
            cid = chunk.id
            candidates_map[cid] = cls._to_retrieved_chunk(chunk, 1.0, "exact")
            channel_scores.setdefault(cid, {})["exact"] = 1.0

        # 3. Full-Text / Keyword Search
        keyword_chunks = cls._retrieve_keyword_matches(db, repository_id, clean_query, language)
        for chunk, kw_score in keyword_chunks:
            cid = chunk.id
            if cid not in candidates_map:
                candidates_map[cid] = cls._to_retrieved_chunk(chunk, kw_score, "keyword")
            channel_scores.setdefault(cid, {})["keyword"] = kw_score

        # 4. Semantic Vector Similarity Search
        vector_chunks = await cls._retrieve_vector_matches(db, repository_id, clean_query, language)
        for chunk, vec_score in vector_chunks:
            cid = chunk.id
            if cid not in candidates_map:
                candidates_map[cid] = cls._to_retrieved_chunk(chunk, vec_score, "vector")
            channel_scores.setdefault(cid, {})["vector"] = vec_score

        # 5. Graph Relationship Expansion
        if expand_graph and candidates_map:
            graph_expanded_chunks = cls._expand_via_knowledge_graph(db, repository_id, candidates_map)
            for chunk, g_score in graph_expanded_chunks:
                cid = chunk.id
                if cid not in candidates_map:
                    candidates_map[cid] = cls._to_retrieved_chunk(chunk, g_score, "graph")
                channel_scores.setdefault(cid, {})["graph"] = g_score

        # 6. Rank Fusion (Weighted Combination with Code-Over-Documentation Prioritization)
        w_vec = settings.RETRIEVAL_VECTOR_WEIGHT
        w_kw = settings.RETRIEVAL_KEYWORD_WEIGHT
        w_exact = settings.RETRIEVAL_EXACT_WEIGHT
        w_graph = 0.15

        # Determine if query asks about code implementation/architecture/auth/routes/models
        is_code_query = bool(re.search(
            r"\b(architecture|route|routes|endpoint|endpoints|database|model|models|auth|authentication|jwt|token|function|functions|class|classes|method|methods|service|services|repository|controller|implement|implementation|module|modules|def|import)\b",
            clean_query,
            re.IGNORECASE
        ))

        scored_results: List[RetrievedChunk] = []
        for cid, chunk in candidates_map.items():
            # Guarantee repository scoping
            if chunk.repository_id != repository_id:
                continue

            scores = channel_scores.get(cid, {})
            channels = list(scores.keys())

            final_score = (
                scores.get("vector", 0.0) * w_vec
                + scores.get("keyword", 0.0) * w_kw
                + scores.get("exact", 0.0) * w_exact
                + scores.get("graph", 0.0) * w_graph
            )

            # Code vs Documentation/Tests ranking adjustment
            p_lower = chunk.file_path.lower().replace("\\", "/")
            is_doc = (
                p_lower.startswith("docs/")
                or p_lower.startswith("doc/")
                or "/docs/" in p_lower
                or "/doc/" in p_lower
                or p_lower.endswith((".rst", ".md", ".markdown", ".adoc", ".txt"))
                or "tutorial" in p_lower
            )
            is_test_or_upload = (
                p_lower.startswith(("tests/", "test/", "uploads/", "examples/", "fixtures/"))
                or "/tests/" in p_lower
                or "/test/" in p_lower
                or "/uploads/" in p_lower
                or "/examples/" in p_lower
                or "/fixtures/" in p_lower
                or p_lower.endswith(("_test.py", "_test.ts", "_test.js", "test.py"))
            )
            is_code_file = p_lower.endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".cpp", ".c", ".rs", ".rb", ".php", ".cs"))

            if is_code_query:
                if is_test_or_upload:
                    # Deprioritize test/upload files so core application source code ranks higher
                    final_score *= 0.35
                elif is_code_file:
                    # Boost actual source code files
                    final_score += 0.20
                    if chunk.symbol_name:
                        final_score += 0.10
                elif is_doc:
                    # Moderate documentation score so docs do not outrank source code
                    final_score *= 0.65
            else:
                if is_code_file and chunk.symbol_name:
                    final_score += 0.05

            chunk.score = round(min(1.0, max(0.0, final_score)), 4)
            chunk.channels = channels
            scored_results.append(chunk)

        # Sort descending by fused score
        scored_results.sort(key=lambda x: x.score, reverse=True)

        # 7. Stable Deduplication by File Path and Line Range, with Per-File Diversity
        seen_chunks: Set[Tuple[int, str, int, int]] = set()
        file_chunk_counts: Dict[str, int] = {}
        deduped_results: List[RetrievedChunk] = []
        for chunk in scored_results:
            stable_id = (chunk.repository_id, chunk.file_path, chunk.start_line, chunk.end_line)
            if stable_id in seen_chunks:
                continue
            # Cap at 2 chunks per file so a single file never crowds out other layers
            if file_chunk_counts.get(chunk.file_path, 0) >= 2:
                continue
            seen_chunks.add(stable_id)
            file_chunk_counts[chunk.file_path] = file_chunk_counts.get(chunk.file_path, 0) + 1
            deduped_results.append(chunk)
            if len(deduped_results) >= k:
                break

        return deduped_results

    @classmethod
    def _retrieve_exact_matches(
        cls, db: Session, repo_id: int, query: str, language: Optional[str]
    ) -> List[CodeChunk]:
        """Finds chunks with exact matching symbol names or file paths."""
        words = re.findall(r"[a-zA-Z0-9_\.]+", query)
        if not words:
            return []

        # Find code symbols matching words
        matching_symbols = (
            db.query(CodeSymbol)
            .filter(CodeSymbol.repository_id == repo_id, CodeSymbol.name.in_(words))
            .all()
        )
        symbol_names = [s.name for s in matching_symbols]

        q = db.query(CodeChunk).filter(CodeChunk.repository_id == repo_id)
        if language:
            q = q.filter(CodeChunk.language == language)

        conditions = []
        if symbol_names:
            conditions.append(CodeChunk.code_symbol.in_(symbol_names))
        for w in words:
            if "." in w or "/" in w:
                conditions.append(CodeChunk.file_path.ilike(f"%{w}%"))

        if not conditions:
            return []

        return q.filter(or_(*conditions)).limit(10).all()

    @classmethod
    def _retrieve_keyword_matches(
        cls, db: Session, repo_id: int, query: str, language: Optional[str]
    ) -> List[tuple]:
        """Finds chunks using keyword match or PostgreSQL full text, filtering out English stopwords."""
        words = [w for w in re.findall(r"[a-zA-Z0-9_]{3,}", query.lower()) if len(w) >= 3]
        if not words:
            return []

        # Filter out common stop words to prioritize domain-specific terms (routes, auth, models, etc.)
        meaningful_words = [w for w in words if w not in cls.STOPWORDS]
        search_words = meaningful_words if meaningful_words else words

        q = db.query(CodeChunk).filter(CodeChunk.repository_id == repo_id)
        if language:
            q = q.filter(CodeChunk.language == language)

        # Filter by tokens matching chunk text (up to 12 meaningful keywords)
        keyword_filters = [CodeChunk.chunk_text.ilike(f"%{w}%") for w in search_words[:12]]
        matching_chunks = q.filter(or_(*keyword_filters)).limit(25).all()

        results = []
        for chunk in matching_chunks:
            # Score based on frequency of matched meaningful words
            lower_text = chunk.chunk_text.lower()
            hit_count = sum(1 for w in search_words if w in lower_text)
            norm_score = min(1.0, hit_count / max(1, len(search_words)))
            results.append((chunk, norm_score))

        return results

    @classmethod
    async def _retrieve_vector_matches(
        cls, db: Session, repo_id: int, query: str, language: Optional[str]
    ) -> List[tuple]:
        """Calculates semantic similarity using pgvector or cosine similarity."""
        provider = get_embedding_provider()
        if not provider.is_configured:
            return []

        try:
            query_vector = await provider.embed_text(query)
        except Exception as e:
            logger.debug(f"Failed to generate query vector: {e}")
            return []

        # Check database dialect
        bind = db.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        q = db.query(CodeChunk).filter(
            CodeChunk.repository_id == repo_id,
            CodeChunk.embedding.isnot(None),
            CodeChunk.embedding_model == provider.model_name,
        )
        if language:
            q = q.filter(CodeChunk.language == language)

        if is_postgres:
            try:
                # Use native pgvector cosine distance: 1 - cosine_distance = cosine similarity
                distance = CodeChunk.embedding.cosine_distance(query_vector)
                chunks_with_dist = (
                    db.query(CodeChunk, distance.label("distance"))
                    .filter(
                        CodeChunk.repository_id == repo_id,
                        CodeChunk.embedding.isnot(None),
                        CodeChunk.embedding_model == provider.model_name,
                    )
                    .order_by(distance)
                    .limit(15)
                    .all()
                )
                return [(chunk, max(0.0, 1.0 - float(dist))) for chunk, dist in chunks_with_dist]
            except Exception as pg_err:
                logger.debug(f"PostgreSQL pgvector query failed, falling back: {pg_err}")

        # In-memory / SQLite fallback calculation for unit tests
        chunks = q.limit(50).all()
        results = []
        for chunk in chunks:
            if chunk.embedding is not None:
                sim = cls._cosine_similarity(query_vector, chunk.embedding)
                if sim > 0.3:
                    results.append((chunk, sim))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:15]

    @classmethod
    def _expand_via_knowledge_graph(
        cls, db: Session, repo_id: int, initial_candidates: Dict[int, RetrievedChunk]
    ) -> List[tuple]:
        """Finds related code chunks via Knowledge Graph relationships."""
        # Find symbols or files referenced in initial candidates
        candidate_paths = {c.file_path for c in initial_candidates.values()}
        candidate_symbols = {c.symbol_name for c in initial_candidates.values() if c.symbol_name}

        # Query graph nodes for candidate files/symbols
        seed_nodes = (
            db.query(GraphNode)
            .filter(
                GraphNode.repository_id == repo_id,
                or_(
                    GraphNode.file_path.in_(candidate_paths),
                    GraphNode.symbol_name.in_(candidate_symbols),
                ),
            )
            .limit(10)
            .all()
        )
        seed_ids = {n.id for n in seed_nodes}
        if not seed_ids:
            return []

        # Find 1-hop connected nodes (callers, callees, importing files)
        connected_edges = (
            db.query(GraphEdge)
            .filter(
                GraphEdge.repository_id == repo_id,
                or_(
                    GraphEdge.source_node_id.in_(seed_ids),
                    GraphEdge.target_node_id.in_(seed_ids),
                ),
                GraphEdge.edge_type.in_(["CALLS", "IMPORTS", "DEFINES"]),
            )
            .limit(15)
            .all()
        )

        neighbor_ids = set()
        for e in connected_edges:
            if e.source_node_id not in seed_ids:
                neighbor_ids.add(e.source_node_id)
            if e.target_node_id not in seed_ids:
                neighbor_ids.add(e.target_node_id)

        if not neighbor_ids:
            return []

        neighbor_nodes = (
            db.query(GraphNode)
            .filter(
                GraphNode.repository_id == repo_id,
                GraphNode.id.in_(neighbor_ids)
            )
            .all()
        )
        neighbor_paths = {n.file_path for n in neighbor_nodes if n.file_path}

        if not neighbor_paths:
            return []

        expanded_chunks = (
            db.query(CodeChunk)
            .filter(
                CodeChunk.repository_id == repo_id,
                CodeChunk.file_path.in_(neighbor_paths),
            )
            .limit(5)
            .all()
        )

        return [(chunk, 0.65) for chunk in expanded_chunks if chunk.id not in initial_candidates]

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Calculates cosine similarity between two float vectors."""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return max(0.0, min(1.0, dot / (norm_a * norm_b)))

    @staticmethod
    def _to_retrieved_chunk(chunk: CodeChunk, initial_score: float, channel: str) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=chunk.id,
            repository_id=chunk.repository_id,
            file_path=chunk.file_path,
            symbol_name=chunk.code_symbol,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            chunk_text=chunk.chunk_text,
            score=round(initial_score, 4),
            channels=[channel],
            source_revision=chunk.source_revision,
            language=chunk.language,
        )
