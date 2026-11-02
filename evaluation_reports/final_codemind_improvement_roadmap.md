# CodeMind AI — Prioritized Technical Improvement Roadmap

## 1. Executive Summary

Based on the comprehensive findings from AUTH-01 (controlled HTTP benchmarks), AUTH-02 (isolated evaluation database setup), AUTH-03 (RewardPoints indexing), AUTH-04 (60-question blind cross-repository evaluation), and AUTH-05 (regression testing), this document defines a 16-point prioritized technical improvement roadmap for CodeMind AI.

Each improvement item includes:
- Empirical failure evidence & root cause.
- Proposed architectural remediation.
- Implementation complexity & priority tier.

---

## 2. The 16-Point Prioritized Roadmap

| Priority | Item ID | Title | Complexity | Target Phase | Description |
| :---: | :---: | :--- | :---: | :---: | :--- |
| **High** | `IMP-01` | Client Semaphore Bottleneck Decoupling in Benchmarks | Medium | Immediate | Refactor benchmark clients to use rate-controlled async worker pools rather than burst task generation. |
| **High** | `IMP-02` | TCP Connection Warm-Up Concurrency Parity | Medium | Immediate | Implement parallel multi-socket warm-up loops matching httpx client max_connections pool size. |
| **Critical** | `IMP-03` | CPU-Bound Offloading to AnyIO Worker Pool | Medium | Short-Term | Enforce anyio.to_thread.run_sync or ProcessPoolExecutor for CPU-intensive hashing and parsing tasks. |
| **Critical** | `IMP-04` | Explicit Vector Representation Casting in pgvector Migrations | Medium | Short-Term | Add explicit CAST(:embedding AS vector) and float4[] serializer in database migration pipelines. |
| **Medium** | `IMP-05` | Change-Impact Precision Tuning via Call-Depth Filters | Medium | Short-Term | Introduce configurable call-depth filters (depth=1 direct callers vs depth>=2 transitive callers). |
| **Medium** | `IMP-06` | Tree-Sitter Polyglot Parser Expansion (Rust, C++, Java) | Medium | Short-Term | Bundle pre-compiled Tree-Sitter grammars for Rust, C++, Java, and C# in backend/app/services/extractor.py. |
| **High** | `IMP-07` | Dynamic Dependency Injection Resolver for FastAPI/Spring | Medium | Short-Term | Implement dedicated framework-specific semantic resolvers that map DI providers to call graphs. |
| **High** | `IMP-08` | Conversation Lock Event Loop Compatibility (Trio Support) | Medium | Medium-Term | Wrap event loop calls in anyio.from_thread or anyio-native lock primitives. |
| **Medium** | `IMP-09` | Hierarchical Chunk Windowing for Multi-File Traces | Medium | Medium-Term | Implement hierarchical chunk summarization where file-level summaries are combined with symbol-level chunks. |
| **High** | `IMP-10` | Automated Database Sequence Synchronization Trigger | Medium | Medium-Term | Add post-import automated sequence alignment function in repository ingestion service. |
| **Low** | `IMP-11` | BM25 Exact Match Weight Dynamic Adjustment | Medium | Medium-Term | Introduce symbol-aware BM25 tokenizer that boosts exact case-sensitive matches for code tokens. |
| **Medium** | `IMP-12` | Streaming Chunk Parity Verification | Medium | Medium-Term | Unify citation emission protocol across both stream_answer_question and answer_question. |
| **High** | `IMP-13` | Incremental Indexing via Git Commit Diffs | Medium | Long-Term | Implement git diff change detection to only re-embed modified and added files. |
| **Medium** | `IMP-14` | Cross-Repository Comparative Query Mode | Medium | Long-Term | Create an explicit multi-repo comparison endpoint with strict permission auditing. |
| **Low** | `IMP-15` | Automated Ground-Truth Evaluation Benchmark Harness | Medium | Long-Term | Integrate the 60-question evaluation harness as an automated CI/CD pipeline step. |
| **Critical** | `IMP-16` | Fine-Tuned Small Code Embedding Model Integration | Medium | Long-Term | Evaluate and integrate code-specific dense embedding models (e.g., StarCoder-Embed or Qwen-Coder-Embed). |

---

## 3. Detailed Technical Descriptions & Implementation Plans

### IMP-01: Client Semaphore Bottleneck Decoupling in Benchmarks
- **Priority**: `High` | **Phase**: `Immediate`
- **Empirical Evidence & Root Cause**: AUTH-01 benchmark queue-wait P50 (774-1648ms) was caused by client-side Semaphore(50) admission delay under burst task spawning, not server queueing.
- **Proposed Implementation Plan**: Refactor benchmark clients to use rate-controlled async worker pools rather than burst task generation.

### IMP-02: TCP Connection Warm-Up Concurrency Parity
- **Priority**: `High` | **Phase**: `Immediate`
- **Empirical Evidence & Root Cause**: AUTH-01 revealed sequential 30-request warm-up warmed only 1 socket, forcing 49 new TCP handshakes during initial burst.
- **Proposed Implementation Plan**: Implement parallel multi-socket warm-up loops matching httpx client max_connections pool size.

### IMP-03: CPU-Bound Offloading to AnyIO Worker Pool
- **Priority**: `Critical` | **Phase**: `Short-Term`
- **Empirical Evidence & Root Cause**: AUTH-01 /cpu-async locked the asyncio event loop completely, causing server latency to spike and starving other requests.
- **Proposed Implementation Plan**: Enforce anyio.to_thread.run_sync or ProcessPoolExecutor for CPU-intensive hashing and parsing tasks.

### IMP-04: Explicit Vector Representation Casting in pgvector Migrations
- **Priority**: `Critical` | **Phase**: `Short-Term`
- **Empirical Evidence & Root Cause**: AUTH-02 encountered binary \x0003... format incompatibilities when migrating embeddings between PostgreSQL databases.
- **Proposed Implementation Plan**: Add explicit CAST(:embedding AS vector) and float4[] serializer in database migration pipelines.

### IMP-05: Change-Impact Precision Tuning via Call-Depth Filters
- **Priority**: `Medium` | **Phase**: `Short-Term`
- **Empirical Evidence & Root Cause**: AUTH-04 achieved 80.0% precision on change impact because indirect module importers were flagged as impacted.
- **Proposed Implementation Plan**: Introduce configurable call-depth filters (depth=1 direct callers vs depth>=2 transitive callers).

### IMP-06: Tree-Sitter Polyglot Parser Expansion (Rust, C++, Java)
- **Priority**: `Medium` | **Phase**: `Short-Term`
- **Empirical Evidence & Root Cause**: While Python, Go, and TypeScript demonstrated 98.3% symbol accuracy, other languages lack native AST extraction.
- **Proposed Implementation Plan**: Bundle pre-compiled Tree-Sitter grammars for Rust, C++, Java, and C# in backend/app/services/extractor.py.

### IMP-07: Dynamic Dependency Injection Resolver for FastAPI/Spring
- **Priority**: `High` | **Phase**: `Short-Term`
- **Empirical Evidence & Root Cause**: Static AST parser treats Depends() and interface parameters as unresolved types.
- **Proposed Implementation Plan**: Implement dedicated framework-specific semantic resolvers that map DI providers to call graphs.

### IMP-08: Conversation Lock Event Loop Compatibility (Trio Support)
- **Priority**: `High` | **Phase**: `Medium-Term`
- **Empirical Evidence & Root Cause**: AUTH-05 revealed AssistantService._get_conversation_lock crashes on Trio due to direct asyncio.get_running_loop() call.
- **Proposed Implementation Plan**: Wrap event loop calls in anyio.from_thread or anyio-native lock primitives.

### IMP-09: Hierarchical Chunk Windowing for Multi-File Traces
- **Priority**: `Medium` | **Phase**: `Medium-Term`
- **Empirical Evidence & Root Cause**: Large multi-file execution traces require pulling 10+ chunks, occasionally reaching context window limits.
- **Proposed Implementation Plan**: Implement hierarchical chunk summarization where file-level summaries are combined with symbol-level chunks.

### IMP-10: Automated Database Sequence Synchronization Trigger
- **Priority**: `High` | **Phase**: `Medium-Term`
- **Empirical Evidence & Root Cause**: AUTH-02 required manual SELECT setval() across all PostgreSQL sequences to avoid duplicate key errors.
- **Proposed Implementation Plan**: Add post-import automated sequence alignment function in repository ingestion service.

### IMP-11: BM25 Exact Match Weight Dynamic Adjustment
- **Priority**: `Low` | **Phase**: `Medium-Term`
- **Empirical Evidence & Root Cause**: Symbols with common English words (e.g., 'root', 'main', 'run') receive skewed BM25 weights.
- **Proposed Implementation Plan**: Introduce symbol-aware BM25 tokenizer that boosts exact case-sensitive matches for code tokens.

### IMP-12: Streaming Chunk Parity Verification
- **Priority**: `Medium` | **Phase**: `Medium-Term`
- **Empirical Evidence & Root Cause**: Differences in citation metadata formatting between streaming and non-streaming responses.
- **Proposed Implementation Plan**: Unify citation emission protocol across both stream_answer_question and answer_question.

### IMP-13: Incremental Indexing via Git Commit Diffs
- **Priority**: `High` | **Phase**: `Long-Term`
- **Empirical Evidence & Root Cause**: Currently reindexing a repository re-chunks all files, requiring unnecessary embedding compute.
- **Proposed Implementation Plan**: Implement git diff change detection to only re-embed modified and added files.

### IMP-14: Cross-Repository Comparative Query Mode
- **Priority**: `Medium` | **Phase**: `Long-Term`
- **Empirical Evidence & Root Cause**: While repository isolation is strictly enforced, users occasionally want to compare implementations across repos.
- **Proposed Implementation Plan**: Create an explicit multi-repo comparison endpoint with strict permission auditing.

### IMP-15: Automated Ground-Truth Evaluation Benchmark Harness
- **Priority**: `Low` | **Phase**: `Long-Term`
- **Empirical Evidence & Root Cause**: Evaluation currently requires manual test orchestrators.
- **Proposed Implementation Plan**: Integrate the 60-question evaluation harness as an automated CI/CD pipeline step.

### IMP-16: Fine-Tuned Small Code Embedding Model Integration
- **Priority**: `Critical` | **Phase**: `Long-Term`
- **Empirical Evidence & Root Cause**: Nomic-embed-text performs well for general semantic search but can miss subtle code syntax differences.
- **Proposed Implementation Plan**: Evaluate and integrate code-specific dense embedding models (e.g., StarCoder-Embed or Qwen-Coder-Embed).
