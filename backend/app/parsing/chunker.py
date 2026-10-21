import hashlib
import logging
from dataclasses import dataclass
from typing import List, Optional

from backend.app.core.config import settings
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol

logger = logging.getLogger(__name__)


@dataclass
class GeneratedChunk:
    file_path: str
    code_symbol: Optional[str]
    chunk_index: int
    chunk_text: str
    content_hash: str
    language: Optional[str]
    start_line: int
    end_line: int
    symbol_id: Optional[int] = None


class CodeChunker:
    """
    Intelligent AST-aware code chunking.
    Prioritizes logical symbol boundaries (functions, classes, methods),
    falling back to structured sliding windows for polyglot code and top-level scripts.
    """

    @classmethod
    def chunk_file(
        cls,
        indexed_file: IndexedFile,
        content: str,
        symbols: Optional[List[CodeSymbol]] = None,
        revision: Optional[str] = None,
    ) -> List[GeneratedChunk]:
        if not content.strip():
            return []

        lines = content.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            return []

        lang = indexed_file.language or "text"
        chunks: List[GeneratedChunk] = []
        covered_line_ranges: List[tuple] = []

        # 1. Chunk by extracted function and class symbols
        if symbols:
            # Sort symbols by length descending to process outer classes or functions cleanly
            meaningful_symbols = [s for s in symbols if s.kind in ("function", "class", "method")]
            for sym in meaningful_symbols:
                s_line = max(1, sym.start_line)
                e_line = min(total_lines, sym.end_line)
                if s_line > e_line:
                    continue

                symbol_lines = lines[s_line - 1 : e_line]
                chunk_len = len(symbol_lines)

                clean_path = indexed_file.path.replace("\x00", "")
                clean_sym_name = sym.name.replace("\x00", "") if sym.name else None
                # Add context header
                header = f"// File: {clean_path} | {sym.kind.capitalize()}: {clean_sym_name} | Lines: {s_line}-{e_line}\n"
                
                if chunk_len <= settings.CHUNK_SIZE_LINES:
                    raw_text = "\n".join(symbol_lines)
                    full_chunk_text = (header + raw_text).replace("\x00", "\uFFFD")
                    c_hash = hashlib.sha256(full_chunk_text.encode("utf-8")).hexdigest()
                    chunks.append(
                        GeneratedChunk(
                            file_path=clean_path,
                            code_symbol=clean_sym_name,
                            chunk_index=len(chunks),
                            chunk_text=full_chunk_text,
                            content_hash=c_hash,
                            language=lang,
                            start_line=s_line,
                            end_line=e_line,
                            symbol_id=sym.id,
                        )
                    )
                else:
                    # Break large symbols into subchunks with overlap
                    step = max(1, settings.CHUNK_SIZE_LINES - settings.CHUNK_OVERLAP_LINES)
                    for start_idx in range(0, chunk_len, step):
                        end_idx = min(chunk_len, start_idx + settings.CHUNK_SIZE_LINES)
                        sub_lines = symbol_lines[start_idx:end_idx]
                        sub_start = s_line + start_idx
                        sub_end = s_line + end_idx - 1
                        sub_header = f"// File: {clean_path} | {sym.kind.capitalize()}: {clean_sym_name} (Part) | Lines: {sub_start}-{sub_end}\n"
                        full_chunk_text = (sub_header + "\n".join(sub_lines)).replace("\x00", "\uFFFD")
                        c_hash = hashlib.sha256(full_chunk_text.encode("utf-8")).hexdigest()
                        chunks.append(
                            GeneratedChunk(
                                file_path=clean_path,
                                code_symbol=clean_sym_name,
                                chunk_index=len(chunks),
                                chunk_text=full_chunk_text,
                                content_hash=c_hash,
                                language=lang,
                                start_line=sub_start,
                                end_line=sub_end,
                                symbol_id=sym.id,
                            )
                        )
                        if end_idx >= chunk_len:
                            break

                covered_line_ranges.append((s_line, e_line))

        # 2. If no symbols were extracted, or file has significant un-covered code, use sliding window
        if not chunks:
            clean_path = indexed_file.path.replace("\x00", "")
            step = max(1, settings.CHUNK_SIZE_LINES - settings.CHUNK_OVERLAP_LINES)
            for start_idx in range(0, total_lines, step):
                end_idx = min(total_lines, start_idx + settings.CHUNK_SIZE_LINES)
                window_lines = lines[start_idx:end_idx]
                s_line = start_idx + 1
                e_line = end_idx
                header = f"// File: {clean_path} | Lines: {s_line}-{e_line}\n"
                full_chunk_text = (header + "\n".join(window_lines)).replace("\x00", "\uFFFD")
                c_hash = hashlib.sha256(full_chunk_text.encode("utf-8")).hexdigest()

                chunks.append(
                    GeneratedChunk(
                        file_path=clean_path,
                        code_symbol=None,
                        chunk_index=len(chunks),
                        chunk_text=full_chunk_text,
                        content_hash=c_hash,
                        language=lang,
                        start_line=s_line,
                        end_line=e_line,
                        symbol_id=None,
                    )
                )
                if end_idx >= total_lines:
                    break

        return chunks
