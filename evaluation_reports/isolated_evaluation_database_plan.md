# Isolated Evaluation Database Architecture Plan

**Objective:** Provide a completely isolated, risk-free execution environment for CodeMind AI's full assistant pipeline during evaluation, ensuring the production database remains 100% untouched.

---

## 1. Rationale for Database Isolation

Static inspection of `backend/app/services/assistant_service.py:1180–1210` confirms that standard calls to `AssistantService.answer_question()` execute database writes:
```python
conv = AssistantConversation(...)
db.add(conv)
db.commit()
...
user_msg = AssistantMessage(...)
db.add(user_msg)
...
assistant_msg = AssistantMessage(...)
db.add(assistant_msg)
db.commit()
```
Relying on transaction rollbacks or mocking the database connection carries risks of accidental state corruption or altering natural multi-turn follow-up behavior. **An isolated evaluation database is the only safe method that allows the normal assistant pipeline to execute naturally with zero risk to production records.**

---

## 2. Technical Architecture & Database Separation

```mermaid
flowchart LR
    subgraph ProductionEnv["Production Database (100% Read-Only & Untouched)"]
        ProdDB[("codemind_db\nPort: 5432")]
    end
    
    subgraph EvalEnv["Isolated Evaluation Environment"]
        EvalDB[("codemind_eval_db\nPort: 5432")]
        Assistant["AssistantService (Normal Pipeline)"]
        EvalDB <--> Assistant
    end
    
    ProdDB -. "pg_dump / COPY (Selective Read-Only Clone)" .-> EvalDB
```

### A. Database Credentials & Connection Segregation
- **Production Database:** `postgresql://postgres:postgres@localhost:5432/codemind_db` (Remains untouched).
- **Evaluation Database:** `postgresql://postgres:postgres@localhost:5432/codemind_eval_db` (New, completely separated database instance).
- **Configuration Switch:** Controlled via an isolated script execution environment variable (`EVALUATION_DATABASE_URL`), leaving `backend/.env` completely unmodified.

### B. Preserving Repository Metadata, Chunks, and Vector Embeddings
To avoid costly re-embedding while maintaining exact repository IDs:
1. **Schema Initialization:** Apply migrations or schema creation on `codemind_eval_db` with `CREATE EXTENSION IF NOT EXISTS vector;`.
2. **Selective Table Copy:** Copy only the indexing and knowledge-graph tables from `codemind_db` to `codemind_eval_db`:
   - `repositories` (Preserving primary keys: 44 for Threatsheild, 45 for TokenPool, 46 for expertdecision).
   - `indexed_files`
   - `code_chunks` (Preserving 768-dimensional `nomic-embed-text` embeddings and `RobustVector` data).
   - `code_symbols`
   - `graph_nodes`
   - `graph_edges`
3. **Conversation Isolation:**
   - The tables `assistant_conversations` and `assistant_messages` will be initialized completely **EMPTY** in `codemind_eval_db`.
   - All evaluation queries, multi-turn follow-ups, and generated citations will write strictly to `codemind_eval_db`.
   - Zero rows will ever be written to `codemind_db`.

---

## 3. Step-by-Step Provisioning Procedure (Plan Only)

```sql
-- 1. Create isolated evaluation database
CREATE DATABASE codemind_eval_db;

-- 2. Connect and enable pgvector
\c codemind_eval_db
CREATE EXTENSION IF NOT EXISTS vector;

-- 3. Clone table structures and indexing data from codemind_db
-- (Executed via read-only pg_dump / psql pipe for tables: repositories, indexed_files, code_chunks, code_symbols, graph_nodes, graph_edges)
```

---

## 4. Evaluation Execution & Cleanup Lifecycle

1. **Pipeline Execution:** The evaluation runner initializes SQLAlchemy's engine with `EVALUATION_DATABASE_URL`, running `AssistantService.answer_question()` through its authentic, unmodified execution path.
2. **Result Verification:** Conversation records and responses generated in `codemind_eval_db` are extracted and verified against ground-truth files on disk.
3. **Backup & Teardown Protocol:**
   - After evaluation scoring is finalized, the evaluation session data can be archived into `evaluation_reports/codemind_eval_backup.sql`.
   - The temporary database can be safely dropped: `DROP DATABASE codemind_eval_db;`.
   - The production database `codemind_db` remains completely unchanged.

> [!IMPORTANT]
> **STRICT STOP:** This document represents an architectural proposal only. **No database has been created, no PostgreSQL configurations have been altered, and no commands have been executed.**

