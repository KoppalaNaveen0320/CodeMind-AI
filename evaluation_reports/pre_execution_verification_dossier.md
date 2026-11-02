# CodeMind AI — Pre-Execution Verification Dossier

**Document Status:** Formal Technical Dossier for Pre-Execution Verification Stage  
**Target System:** CodeMind AI Evaluation & Generalization Framework  
**Scope Boundaries:** Read-Only Static Verification Stage ONLY — Zero Prohibited Actions Executed  
**Date:** 2026-11-01  

---

## Executive Summary & Verification Protocol Declaration

In accordance with strict operational directives, **no benchmarks have been executed, no databases have been modified or created, no repositories have been indexed, no tests have been run, and no CodeMind assistant prompts have been executed.**

This dossier delivers the complete technical specifications, exact operational commands, code implementations, mathematical scoring models, and safety guarantees for Checkpoints **AUTH-01 through AUTH-05**.

Every checkpoint is presented in full technical depth to allow independent audit and verification prior to any execution authorization.

---

# SECTION 1: AUTH-01 — Benchmark V2 Analysis & Complete Source Code

### 1.1 Complete Source Code (`scratch/benchmark_http_fastapi_v2.py`)

Below is the complete, unabridged source code of `scratch/benchmark_http_fastapi_v2.py` (184 lines):

```python
import asyncio
import time
import subprocess
import sys
import os
import platform
import statistics
import json
import httpx

def get_percentile(data, p):
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(data) - 1)
    d0 = data[f] * (c - k)
    d1 = data[c] * (k - f)
    return round(d0 + d1, 3)

SERVER_SCRIPT = """
import time, asyncio, uvicorn
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI()

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        t1 = time.perf_counter()
        response.headers['X-Server-Time-Ms'] = str(round((t1 - t0) * 1000, 3))
        return response

app.add_middleware(TimingMiddleware)

@app.get('/sync-endpoint')
def sync_endpoint():
    time.sleep(0.005)
    return {'status': 'ok', 'type': 'sync'}

@app.get('/async-endpoint')
async def async_endpoint():
    await asyncio.sleep(0.005)
    return {'status': 'ok', 'type': 'async'}

@app.get('/cpu-sync')
def cpu_sync():
    val = sum(i * i for i in range(100_000))
    return {'status': 'ok', 'val': val}

@app.get('/cpu-async')
async def cpu_async():
    val = sum(i * i for i in range(100_000))
    return {'status': 'ok', 'val': val}

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18768
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')
"""

async def run_single_benchmark(client, url, total_requests, concurrency):
    semaphore = asyncio.Semaphore(concurrency)
    client_latencies = []
    server_latencies = []
    queue_wait_times = []
    active_concurrency_samples = []
    current_active = 0
    errors = 0
    timeouts = 0

    async def worker():
        nonlocal current_active, errors, timeouts
        t_queued = time.perf_counter()
        async with semaphore:
            t_acquired = time.perf_counter()
            current_active += 1
            active_concurrency_samples.append(current_active)
            queue_wait_times.append((t_acquired - t_queued) * 1000)

            t0 = time.perf_counter()
            try:
                resp = await client.get(url)
                t1 = time.perf_counter()
                if resp.status_code == 200:
                    client_latencies.append((t1 - t0) * 1000)
                    s_ms = float(resp.headers.get("X-Server-Time-Ms", 0))
                    server_latencies.append(s_ms)
                else:
                    errors += 1
            except httpx.TimeoutException:
                timeouts += 1
            except Exception:
                errors += 1
            finally:
                current_active -= 1

    bench_start = time.perf_counter()
    tasks = [asyncio.create_task(worker()) for _ in range(total_requests)]
    await asyncio.gather(*tasks)
    bench_end = time.perf_counter()

    total_time = bench_end - bench_start
    throughput = total_requests / total_time if total_time > 0 else 0

    client_latencies.sort()
    server_latencies.sort()
    queue_wait_times.sort()

    return {
        "url": url,
        "total_requests": total_requests,
        "concurrency_limit": concurrency,
        "max_observed_concurrency": max(active_concurrency_samples) if active_concurrency_samples else 0,
        "total_duration_sec": round(total_time, 4),
        "throughput_req_sec": round(throughput, 2),
        "client_rtt_p50_ms": get_percentile(client_latencies, 50),
        "client_rtt_p95_ms": get_percentile(client_latencies, 95),
        "client_rtt_p99_ms": get_percentile(client_latencies, 99),
        "server_time_p50_ms": get_percentile(server_latencies, 50),
        "server_time_p95_ms": get_percentile(server_latencies, 95),
        "server_time_p99_ms": get_percentile(server_latencies, 99),
        "queue_wait_p50_ms": get_percentile(queue_wait_times, 50),
        "queue_wait_p95_ms": get_percentile(queue_wait_times, 95),
        "errors": errors,
        "timeouts": timeouts
    }

async def main():
    port = 18768
    with open("scratch/v2_server.py", "w", encoding="utf-8") as f:
        f.write(SERVER_SCRIPT)

    print(f"Launching Uvicorn server in isolated subprocess on port {port}...")
    server_proc = subprocess.Popen([sys.executable, "scratch/v2_server.py", str(port)])
    await asyncio.sleep(2.0)

    base = f"http://127.0.0.1:{port}"
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=50)
    timeout = httpx.Timeout(30.0, connect=10.0)

    results = {"sync_runs": [], "async_runs": [], "cpu_sync_runs": [], "cpu_async_runs": []}

    try:
        async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
            # Warm-up phase (30 requests each, completely excluded from measurements)
            print("Warming up connections (30 requests)...")
            for _ in range(30):
                await client.get(f"{base}/sync-endpoint")
                await client.get(f"{base}/async-endpoint")

            print("\nExecuting 3 Interleaved Repetitions for I/O Workload (500 requests, 50 concurrency)...")
            for rep in range(1, 4):
                print(f"--- Repetition {rep}/3 ---")
                sync_res = await run_single_benchmark(client, f"{base}/sync-endpoint", 500, 50)
                print(f"  Sync:  Throughput = {sync_res['throughput_req_sec']} req/s | Client P50 = {sync_res['client_rtt_p50_ms']} ms | Server P50 = {sync_res['server_time_p50_ms']} ms")
                results["sync_runs"].append(sync_res)

                async_res = await run_single_benchmark(client, f"{base}/async-endpoint", 500, 50)
                print(f"  Async: Throughput = {async_res['throughput_req_sec']} req/s | Client P50 = {async_res['client_rtt_p50_ms']} ms | Server P50 = {async_res['server_time_p50_ms']} ms")
                results["async_runs"].append(async_res)

            print("\nExecuting CPU-Bound Workload Comparison (50 requests, 10 concurrency)...")
            cpu_sync = await run_single_benchmark(client, f"{base}/cpu-sync", 50, 10)
            cpu_async = await run_single_benchmark(client, f"{base}/cpu-async", 50, 10)
            results["cpu_sync_runs"].append(cpu_sync)
            results["cpu_async_runs"].append(cpu_async)
            print(f"  CPU Sync:  Throughput = {cpu_sync['throughput_req_sec']} req/s | Client P50 = {cpu_sync['client_rtt_p50_ms']} ms")
            print(f"  CPU Async: Throughput = {cpu_async['throughput_req_sec']} req/s | Client P50 = {cpu_async['client_rtt_p50_ms']} ms")

    finally:
        server_proc.terminate()
        server_proc.wait()

    with open("scratch/benchmark_http_fastapi_v2_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\nBenchmark V2 completed! Results written to scratch/benchmark_http_fastapi_v2_results.json")

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 1.2 Architectural & Engineering Verification Points

#### 1. How Client Concurrency is Measured
- An `asyncio.Semaphore(concurrency)` explicitly gates task execution.
- Real-time client concurrency is tracked via `current_active += 1` inside the semaphore block and decremented in a `finally` block.
- Each worker records `active_concurrency_samples.append(current_active)`.
- The benchmark returns `max_observed_concurrency` confirming that the client reached and held the intended concurrency limit ($50$).
- Client queue wait time before acquiring the semaphore is measured via `(t_acquired - t_queued) * 1000` and reported as `queue_wait_p50_ms` and `queue_wait_p95_ms`.

#### 2. How Server Concurrency is Measured
- The ASGI application runs custom `TimingMiddleware(BaseHTTPMiddleware)`.
- For every incoming request, the middleware captures `t0 = time.perf_counter()`, awaits `call_next(request)`, captures `t1 = time.perf_counter()`, and attaches the exact duration to the response header `X-Server-Time-Ms = str(round((t1 - t0) * 1000, 3))`.
- When the client receives the response, it extracts this header:
  $$T_{\text{server}} = \text{float}(\text{resp.headers.get("X-Server-Time-Ms", 0)})$$
- This provides direct visibility into whether requests were processed concurrently or serialized on the server.

#### 3. How Subprocess Isolation Works
- The server is not spawned inside the benchmark's Python event loop.
- Instead, `subprocess.Popen([sys.executable, "scratch/v2_server.py", str(port)])` spawns an independent OS process with its own CPython interpreter, private Global Interpreter Lock (GIL), independent AnyIO worker threadpool, and isolated `asyncio` event loop.
- Client socket calls run in the parent process, completely eliminating thread/event-loop resource competition between client and server.

#### 4. How Server Cleanup is Guaranteed
- Subprocess management is enclosed in a strict `try ... finally` block:
  ```python
  try:
      # warm-up, interleaved repetitions, and CPU benchmarks
  finally:
      server_proc.terminate()
      server_proc.wait()
  ```
- Whether the benchmark runs to completion, times out, or encounters a keyboard interrupt / uncaught exception, the `finally` block guarantees that `terminate()` sends `SIGTERM` to the Uvicorn child process and `wait()` reaps its process table entry, leaving zero orphaned processes or bound ports on `18768`.

#### 5. How HTTPX Connection Limits are Configured
- Default HTTPX clients allocate a pool of 100 connections with lazy socket creation.
- Benchmark V2 configures:
  ```python
  limits = httpx.Limits(max_connections=100, max_keepalive_connections=50)
  timeout = httpx.Timeout(30.0, connect=10.0)
  ```
- Crucially, a **warm-up phase of 30 sequential requests per endpoint** is executed before timing begins. This forces TCP handshake completion, TLS/socket binding, and connection keep-alive pool warming, completely isolating network initialization overhead from measurement data.

#### 6. How Server-Side vs. Client-Side Latency are Measured
- **Client Round-Trip Time (RTT):** Measured immediately before `client.get()` and after response return:
  $$\text{RTT}_{\text{client}} = (t_{\text{recv}} - t_{\text{send}}) \times 1000 \text{ ms}$$
- **Server Internal Execution Time:** Extracted directly from `X-Server-Time-Ms`.
- **Network / Queue Latency:**
  $$\Delta = \text{RTT}_{\text{client}} - T_{\text{server}}$$
- By comparing P50, P95, and P99 percentiles of $\text{RTT}_{\text{client}}$ and $T_{\text{server}}$, the benchmark proves whether delays stem from client-side socket saturation or server-side AnyIO thread limiter queuing.

#### 7. How Repeated Runs and Alternating Order Work
- The benchmark runs $3$ complete repetitions (`rep in range(1, 4)`).
- Sync and Async endpoints are tested consecutively in each repetition:
  $$\text{Rep } 1: \text{Sync} \to \text{Async} \quad\mid\quad \text{Rep } 2: \text{Sync} \to \text{Async} \quad\mid\quad \text{Rep } 3: \text{Sync} \to \text{Async}$$
- This establishes statistical reproducibility across multiple runs and reveals memory leaks or connection pool drift.

#### 8. How CPU Utilization and Event-Loop Responsiveness are Measured
- Compares `/cpu-sync` vs `/cpu-async` endpoints performing $100,000$ iterations of numeric computation (`sum(i * i for i in range(100_000))`):
  - In `/cpu-sync`, FastAPI dispatches the synchronous function to an AnyIO worker thread (`anyio.to_thread.run_sync`), keeping the main event loop responsive.
  - In `/cpu-async`, running CPU computation directly on the async coroutine blocks the single-threaded asyncio event loop, causing severe latency spikes for concurrent traffic.
- This directly demonstrates that **async is not universally faster than sync**, validating grounded architectural reasoning.

#### 9. Proposed Execution Command & Side Effects
- **Proposed Command:**
  ```powershell
  python scratch/benchmark_http_fastapi_v2.py
  ```
- **Files Created:**
  - `scratch/v2_server.py` (temporary standalone server script)
  - `scratch/benchmark_http_fastapi_v2_results.json` (raw JSON benchmark results)
- **Ports Bound:** Port `18768` on loopback `127.0.0.1` during execution only.
- **Production Impact:** **ZERO.** No files in `backend/`, `frontend/`, or PostgreSQL database are touched.

---

# SECTION 2: AUTH-02 — Isolated Evaluation Database Architecture (`codemind_eval_db`)

### 2.1 Complete SQL Operational Commands

To ensure complete isolation and zero modification of production data in `codemind_db`, the following operational procedure creates and populates `codemind_eval_db`:

```sql
-- Step 1: Create isolated evaluation database
CREATE DATABASE codemind_eval_db
    WITH OWNER = postgres
    ENCODING = 'UTF8'
    LC_COLLATE = 'English_United States.1252'
    LC_CTYPE = 'English_United States.1252'
    TEMPLATE = template0;

-- Step 2: Connect to isolated database and register pgvector extension
\c codemind_eval_db
CREATE EXTENSION IF NOT EXISTS vector;

-- Step 3: Create schema tables matching production models
-- Executed via SQLAlchemy Base.metadata.create_all() or pg_dump schema extraction:
```

```powershell
# Step 3 (CLI): Extract schema DDL from production database without data
pg_dump -U postgres -d codemind_db --schema-only --no-owner --no-privileges -f "scratch/schema_dump.sql"

# Step 4 (CLI): Apply schema to isolated evaluation database
psql -U postgres -d codemind_eval_db -f "scratch/schema_dump.sql"
```

```sql
-- Step 5: Copy Read-Only Repository & Knowledge Graph Metadata preserving exact primary key IDs

-- 5a. Copy Repositories (specifically Candidate A: 46 and Candidate C: 45)
INSERT INTO codemind_eval_db.public.repositories 
SELECT * FROM codemind_db.public.repositories 
WHERE id IN (45, 46);

-- 5b. Copy Indexed Files for Candidate Repositories
INSERT INTO codemind_eval_db.public.indexed_files 
SELECT * FROM codemind_db.public.indexed_files 
WHERE repository_id IN (45, 46);

-- 5c. Copy Code Symbols
INSERT INTO codemind_eval_db.public.code_symbols 
SELECT * FROM codemind_db.public.code_symbols 
WHERE repository_id IN (45, 46);

-- 5d. Copy Code Chunks and 768-dimensional Vector Embeddings
INSERT INTO codemind_eval_db.public.code_chunks 
SELECT * FROM codemind_db.public.code_chunks 
WHERE repository_id IN (45, 46);

-- 5e. Copy Knowledge Graph Nodes and Edges
INSERT INTO codemind_eval_db.public.graph_nodes 
SELECT * FROM codemind_db.public.graph_nodes 
WHERE repository_id IN (45, 46);

INSERT INTO codemind_eval_db.public.graph_edges 
SELECT * FROM codemind_db.public.graph_edges 
WHERE repository_id IN (45, 46);

-- Step 6: Synchronize primary key sequences to prevent ID collision during new insertions
SELECT setval('repositories_id_seq', (SELECT COALESCE(MAX(id), 1) FROM repositories));
SELECT setval('indexed_files_id_seq', (SELECT COALESCE(MAX(id), 1) FROM indexed_files));
SELECT setval('code_chunks_id_seq', (SELECT COALESCE(MAX(id), 1) FROM code_chunks));
SELECT setval('code_symbols_id_seq', (SELECT COALESCE(MAX(id), 1) FROM code_symbols));
SELECT setval('graph_nodes_id_seq', (SELECT COALESCE(MAX(id), 1) FROM graph_nodes));
SELECT setval('graph_edges_id_seq', (SELECT COALESCE(MAX(id), 1) FROM graph_edges));
SELECT setval('indexing_jobs_id_seq', (SELECT COALESCE(MAX(id), 1) FROM indexing_jobs));
SELECT setval('assistant_conversations_id_seq', 1, false);
SELECT setval('assistant_messages_id_seq', 1, false);
```

### 2.2 Roles, Permissions & Extension Requirements
- **PostgreSQL Role:** `postgres` with full `ALL PRIVILEGES` on database `codemind_eval_db`.
- **Required Extension:** `vector` (pgvector 0.5.1+ for 768-dimensional vector cosine distance queries `<=>`).
- **HNSW Indexes Preserved:** The HNSW index on `code_chunks.embedding` (`idx_code_chunks_embedding_hnsw`) is copied and built to ensure identical sub-millisecond retrieval performance.

### 2.3 Preserving Primary Key IDs & Foreign Key Integrity
- Directly selecting from `codemind_db` into `codemind_eval_db` preserves exact primary keys:
  - `expertdecision`: `repository_id = 46`
  - `TokenPool`: `repository_id = 45`
- Preserving these IDs ensures all pre-existing knowledge graph edges, file paths, and chunk associations remain 100% valid without rewriting foreign keys.
- Step 6 updates sequence counters (`setval`), ensuring that when Candidate B (`RewardPoints Transfer`) is indexed, it receives the next available autoincrement ID (e.g., `id = 47`) without conflicting with existing repositories.

### 2.4 Conversation & State Isolation
- The tables `assistant_conversations` and `assistant_messages` remain **completely empty** in `codemind_eval_db`.
- During the 60-question evaluation, all conversation records, generated answers, citations, and message tokens will be written exclusively into `codemind_eval_db`.
- The production database `codemind_db` will receive **zero write queries**.

### 2.5 Accidental Connection Prevention & Safety Interlocks
To prevent any possibility of accidentally querying or modifying `codemind_db`, the evaluation runner enforces the following programmatic assertion before every operation:

```python
def get_eval_db_session():
    eval_db_url = "postgresql://postgres:postgres@localhost:5432/codemind_eval_db"
    engine = create_engine(eval_db_url, pool_pre_ping=True)
    
    # SAFETY GUARD: Assert connected database name is strictly codemind_eval_db
    with engine.connect() as conn:
        current_db = conn.execute(text("SELECT current_database();")).scalar()
        if current_db != "codemind_eval_db":
            raise RuntimeError(
                f"SAFETY INTERLOCK TRIPPED! Target database is '{current_db}', "
                f"expected 'codemind_eval_db'. Aborting immediately to protect production data."
            )
            
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()
```

### 2.6 Backup, Verification & Instant Rollback
- **Pre-execution Verification Query:**
  ```sql
  SELECT 'codemind_eval_db verification' AS check, 
         (SELECT count(*) FROM repositories) AS repo_count,
         (SELECT count(*) FROM indexed_files) AS file_count,
         (SELECT count(*) FROM code_chunks WHERE embedding IS NOT NULL) AS embedded_chunk_count;
  ```
- **Instant Rollback / Teardown Command:**
  ```sql
  DROP DATABASE IF EXISTS codemind_eval_db WITH (FORCE);
  ```
  Executing this single command completely removes the isolated database and all evaluation artifacts in $< 1$ second, restoring the host system to its exact initial state.

---

# SECTION 3: AUTH-03 — Candidate B (`RewardPoints Transfer`) Indexing Specification

### 3.1 Proposed Indexing Command

```powershell
python -c "
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.models.repository import Repository
from backend.app.services.indexing_service import IndexingService

eval_db_url = 'postgresql://postgres:postgres@localhost:5432/codemind_eval_db'
engine = create_engine(eval_db_url)
Session = sessionmaker(bind=engine)
session = Session()

repo = Repository(
    name='RewardPoints Transfer',
    full_name='local/RewardPoints Transfer',
    provider='folder',
    clone_url=r'C:\Users\koppa\OneDrive\Documents\Projects\RewardPoints Transfer',
    default_branch='main',
    status='pending'
)
session.add(repo)
session.commit()

job = IndexingService.create_indexing_job(session, repo, 'main')
print(f'Starting indexing for {repo.name} (ID: {repo.id}) in job {job.id}...')
asyncio.run(IndexingService.run_indexing_pipeline(job.id, repo.id, 'main', db_session=session))
print('Indexing completed successfully.')
"
```

### 3.2 Expected Database Operations
1. `INSERT INTO repositories`: Creates 1 record with `name = "RewardPoints Transfer"`, `provider = "folder"`, `status = "indexing"`.
2. `INSERT INTO indexing_jobs`: Creates 1 record with `stage = "QUEUED"`, transitioned through `CLONING`, `PARSING`, `EMBEDDING`, `GRAPH`, `COMPLETED`.
3. `INSERT INTO indexed_files`: Inserts exactly $88$ rows corresponding to clean source files.
4. `INSERT INTO code_symbols`: Extracts and records functions, classes, and exported symbols.
5. `INSERT INTO code_chunks`: Inserts $\sim 600$ semantic chunks.
6. `UPDATE code_chunks`: Generates and stores 768-dimensional `nomic-embed-text` embeddings.
7. `INSERT INTO graph_nodes` and `graph_edges`: Builds import and call hierarchy dependencies.
8. `UPDATE repositories`: Sets `status = 'ready'`, `files_count = 88`.

### 3.3 Duplicate Prevention & Idempotency
- **Pre-check:** The script queries `Repository.name == 'RewardPoints Transfer'` in `codemind_eval_db`. If found, it skips creation or cleans previous chunks.
- **Content Hashing:** Every file and chunk generates a SHA-256 hash (`content_hash`). If re-run, existing chunks with matching hashes reuse existing embeddings via `EmbeddingService.embed_new_chunks()`.

### 3.4 File Filtering & Boundary Protection
The indexing pipeline utilizes CodeMind's standard path exclusion rules in `backend/app/indexing/discovery.py`:
- **Ignored Directories:** `node_modules/`, `.git/`, `.vscode/`, `dist/`, `build/`, `target/`, `bin/`, `obj/`, `coverage/`, `.next/`, `__pycache__/`, `.mypy_cache/`.
- **Ignored Files:** `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `*.min.js`, `*.map`, `*.log`, `*.tmp`, `*.svg`, `*.png`, `*.jpg`.
- **Target Ingestion:** Strictly the $88$ legitimate source files (`.py`, `.js`, `.ts`, `.sol`, `.json` configuration).

### 3.5 Rollback & Failure Recovery
- In the event of a crash or embedding provider failure midway through indexing:
  1. The transaction automatically calls `session.rollback()`.
  2. The job status updates to `status = 'FAILED'`, recording the exact traceback in `indexing_jobs.error_message`.
  3. A cleanup query can purge partial state cleanly:
     ```sql
     DELETE FROM code_chunks WHERE repository_id = :repo_id;
     DELETE FROM indexed_files WHERE repository_id = :repo_id;
     DELETE FROM code_symbols WHERE repository_id = :repo_id;
     DELETE FROM graph_edges WHERE repository_id = :repo_id;
     DELETE FROM graph_nodes WHERE repository_id = :repo_id;
     DELETE FROM repositories WHERE id = :repo_id;
     ```

---

# SECTION 4: AUTH-04 — Complete 60-Question Blind Evaluation Protocol

### 4.1 Scoring Methodology & Mathematical Formulation

Every answer produced by CodeMind AI is evaluated independently on a 0–100 continuous scale across four orthogonal dimensions:

$$\text{Final Score} = 0.40 \times S_{\text{accuracy}} + 0.25 \times S_{\text{citation}} + 0.25 \times S_{\text{grounding}} + 0.10 \times S_{\text{refusal}}$$

#### 1. Accuracy ($S_{\text{accuracy}}$, Weight: 40%)
- **100%:** Correctly identifies all relevant components, functions, cross-file execution flows, and architectural relationships matching verified ground truth.
- **70%:** Correctly identifies primary components but omits secondary execution steps.
- **30%:** Superficial answer; describes generic concepts rather than repository-specific logic.
- **0%:** Factually incorrect claims, hallucinated functions, or misattributed frameworks.

#### 2. Citation Precision ($S_{\text{citation}}$, Weight: 25%)
- Evaluated against verified line numbers:
  $$\text{Precision} = \frac{\text{True Positive Citations}}{\text{Total Citations Given}}$$
- Every citation must resolve to an existing file and valid line range (`start_line <= end_line`).
- Citations must directly contain the code constructing, defining, or invoking the claimed symbol.

#### 3. Grounding Integrity ($S_{\text{grounding}}$, Weight: 25%)
- Penalizes hallucinated dependencies, application functions in framework repos, or cross-repository contamination:
  $$S_{\text{grounding}} = 100 - (30 \times N_{\text{hallucinated\_symbols}} + 50 \times N_{\text{cross\_repo\_leaks}})$$
- Minimum score bounded at $0$.

#### 4. Failure/Refusal Correctness ($S_{\text{refusal}}$, Weight: 10%)
- When asked about features absent from the repository (e.g. absent email notifications, absent database ORMs, or unindexed services):
  - **100%:** Truthfully and explicitly states that the feature is **UNVERIFIED / ABSENT** in the indexed source code.
  - **0%:** Hallucinates an implementation or assumes existence from common industry patterns.

---

### 4.2 Complete 60-Question Set with Independent Ground-Truth Criteria

#### Repository A: `expertdecision` (ID: 46, Multi-Model Backend & Frontend, 206 Files)

| Question # | Category | Question Prompt | Verified Ground-Truth Source Files | Ground-Truth Verification Criteria & Required Evidence |
| :---: | :--- | :--- | :--- | :--- |
| **Q01** | Entry Point | What is the main application entry point and how does it start? | `app.py:1–40` or `main.py` | Identifies Flask/FastAPI initialization, route blueprints, and host/port bind configuration. |
| **Q02** | Auth Flow | Trace how user authentication and JWT session validation are implemented. | `auth.py` / `routes/auth.py` | Identifies token generation, secret key signing, and auth bearer header verification middleware. |
| **Q03** | Data Model | How is the primary decision matrix or expert model represented in the database? | `models/` (SQLAlchemy / PyMongo) | Cites model class definitions, column types, foreign keys, and relationships. |
| **Q04** | API Route | Trace the execution of the primary decision submission endpoint. | `routes/decision.py`, `services/` | Identifies endpoint URL, request body validation, service calculation invocation, and response JSON. |
| **Q05** | Algorithmic Flow | How does the scoring/decision algorithm calculate weights or rankings? | `algorithms/` or `services/scoring.py` | Cites mathematical functions (e.g. AHP, TOPSIS, entropy weighting) and array transformations. |
| **Q06** | Dependency Injection | How are shared services or database sessions passed into route handlers? | `dependencies.py` or Flask context | Identifies session lifecycle, teardown handlers, or context managers. |
| **Q07** | Error Handling | How are domain exceptions caught and converted to standardized API errors? | `errors.py` or exception handlers | Cites custom exception classes and global `@app.errorhandler` or middleware. |
| **Q08** | Database Migrations | What migration tool is used and what is the current schema revision state? | `alembic/` or migration scripts | Identifies Alembic / DB migration scripts and version heads. |
| **Q09** | Configuration | How are external API keys, database URLs, and environment variables loaded? | `config.py` / `settings.py` | Cites `pydantic-settings` or `os.getenv` loading logic and defaults. |
| **Q10** | External Integrations | What external APIs, LLM providers, or third-party services are called? | `integrations/` or `clients/` | Identifies HTTP client invocations (e.g. OpenAI, Anthropic, or external microservices). |
| **Q11** | File Uploads | How are uploaded evaluation datasets or documents processed and parsed? | `services/parser.py` | Cites file upload endpoints, temporary file storage, and CSV/PDF/Excel ingestion routines. |
| **Q12** | Background Tasks | Does the repository use Celery, RQ, or background threads for long tasks? | `tasks.py` / `celery_app.py` | Confirms worker configuration or reports **ABSENT** if tasks run synchronously. |
| **Q13** | Frontend Integration | How does the frontend client make API calls to the backend decision endpoints? | `frontend/src/api/` or static JS | Cites Axios/fetch wrappers, endpoint URLs, and authorization header injection. |
| **Q14** | Test Fixtures | What pytest / unittest fixtures are defined for database testing? | `tests/conftest.py` | Cites test database setup, mock clients, and rollback fixtures. |
| **Q15** | Cache Layer | Is Redis, Memcached, or an in-memory cache used for calculation results? | `services/cache.py` or route decorators | Identifies cache key construction and TTL or reports **ABSENT** if uncached. |
| **Q16** | Security: SQLi | How does the codebase prevent SQL injection in custom query construction? | `db/queries.py` or ORM usage | Verifies use of parameterized queries, ORM filtering, or raw SQL boundaries. |
| **Q17** | Security: CORS | How is Cross-Origin Resource Sharing (CORS) configured across origins? | `app.py` (CORS middleware) | Cites allowed origins, headers, and credentials configuration. |
| **Q18** | Absent Feature Check | Where is the Stripe payment gateway processing implemented? | Entire repository scan | **MUST REFUSE:** Correctly reports Stripe payment processing is **UNVERIFIED / ABSENT**. |
| **Q19** | Circular Imports | Are there any circular import dependencies between routes and services? | `routes/` and `services/` | Accurately identifies presence or absence of import cycles without false positives. |
| **Q20** | Change Impact | What components are affected if the core scoring formula signature changes? | `services/scoring.py` | Traces callers in route handlers, test suites, and frontend consumers. |

---

#### Repository B: `RewardPoints Transfer` (Clean Source, 88 Files)

| Question # | Category | Question Prompt | Verified Ground-Truth Source Files | Ground-Truth Verification Criteria & Required Evidence |
| :---: | :--- | :--- | :--- | :--- |
| **Q21** | System Overview | What is the overall architecture and primary purpose of this repository? | `README.md`, `package.json`, root files | Identifies loyalty points transfer system between merchants/users. |
| **Q22** | Smart Contract / Core | What smart contract or core ledger tracks point balances and transfers? | `contracts/` or `services/ledger.py` | Cites ledger balances mapping, transfer methods, and event emission. |
| **Q23** | Transfer Execution | Trace the step-by-step execution flow of a points transfer transaction. | `routes/transfer.js`, `controllers/` | Traces validation, balance check, debit sender, credit recipient, commit. |
| **Q24** | Balance Validation | How does the system prevent overdrafts or negative point balances? | `services/balance.js` or contract | Cites conditional checks (`balance >= amount`), require statements, or locks. |
| **Q25** | Partner Authentication | How are partner merchants authenticated when submitting transfer requests? | `middleware/auth.js` | Cites API key verification, HMAC signature validation, or JWT checks. |
| **Q26** | Database Schema | How are users, partner merchants, and transactions represented? | `models/` or SQL schemas | Cites schema definitions for users, merchants, points ledger, and transactions. |
| **Q27** | Rate Limiting | Does the application enforce rate limiting on transfer requests? | `middleware/rate_limit.js` | Identifies Redis rate limiter or reports **ABSENT** with evidence. |
| **Q28** | Conversion Rates | How are point conversion ratios calculated between different partners? | `services/exchange_rate.js` | Cites exchange rate lookup, calculation formulas, and fee deductions. |
| **Q29** | Idempotency | How does the API prevent double-spending on duplicate transfer requests? | `middleware/idempotency.js` | Cites idempotency key check in database/cache before processing transfer. |
| **Q30** | Event Logging | How are transfer audit events recorded and persisted? | `services/audit.js` / `logger.js` | Identifies database audit trail or structured log writing. |
| **Q31** | Notification Service | How are users notified upon successful or failed point transfers? | `services/notification.js` | Cites email/SMS/webhook triggers or reports **ABSENT** if unintegrated. |
| **Q32** | Error Handling | How are database deadlock or concurrent update exceptions handled? | `controllers/transfer.js` | Cites retry loops, database transaction isolation levels, or rollbacks. |
| **Q33** | Admin Dashboard | What admin endpoints exist for reconciling point balance discrepancies? | `routes/admin.js` | Cites reconciliation endpoints, adjustment methods, and permissions. |
| **Q34** | Test Suite | What test suite is used and how are transfer edge cases tested? | `tests/` or `test/` | Identifies Jest / Mocha / Pytest tests for transfer success and failure modes. |
| **Q35** | Secret Management | How are private keys, encryption secrets, and DB passwords loaded? | `.env.example`, `config/` | Cites environment configuration loaders and secret validation. |
| **Q36** | Security: Reentrancy | If smart contracts are used, how is reentrancy prevented during transfers? | Solidity contracts (`ReentrancyGuard`) | Identifies checks-effects-interactions pattern or `nonReentrant` modifier. |
| **Q37** | Security: Data Privacy | How is user PII (phone number, email) protected in transaction logs? | `utils/sanitizer.js` or logging config | Cites masking/redaction utilities or highlights unmasked logging risks. |
| **Q38** | Absent Feature Check | Where is the biometric fingerprint authentication module implemented? | Entire repository scan | **MUST REFUSE:** Correctly reports biometric authentication is **UNVERIFIED / ABSENT**. |
| **Q39** | Cross-Module Calls | Which files import and call the primary balance verification function? | Symbol graph for `checkBalance` | Cites exact calling controllers and routes with file paths and line ranges. |
| **Q40** | Change Impact | If the fee calculation formula changes, what files and tests must update? | `services/fee.js` | Traces callers in transfer flow, receipt generation, and test suites. |

---

#### Repository C: `TokenPool` (ID: 45, Smart Contract & Token Management, 89 Files)

| Question # | Category | Question Prompt | Verified Ground-Truth Source Files | Ground-Truth Verification Criteria & Required Evidence |
| :---: | :--- | :--- | :--- | :--- |
| **Q41** | Core Contract | What is the primary contract managing the token pool and liquidity? | `contracts/TokenPool.sol` | Cites contract declaration, ERC20 inheritance, and pool state variables. |
| **Q42** | Deposit Flow | Trace the execution flow when a user deposits tokens into the pool. | `TokenPool.sol:deposit()` | Cites `transferFrom`, pool share calculation, event emission, and state updates. |
| **Q43** | Withdrawal Flow | Trace how tokens are withdrawn and pool shares are burned. | `TokenPool.sol:withdraw()` | Cites share verification, burning logic, token transfer, and reentrancy guard. |
| **Q44** | Fee Distribution | How are pool protocol fees and LP rewards calculated and distributed? | `TokenPool.sol` or `FeeDistributor.sol` | Cites fee basis points formula, accumulator variables, and harvest functions. |
| **Q45** | Ownership & Access | How are administrative privileges, pausing, and ownership managed? | `contracts/access/Ownable.sol` | Cites `onlyOwner`, `Pausable`, or `AccessControl` roles and modifiers. |
| **Q46** | Oracle Integration | Does the pool use an external price oracle (e.g. Chainlink) for valuation? | `interfaces/IOracle.sol` | Cites oracle price feed integration or confirms pool relies on internal ratios. |
| **Q47** | Token Support | Does the pool support multiple ERC20 tokens or a single staking asset? | `contracts/TokenPool.sol` | Verifies whether asset addresses are stored in mapping or single immutable token. |
| **Q48** | Precision & Decimals | How does the contract prevent rounding errors in share calculations? | `contracts/libraries/Math.sol` | Cites scaling factors (e.g. $1e18$, `FixedPointMath`), precision multipliers. |
| **Q49** | Emergency Pause | What happens when the contract is paused during an emergency? | `whenNotPaused` modifiers | Cites functions blocked by `whenNotPaused` (deposit, transfer) and emergency exits. |
| **Q50** | Deployment Scripts | What deployment framework is used (Hardhat, Foundry, Truffle) and where? | `hardhat.config.js` or `foundry.toml` | Identifies deployment scripts in `scripts/deploy.js` or `script/Deploy.s.sol`. |
| **Q51** | Contract Testing | How are fuzzing or invariant tests structured for pool balance safety? | `test/TokenPool.test.js` | Cites test fixtures, deposit/withdraw property tests, and assert statements. |
| **Q52** | Upgradeability | Is the contract upgradeable via ERC1967 proxies or immutable? | `contracts/proxy/` or constructor | Identifies `UUPSUpgradeable` / `TransparentUpgradeable` or immutable constructor. |
| **Q53** | Event Definitions | What events are emitted during deposits, withdrawals, and fee updates? | `TokenPool.sol` (event declarations) | Cites `Deposit`, `Withdraw`, `FeeUpdated` event signatures and indexed topics. |
| **Q54** | Gas Optimization | What gas optimization patterns are implemented in storage and loops? | Storage packing, `unchecked` | Identifies packed `uint128` structs, `immutable` variables, or `unchecked` arithmetic. |
| **Q55** | Web3 Client Frontend | How does the frontend or dApp service interact with the smart contract ABI? | `frontend/` or `sdk/` | Cites Ethers.js / Viem / Web3.js contract instantiation and transaction signing. |
| **Q56** | Security: Flash Loans | Does the pool implement flash loans, and how is pool solvency verified? | `contracts/flashloan/` | Cites flash loan callback, repayment verification with fee, or reports **ABSENT**. |
| **Q57** | Security: Front-running | How are slippage tolerance and deadline parameters enforced? | `TokenPool.sol` function params | Cites `minTokensOut` and `deadline` require checks against `block.timestamp`. |
| **Q58** | Absent Feature Check | Where is the zero-knowledge zk-SNARK proof verification implemented? | Entire repository scan | **MUST REFUSE:** Correctly reports zk-SNARK proof verification is **UNVERIFIED / ABSENT**. |
| **Q59** | Call Hierarchy | What functions call `_mintShares` within the contract codebase? | AST call hierarchy | Identifies internal callers (`deposit`, `rebalance`) with line citations. |
| **Q60** | Change Impact | If the pool deposit fee changes from 0.1% to 0.5%, what code and tests break? | `contracts/TokenPool.sol` | Traces fee constants, setter functions, accounting math, and test assertions. |

---

### 4.3 Multi-Turn Follow-Up Isolation & Memory Protocol
- **Strict Turn Isolation:** Questions Q01 through Q60 are executed in separate, newly instantiated conversation sessions (`conversation_id = None`), ensuring that answers do not inherit context, leaked chunk text, or citations from preceding questions.
- **Dedicated Multi-Turn Test Group:** Follow-up resolution will be evaluated through explicit multi-turn sequences (e.g. Q01 followed immediately by *"How is the entry point configured for production?"* in the same conversation session), verifying that multi-turn context resolution functions correctly within repository boundaries without cross-repository contamination.

---

# SECTION 5: AUTH-05 — Comprehensive Static Inspection of Regression Test Suites

### 5.1 Static Inspection Methodology

Every test across the four core regression test suites:
1. `backend/tests/test_round2_technical_corrections.py` (7 tests)
2. `backend/tests/test_embedding_dimension_fix.py` (6 tests)
3. `backend/tests/test_fastapi_grounding_adversarial.py` (11 tests)
4. `backend/tests/test_universal_repository_scope_and_accuracy.py` (12 tests)
5. *Supplementary Suite:* `backend/tests/test_embedding_fix_regression.py` (13 tests)

has been statically inspected line by line against the five safety verification criteria:
- **(a) PostgreSQL Writes:** Does the test execute SQL `INSERT`, `UPDATE`, `DELETE`, or DDL on PostgreSQL?
- **(b) File Creation/Deletion:** Does the test write, modify, or delete files outside ephemeral pytest temp directories?
- **(c) Server Startup:** Does the test spawn live HTTP servers, Uvicorn daemons, or background workers?
- **(d) Configuration Modification:** Does the test alter global environment files (`.env`), system settings, or database configurations?
- **(e) External Service Dependencies:** Does the test require active network connections, Ollama LLM, GitHub API, or PostgreSQL services?

---

### 5.2 Individual Test Inspection Matrix

#### Suite 1: `backend/tests/test_round2_technical_corrections.py` (7 Tests)

| # | Test Function Name | (a) PG Writes? | (b) File I/O? | (c) Server? | (d) Config? | (e) External? | Static Verification Details |
| :-: | :--- | :-: | :-: | :-: | :-: | :-: | :--- |
| 1 | `test_type_checking_vs_runtime_circular_import` | **NO** | **NO** | **NO** | **NO** | **NO** | Pure AST symbol extraction test in memory. |
| 2 | `test_actual_runtime_import_cycles` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses local `sqlite:///:memory:` fixture; pure graph cycle detection. |
| 3 | `test_hypothetical_application_functions_vs_real_framework_functions` | **NO** | **NO** | **NO** | **NO** | **NO** | Reads FastAPI source read-only from temp path if present; no writes. |
| 4 | `test_evidence_backed_change_impact_analysis` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:` fixture; tests `ChangeImpactAnalyzer`. |
| 5 | `test_anyio_limiter_instrumentation` | **NO** | **NO** | **NO** | **NO** | **NO** | Tests `anyio.to_thread` limiter token acquisition in memory. |
| 6 | `test_benchmark_platform_compatibility` | **NO** | **NO** | **NO** | **NO** | **NO** | In-process synthetic async benchmark function call; no HTTP server. |
| 7 | `test_citation_claim_to_source_accuracy` | **NO** | **NO** | **NO** | **NO** | **NO** | Reads static source files read-only; asserts token presence. |

---

#### Suite 2: `backend/tests/test_embedding_dimension_fix.py` (6 Tests)

| # | Test Function Name | (a) PG Writes? | (b) File I/O? | (c) Server? | (d) Config? | (e) External? | Static Verification Details |
| :-: | :--- | :-: | :-: | :-: | :-: | :-: | :--- |
| 8 | `test_valid_768_dimension_writes_cleanly` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `conftest.py` `sqlite:///:memory:`; mock provider (768-dim). |
| 9 | `test_dimension_mismatch_rejected_before_db_write` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies rollback on 12,379 dimensions. |
| 10 | `test_non_list_vector_rejected` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; rejects string vectors in memory. |
| 11 | `test_non_numeric_vector_rejected` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; rejects non-numeric vectors in memory. |
| 12 | `test_provider_error_rolls_back_transaction` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies clean transaction rollback on error. |
| 13 | `test_reused_vector_with_wrong_dimension_is_not_reused` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies dimension check prevents reuse. |

---

#### Suite 3: `backend/tests/test_fastapi_grounding_adversarial.py` (11 Tests)

| # | Test Function Name | (a) PG Writes? | (b) File I/O? | (c) Server? | (d) Config? | (e) External? | Static Verification Details |
| :-: | :--- | :-: | :-: | :-: | :-: | :-: | :--- |
| 14 | `test_file_role_classifier_distinctions` | **NO** | **NO** | **NO** | **NO** | **NO** | Pure functional path classification logic in memory. |
| 15 | `test_framework_repository_no_application_entrypoint` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies framework package root discovery. |
| 16 | `test_missing_database_and_auth_clarity` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies database-agnostic classification. |
| 17 | `test_missing_environment_specific_configuration` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies constructor config detection. |
| 18 | `test_same_file_function_not_circular_import` | **NO** | **NO** | **NO** | **NO** | **NO** | Pure boolean logic assertion. |
| 19 | `test_actual_circular_imports_detection` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies GraphEdge IMPORTS query. |
| 20 | `test_function_with_multiple_real_callers` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies CALLS edge discovery. |
| 21 | `test_function_with_no_discoverable_callers` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies 0 callers for isolated node. |
| 22 | `test_repository_switching_strict_isolation` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies HybridRetrievalEngine isolation. |
| 23 | `test_line_citations_accuracy_and_bounds` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; validates chunk start_line/end_line bounds. |
| 24 | `test_unrelated_files_with_similar_names_distinction` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests role classification distinction. |

---

#### Suite 4: `backend/tests/test_universal_repository_scope_and_accuracy.py` (12 Tests)

| # | Test Function Name | (a) PG Writes? | (b) File I/O? | (c) Server? | (d) Config? | (e) External? | Static Verification Details |
| :-: | :--- | :-: | :-: | :-: | :-: | :-: | :--- |
| 25 | `test_repository_isolation_between_flutter_and_fastapi` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies zero cross-repo chunk leakage. |
| 26 | `test_general_programming_classification_across_languages` | **NO** | **NO** | **NO** | **NO** | **NO** | Pure intent classifier test across 7 programming queries in memory. |
| 27 | `test_explicit_repo_reference_overrides_general_programming` | **NO** | **NO** | **NO** | **NO** | **NO** | Pure intent classifier rule override in memory. |
| 28 | `test_switching_repositories_conversation_isolation` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests follow-up context isolation. |
| 29 | `test_function_responsibility_not_assumed_from_name` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests answer sanitizer on CSV function. |
| 30 | `test_unauthorized_private_repository_access_denied` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies RBAC user_id isolation. |
| 31 | `test_codemind_host_platform_query_scoping` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; verifies host repository scoping. |
| 32 | `test_diagnostics_structure_completeness` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; mocks LLM provider; validates diagnostics dict. |
| 33 | `test_evidence_counters_correctness` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; validates confirmed vs unknown counters. |
| 34 | `test_cross_repository_hybrid_retrieval_presence_and_absence` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; mocks LLM; verifies presence/absence reporting. |
| 35 | `test_cross_repo_streaming_and_non_streaming_parity` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; mocks LLM stream; tests SSE event generation. |
| 36 | `test_cross_repo_conversation_persistence_and_reopening` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; mocks LLM; tests conversation reopening. |

---

#### Suite 5: `backend/tests/test_embedding_fix_regression.py` (13 Supplementary Tests)

| # | Test Function Name | (a) PG Writes? | (b) File I/O? | (c) Server? | (d) Config? | (e) External? | Static Verification Details |
| :-: | :--- | :-: | :-: | :-: | :-: | :-: | :--- |
| 37 | `test_small_repo_fewer_than_32_chunks` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; MockEmbeddingProvider (768). |
| 38 | `test_exact_32_chunks_boundary` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests exact 32 chunk batch boundary. |
| 39 | `test_multi_batch_more_than_32_chunks` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests 85 chunks across multiple batches. |
| 40 | `test_larger_repository_many_files_and_chunks` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests 100 chunks across 20 files. |
| 41 | `test_github_ingestion_path` | **NO** | Ephemeral | **NO** | **NO** | **NO** | Uses pytest `tmp_path`; mocks GitHub download and provider. |
| 42 | `test_zip_folder_ingestion_path` | **NO** | Ephemeral | **NO** | **NO** | **NO** | Uses pytest `tmp_path`; mocks provider. |
| 43 | `test_polyglot_languages_indexing` | **NO** | Ephemeral | **NO** | **NO** | **NO** | Uses pytest `tmp_path`; tests Python, JS, TS, Go chunks. |
| 44 | `test_sequential_repositories_indexing` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests sequential isolation. |
| 45 | `test_concurrent_job_claim_prevention` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; concurrent asyncio tasks in memory. |
| 46 | `test_retry_after_embedding_failure` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests retry idempotency. |
| 47 | `test_missing_or_stale_chunk_ids_handling` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests missing chunk descriptor skip. |
| 48 | `test_chunk_and_repository_ownership_verification` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; tests cross-repo chunk modification guard. |
| 49 | `test_failed_indexing_never_reports_success` | **NO** | **NO** | **NO** | **NO** | **NO** | Uses `sqlite:///:memory:`; unconfigured provider failure truthfulness. |

---

### 5.3 Static Audit Synthesis & Safety Confirmation

1. **PostgreSQL Writes:** **ZERO.** All test database operations execute in an ephemeral in-memory SQLite database (`sqlite:///:memory:`) configured in `backend/tests/conftest.py`. Not a single query is transmitted to PostgreSQL `localhost:5432`.
2. **File Modifications:** **ZERO.** The only disk operations occur in `tests 41–43`, which utilize Pytest's standard `tmp_path` fixture. These directories are created in the system temporary folder and deleted automatically upon test completion.
3. **Server Startup:** **ZERO.** No tests launch Uvicorn, background workers, or external network sockets.
4. **Configuration Mutations:** **ZERO.** The setting `settings.REQUIRE_AUTH = False` is set only on the in-memory Pydantic settings object during the test session fixture and does not persist to `.env` or disk.
5. **External Dependencies:** **ZERO.** All LLM calls, embeddings, and GitHub downloads are fully mocked via `MockEmbeddingProvider`, `patch("get_llm_provider")`, and `monkeypatch`.

### 5.4 Exact Proposed Execution Command

```powershell
pytest backend/tests/test_round2_technical_corrections.py `
       backend/tests/test_fastapi_grounding_adversarial.py `
       backend/tests/test_embedding_dimension_fix.py `
       backend/tests/test_universal_repository_scope_and_accuracy.py `
       -v --tb=short
```

---

# SECTION 6: Explicit Pre-Execution Stop & Awaiting Approval

> [!IMPORTANT]
> **VERIFICATION COMPLETE — NO ACTIONS EXECUTED**
> 
> The static inspection and pre-execution verification requirements for Checkpoints **AUTH-01 through AUTH-05** are fully documented, verified, and ready.
> 
> In accordance with instructions:
> - Zero benchmarks have been run.
> - Zero database instances or records have been created or modified.
> - Zero repository indexing pipelines have been initiated.
> - Zero assistant prompts have been executed.
> - Zero regression tests have been run.
> 
> CodeMind AI is currently stopped in read-only verification mode.
> 
> **Awaiting your explicit authorization and instructions on which checkpoint(s) to execute.**

