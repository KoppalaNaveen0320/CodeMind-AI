import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.knowledge_graph import GraphEdge, GraphNode
from backend.app.models.repository import Repository
from backend.app.schemas.symbol import SymbolDetailResponse, SymbolSearchItem, SymbolSearchResponse

logger = logging.getLogger(__name__)


class SymbolService:
    """
    Advanced Symbol Search and Source Metadata Service.
    Enforces repository scoping, exact-over-partial ranking, and verified source coordinates.
    """

    @classmethod
    def search_symbols(
        cls,
        db: Session,
        query: str = "",
        repository_id: Optional[int] = None,
        file_path: Optional[str] = None,
        symbol_type: Optional[str] = None,
        language: Optional[str] = None,
        exact: bool = False,
        limit: int = 25,
        offset: int = 0,
        user_id: Optional[int] = None,
    ) -> SymbolSearchResponse:
        """
        Executes bounded, indexed symbol search with exact-above-partial ranking.
        Enforces user ownership scoping when repository_id is not specified.
        """
        limit = min(max(1, limit), 100)
        offset = max(0, offset)
        clean_q = query.strip()

        base_query = (
            db.query(CodeSymbol, IndexedFile, Repository)
            .join(IndexedFile, CodeSymbol.file_id == IndexedFile.id)
            .join(Repository, CodeSymbol.repository_id == Repository.id)
        )

        filters_applied: Dict[str, Any] = {}

        if repository_id is not None:
            base_query = base_query.filter(CodeSymbol.repository_id == repository_id)
            filters_applied["repository_id"] = repository_id
        elif user_id is not None:
            base_query = base_query.filter(or_(Repository.user_id == user_id, Repository.user_id.is_(None)))

        if file_path:
            clean_fp = file_path.strip().replace("\\", "/")
            base_query = base_query.filter(IndexedFile.path.ilike(f"%{clean_fp}%"))
            filters_applied["file_path"] = clean_fp

        if symbol_type:
            types = [t.strip().lower() for t in symbol_type.split(",") if t.strip()]
            if types:
                base_query = base_query.filter(func.lower(CodeSymbol.kind).in_(types))
                filters_applied["symbol_type"] = types

        if language:
            clean_lang = language.strip().lower()
            base_query = base_query.filter(func.lower(IndexedFile.language) == clean_lang)
            filters_applied["language"] = clean_lang

        if clean_q:
            if exact:
                base_query = base_query.filter(func.lower(CodeSymbol.name) == clean_q.lower())
                filters_applied["exact"] = True
            else:
                base_query = base_query.filter(
                    or_(
                        CodeSymbol.name.ilike(f"%{clean_q}%"),
                        CodeSymbol.signature.ilike(f"%{clean_q}%"),
                    )
                )

        total_count = base_query.count()

        if total_count == 0:
            return SymbolSearchResponse(
                query=query,
                total_count=0,
                page=(offset // limit) + 1,
                per_page=limit,
                results=[],
                filters_applied=filters_applied,
            )

        if clean_q:
            rank_order = case(
                (CodeSymbol.name == clean_q, 1),
                (func.lower(CodeSymbol.name) == clean_q.lower(), 2),
                (CodeSymbol.name.ilike(f"{clean_q}%"), 3),
                (func.lower(CodeSymbol.name).ilike(f"{clean_q.lower()}%"), 4),
                else_=5,
            )
            ordered_query = (
                base_query
                .order_by(
                    rank_order.asc(),
                    func.length(CodeSymbol.name).asc(),
                    IndexedFile.path.asc(),
                    CodeSymbol.start_line.asc(),
                )
            )
        else:
            ordered_query = (
                base_query
                .order_by(
                    CodeSymbol.name.asc(),
                    IndexedFile.path.asc(),
                    CodeSymbol.start_line.asc(),
                )
            )

        rows = ordered_query.offset(offset).limit(limit).all()

        results: List[SymbolSearchItem] = []
        for sym, ifile, repo in rows:
            match_type = "partial"
            score = 50.0

            if clean_q:
                if sym.name == clean_q:
                    match_type = "exact"
                    score = 100.0
                elif sym.name.lower() == clean_q.lower():
                    match_type = "exact"
                    score = 95.0
                elif sym.name.startswith(clean_q):
                    match_type = "prefix"
                    score = 80.0
                elif sym.name.lower().startswith(clean_q.lower()):
                    match_type = "prefix"
                    score = 75.0

            # Source preview extraction
            preview = None
            chunk = (
                db.query(CodeChunk)
                .filter(
                    CodeChunk.repository_id == sym.repository_id,
                    CodeChunk.file_id == sym.file_id,
                    CodeChunk.start_line <= sym.end_line,
                    CodeChunk.end_line >= sym.start_line,
                )
                .first()
            )
            if chunk and chunk.chunk_text:
                lines = chunk.chunk_text.strip().splitlines()
                preview = "\n".join(lines[:4])
            elif sym.signature:
                preview = sym.signature
            elif sym.docstring:
                preview = sym.docstring.strip().splitlines()[0]

            results.append(
                SymbolSearchItem(
                    id=sym.id,
                    name=sym.name,
                    kind=sym.kind,
                    symbol_type=sym.kind,
                    repository_id=repo.id,
                    repository_name=repo.name,
                    repository_full_name=repo.full_name,
                    file_path=ifile.path,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    start_column=sym.start_column,
                    end_column=sym.end_column,
                    signature=sym.signature,
                    docstring=sym.docstring,
                    preview=preview,
                    snippet=preview,
                    language=ifile.language,
                    match_type=match_type,
                    score=score,
                )
            )

        has_more = (offset + len(results)) < total_count
        return SymbolSearchResponse(
            query=clean_q,
            total_count=total_count,
            page=(offset // limit) + 1,
            per_page=limit,
            results=results,
            symbols=results,
            has_more=has_more,
            filters_applied=filters_applied,
        )

    @classmethod
    def get_symbol_detail(
        cls, db: Session, symbol_id: int, repository_id: Optional[int] = None
    ) -> Optional[SymbolDetailResponse]:
        """
        Retrieves detailed symbol metadata and call counts.
        """
        query = (
            db.query(CodeSymbol, IndexedFile, Repository)
            .join(IndexedFile, CodeSymbol.file_id == IndexedFile.id)
            .join(Repository, CodeSymbol.repository_id == Repository.id)
            .filter(CodeSymbol.id == symbol_id)
        )
        if repository_id is not None:
            query = query.filter(CodeSymbol.repository_id == repository_id)

        item = query.first()
        if not item:
            return None

        sym, ifile, repo = item

        # Check corresponding graph node for calls
        node = (
            db.query(GraphNode)
            .filter(
                GraphNode.repository_id == repo.id,
                GraphNode.file_path == ifile.path,
                or_(GraphNode.name == sym.name, GraphNode.symbol_name == sym.name),
            )
            .first()
        )

        in_calls = 0
        out_calls = 0
        if node:
            in_calls = (
                db.query(GraphEdge)
                .filter(GraphEdge.target_node_id == node.id, GraphEdge.edge_type == "CALLS")
                .count()
            )
            out_calls = (
                db.query(GraphEdge)
                .filter(GraphEdge.source_node_id == node.id, GraphEdge.edge_type == "CALLS")
                .count()
            )

        preview = None
        chunk = (
            db.query(CodeChunk)
            .filter(
                CodeChunk.repository_id == sym.repository_id,
                CodeChunk.file_id == sym.file_id,
                CodeChunk.start_line <= sym.end_line,
                CodeChunk.end_line >= sym.start_line,
            )
            .first()
        )
        if chunk and chunk.chunk_text:
            lines = chunk.chunk_text.strip().splitlines()
            preview = "\n".join(lines[:6])
        elif sym.signature:
            preview = sym.signature

        return SymbolDetailResponse(
            id=sym.id,
            name=sym.name,
            kind=sym.kind,
            symbol_type=sym.kind,
            repository_id=repo.id,
            repository_name=repo.name,
            repository_full_name=repo.full_name,
            file_path=ifile.path,
            start_line=sym.start_line,
            end_line=sym.end_line,
            start_column=sym.start_column,
            end_column=sym.end_column,
            signature=sym.signature,
            docstring=sym.docstring,
            preview=preview,
            snippet=preview,
            language=ifile.language,
            has_callers=in_calls > 0,
            has_callees=out_calls > 0,
            incoming_calls_count=in_calls,
            outgoing_calls_count=out_calls,
        )
