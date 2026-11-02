# CodeMind AI — Architecture and Pipeline Analysis (Run 1)

## 1. Executive Architecture Overview

CodeMind AI is an intelligent codebase understanding and conversational code intelligence platform. This investigation traces the actual end-to-end execution pipeline from client request to response generation, identifying the physical components, data stores, routing mechanisms, and retrieval bottlenecks.

### 1.1 Actual Frontend Architecture (Inspection Finding)
In strict compliance with the Phase A inspection directive, the frontend was verified against the repository structure:
- **No Node.js / React / Vite host build pipeline**: The host CodeMind AI application does **not** use React, Vite, Next.js, or an npm build pipeline.
- **Server-Side Rendered Templates**: Located in `frontend/templates/`, served via FastAPI's Jinja2 template engine (e.g., `assistant.html`, `dashboard.html`, `code_viewer.html`, `dependencies.html`).
- **Static Assets**: Located in `frontend/static/` and mounted in `backend/app/main.py:96`:
  - `frontend/static/js/api.js`: Vanilla JavaScript managing client-side API requests, SSE streaming consumption, optimistic chat bubbles, and DOM updates.
  - `frontend/static/css/styles.css`: Stylesheets and design tokens.
  - `frontend/static/vendor/katex/`: Vendor assets for math rendering.

*(Note: While evaluated target repositories such as `RewardPoints Transfer` (Repo 47) contain React/TypeScript SPAs, the CodeMind AI host application itself operates on Jinja2 + Vanilla JS).*

---

## 2. Actual Request-to-Response Pipeline

The complete execution flow proceeds across seven distinct stages:

```
[User Browser / SSE Client]
         │ (HTTP POST / SSE)
         ▼
[FastAPI Entry Point: backend/app/main.py]
         │ Routes to /api/v1/assistant/conversations/{conv_id}/messages
         ▼
[API Route Handler: backend/app/api/routes/api_v1.py]
         │ - Authenticates session cookie/token via get_current_user_record
         │ - Verifies repository permission via verify_repo_access
         ▼
[Assistant Service: backend/app/services/assistant_service.py]
         │ - Acquires per-conversation async lock
         │ - Resolves conversational context & pronouns
         │ - Classifies query intent
         ▼
[Hybrid Retrieval Engine: backend/app/retrieval/hybrid_engine.py]
         │ 1. Exact Symbol / Identifier Match (_retrieve_exact_matches)
         │ 2. Keyword Substring Match (_retrieve_keyword_matches)
         │ 3. Dense Vector Cosine Search (_retrieve_vector_matches via pgvector)
         │ 4. Knowledge Graph 1-Hop Expansion (_expand_via_knowledge_graph)
         │ 5. Weighted Rank Fusion & Layer Directional Alignment
         │ 6. Per-File Diversity & Stable Deduplication
         ▼
[Local AI Serving Layer: Ollama Daemon (localhost:11434)]
         │ - Embeddings: nomic-embed-text (768-dim)
         │ - Chat / Generation: qwen2.5:3b (streaming SSE or non-streaming JSON)
         ▼
[Citation Verification & Database Persistence]
         │ - Post-synthesis citation audit against physical database chunks
         │ - Persists user and assistant messages into AssistantMessage table
         │ - Returns response payload / SSE tokens to client
```

---

## 3. Component & Source File Inventory

| Pipeline Stage | Implementation Source File | Core Classes & Methods | Responsibilities |
| :--- | :--- | :--- | :--- |
| **API Entry Point** | `backend/app/main.py` | `FastAPI`, `lifespan` | App lifecycle, static mount (`/static`), route registration. |
| **Route Layer** | `backend/app/api/routes/api_v1.py` | `send_conversation_message`, `stream_conversation_message` | Auth validation, repository scoping, HTTP/SSE contract. |
| **Orchestration** | `backend/app/services/assistant_service.py` | `AssistantService.answer_question`, `stream_answer_question` | Lock management, prompt assembly, citation audit. |
| **Search Engine** | `backend/app/retrieval/hybrid_engine.py` | `HybridRetrievalEngine.retrieve` | 4-channel search, rank fusion, deduplication. |
| **AST Extraction** | `backend/app/parsing/extractor.py` | `CodeExtractor`, Tree-Sitter | Multi-language syntax parsing (Python, TS, Go). |
| **Chunking** | `backend/app/parsing/chunker.py` | `SemanticChunker` | Symbol-aware AST windowing with line bounds. |
| **Code Graph** | `backend/app/graph/service.py` | `KnowledgeGraphService`, `GraphBuilder` | Callers, callees, imports, and inheritance edges. |
| **Vector DB** | PostgreSQL 16 + pgvector | `CodeChunk.embedding <=> vector` | 768-dim HNSW cosine distance search. |

---

## 4. Key Retrieval Bottlenecks Identified

Prior to Run 1 improvements, deep architectural inspection and fresh baseline measurements uncovered five critical bottlenecks in `HybridRetrievalEngine`:
1. **Directory Name Stem Flooding**: `_retrieve_exact_matches` extracted generic words like `"backend"` or `"frontend"` as file search stems, causing `IndexedFile.path.ilike("%backend%")` to match hundreds of files and starve domain-specific files like `main.py`.
2. **Missing Dotfile & Config Support**: `_detect_explicit_file_paths` failed to detect `.env`, `.env.example`, `.env.local`, and extension-less entrypoints.
3. **Test & Documentation Pollution**: The test-file penalty (`* 0.35`) was only invoked when a narrow `is_code_query` regex matched. General questions allowed test files (`backend/tests/test_transfers.py`) and markdown docs (`Prd.md`, `README.md`) to outrank implementation files.
4. **Architectural Layer Blindness**: When users inquired about "on the frontend", backend security files crowded out React UI components due to higher keyword frequency for terms like "JWT" or "token".
5. **Cross-Layer Quota Starvation**: In multi-layer fullstack execution queries, a single backend service file took up to 4 of the 8 retrieval slots, completely excluding frontend entrypoint and UI form components.
