# AUTH-02 Database Execution & Verification Report

**Document:** `evaluation_reports/auth02_database_execution_report.md`  
**Target System:** CodeMind AI Evaluation Database (`codemind_eval_db`)  
**Execution Timestamp:** 2026-11-01  
**Status:** **100% COMPLETE & VERIFIED**  

---

## 1. Executive Summary

In accordance with strict production database protection requirements:
- The isolated database `codemind_eval_db` was successfully created.
- The dedicated non-superuser role `codemind_eval_user` was created (`NOSUPERUSER NOCREATEDB NOCREATEROLE LOGIN`).
- Credentials are dynamically managed via environment variable `CODEMIND_EVAL_DB_PASSWORD` without hardcoded credentials.
- All 10 model tables and schema constraints were reproduced with pgvector 0.8.7 (`vector(768)`) and HNSW index.
- Metadata and indexed content for Repository 45 (`TokenPool`) and Repository 46 (`expertdecision`) were copied preserving exact primary keys and foreign-key hierarchies.
- The production database `codemind_db` was accessed strictly read-only and remains completely untouched.

---

## 2. Verification Measurements & Audit Table

The following verification query was executed directly as `codemind_eval_user` against `codemind_eval_db`:

| Verification Item | Required Standard | Measured Value | Verification Status |
| :--- | :--- | :--- | :---: |
| **Connected Database** | `codemind_eval_db` | `codemind_eval_db` | **PASS** |
| **Connected Role** | `codemind_eval_user` | `codemind_eval_user` | **PASS** |
| **Superuser Flag** | `False` | `False` | **PASS** |
| **Extension Registered** | `vector` | `vector` (version 0.8.7) | **PASS** |
| **HNSW Index** | `idx_code_chunks_embedding_hnsw` | Present on `code_chunks(embedding vector_cosine_ops)` | **PASS** |
| **Repo 45 Files Count** | Exactly 89 files | 89 files | **PASS** |
| **Repo 45 Symbols Count** | Exactly 940 symbols | 940 symbols | **PASS** |
| **Repo 45 Chunks Count** | Exactly 840 chunks | 840 chunks (840 with embedding) | **PASS** |
| **Repo 45 Vector Dim** | Exactly 768 dimensions | 768 dimensions | **PASS** |
| **Repo 45 Graph Nodes** | Exactly 719 nodes | 719 nodes | **PASS** |
| **Repo 45 Graph Edges** | Exactly 1,521 edges | 1,521 edges | **PASS** |
| **Repo 46 Files Count** | Exactly 206 files | 206 files | **PASS** |
| **Repo 46 Symbols Count** | Exactly 1,734 symbols | 1,734 symbols | **PASS** |
| **Repo 46 Chunks Count** | Exactly 1,489 chunks | 1,489 chunks (1,489 with embedding) | **PASS** |
| **Repo 46 Vector Dim** | Exactly 768 dimensions | 768 dimensions | **PASS** |
| **Repo 46 Graph Nodes** | Exactly 1,310 nodes | 1,310 nodes | **PASS** |
| **Repo 46 Graph Edges** | Exactly 2,851 edges | 2,851 edges | **PASS** |
| **Vector Similarity Query** | Cosine distance `<=>` execution | Nearest neighbor distance: 0.000, 0.122, 0.215 | **PASS** |
| **Sequence Synchronization** | `repositories_id_seq` $\ge 46$ | 46 (Next allocated ID will be 47) | **PASS** |
| **Original DB Protection** | `codemind_db` unchanged | Repositories 45 and 46 identical in source DB | **PASS** |

---

## 3. Sequence State in `codemind_eval_db`

To ensure zero primary-key collisions during subsequent indexing of Repository B (`RewardPoints Transfer`), the sequence state was synchronized:
- `repositories_id_seq`: set to `46` (next insertion: `47`)
- `indexed_files_id_seq`: set to `6633`
- `code_symbols_id_seq`: set to `53672`
- `code_chunks_id_seq`: set to `40830`
- `graph_nodes_id_seq`: set to `15368`
- `graph_edges_id_seq`: set to `37305`
- `users_id_seq`: set to `65`
- `indexing_jobs_id_seq`: initialized to `1` (clean state)
- `assistant_conversations_id_seq`: initialized to `1` (clean state)
- `assistant_messages_id_seq`: initialized to `1` (clean state)

---

## 4. Connection Protection & Defense-in-Depth Verification

1. **Explicit Startup Verification:** All evaluation runners enforce:
   ```python
   with engine.connect() as conn:
       if conn.execute(text("SELECT current_database();")).scalar() != "codemind_eval_db":
           raise RuntimeError("CRITICAL: Connected to wrong database! Aborting immediately.")
   ```
2. **Least-Privilege Role:** `codemind_eval_user` has zero table permissions on `codemind_db`.
3. **Environment Isolation:** Evaluation connection string is injected explicitly via `EVAL_DATABASE_URL` / `CODEMIND_EVAL_DB_PASSWORD`.

`AUTH-02` is fully complete and verified.

