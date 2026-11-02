# Phase 1: Benchmark Investigation & Static Code Audit

**Target Files Inspected:**
- `scratch/benchmark_anyio_dependency.py`
- `scratch/benchmark_http_fastapi.py`

**Inspection Mode:** Strictly Static Source Code Inspection (Read-Only)  
**Objective:** Investigate why the live HTTP benchmark in `scratch/benchmark_http_fastapi.py` reported approximately 5.5 seconds for 500 requests with 50 concurrent tasks and 5 ms simulated I/O.

---

## 1. Static Breakdown of the 5.5-Second Execution Time

### Verified Code Facts vs. Hypotheses

| Factor | Code Location | Verified Code Fact | Analytic Hypothesis / Likely Mechanism |
| :--- | :--- | :--- | :--- |
| **Concurrency & Task Scheduling** | `benchmark_http_fastapi.py:80–82` | `tasks = [asyncio.create_task(worker()) for _ in range(total_requests)]` schedules all 500 tasks simultaneously. In `worker()`, `async with semaphore:` bounds concurrency to 50. Total duration `duration = t_end - t_start` measures from before task creation until `asyncio.gather(*tasks)` finishes. | **Batch Draining Overhead:** With 500 requests and 50 concurrency, the workload divides into at least 10 sequential waves of 50 requests. Any queue contention in `asyncio.Semaphore` or event-loop tick delays accumulates across all 10 waves. |
| **Thread & GIL Architecture** | `benchmark_http_fastapi.py:104–105` | `server_thread = threading.Thread(target=run_server, args=(port,), daemon=True); server_thread.start()` runs Uvicorn inside a Python daemon thread within the **same CPython process** as the client. | **CPython GIL Contention:** CPython's Global Interpreter Lock prevents true parallel execution across threads. When the HTTPX client event loop and Uvicorn ASGI server event loop execute concurrently in the same process, they constantly preempt and serialize each other on every socket read/write, adding non-deterministic context-switching latency. |
| **Connection Pooling & Warmup** | `benchmark_http_fastapi.py:51, 60–61` | `limits = httpx.Limits(max_connections=100, max_keepalive_connections=50)`. Warm-up executes 10 sequential requests (`for _ in range(10): await client.get(url)`). | **Initial TCP Burst Contention:** 10 sequential warmup requests only warm **1 single keep-alive connection** in the pool. When 50 concurrent tasks fire simultaneously at line 81, **49 tasks must negotiate a new TCP handshake simultaneously** on the Windows loopback interface, incurring TCP handshake overhead and connection pool synchronization locks. |
| **Latency Measurement Location** | `benchmark_http_fastapi.py:66–71` | `t0 = time.perf_counter()` is called inside `async with semaphore:`. Latency is appended as `(t1 - t0) * 1000` around `resp = await client.get(url)`. | **Client-Side vs Server-Side Mixing:** The measurement records full client round-trip time (HTTPX pool checkout + socket write + loopback transit + server parsing + server execution + socket response + client parsing), not pure server execution time. |
| **Server-Side Threadpool Queueing (Sync)** | `benchmark_http_fastapi.py:13–17` | `@app.get("/sync-endpoint") def sync_endpoint(): time.sleep(0.005)` is a synchronous `def` function. FastAPI routes synchronous endpoints through `anyio.to_thread.run_sync`. | **AnyIO Limiter Starvation:** AnyIO's default thread limiter has `total_tokens = 40`. With 50 concurrent requests hitting the server, at least 10 requests must queue in the AnyIO limiter queue even before executing `time.sleep(0.005)`. |

---

## 2. In-Depth Analysis of the Seven Verification Dimensions

### 1. Actual Client Concurrency
- **Verified Code Fact:** `semaphore = asyncio.Semaphore(50)` (line 56) enforces that at most 50 `worker()` coroutines execute `await client.get(url)` at any point in time.
- **Queueing Observation:** All 500 tasks are instantiated at once at line 80 (`tasks = [asyncio.create_task(worker()) for _ in range(500)]`). Tasks 51 through 500 must wait in the `asyncio.Semaphore` FIFO queue.
- **Analytical Implication:** The reported `total_duration_sec` ($\sim 5.5\text{ s}$) represents the wall-clock time required to drain all 10 successive batches of 50 requests through the event loop, not the latency of a single concurrent batch.

### 2. HTTPX Connection-Pool Behavior
- **Verified Code Fact:** Lines 51–52 configure `limits = httpx.Limits(max_connections=100, max_keepalive_connections=50)` and `timeout = httpx.Timeout(30.0, connect=10.0)`.
- **Identified Defect in Warmup:** Lines 60–61 execute `for _ in range(10): await client.get(url)` sequentially. In HTTPX, sequential requests reuse the same open socket. Therefore, when line 80 starts 50 concurrent requests, the pool contains only 1 connection.
- **Impact:** The remaining 49 concurrent coroutines simultaneously initiate TCP connection handshakes (`SYN` $\to$ `SYN-ACK` $\to$ `ACK`) over `127.0.0.1:18765`. On Windows loopback using IOCP, 49 simultaneous connection setups contend for port allocation and socket acceptance.

### 3. Uvicorn Worker Count and Configuration
- **Verified Code Fact:** Line 38 calls `uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")` with default single-worker configuration (`workers=1`).
- **Verified Code Fact:** Line 104 starts Uvicorn via `server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)`.
- **Architectural Consequence:** Uvicorn runs inside the **same Python process** as the client benchmark. In CPython, multiple threads share one GIL. Both Uvicorn's event loop and HTTPX's event loop require the GIL to serialize bytes, handle IOCP completions, and execute Python frames.

### 4. Server-Side versus Client-Side Latency
- **Verified Code Fact:** `benchmark_http_fastapi.py` contains **no server-side timing middleware** and no response headers recording internal server execution duration.
- **Analytical Implication:** The client latency `(t1 - t0) * 1000` conflates:
  1. Client-side HTTPX connection checkout from pool.
  2. Operating system socket write and loopback packet transit.
  3. Uvicorn HTTP parser (`httptools` / `h11`) and ASGI application dispatch.
  4. Actual endpoint execution (5 ms sleep).
  5. Response JSON serialization.
  6. Socket return transit and client response decoding.
  Without an ASGI timing middleware (`X-Process-Time`), server execution time cannot be verified independently from client-side network stack overhead.

### 5. Warm-up Exclusion
- **Verified Code Fact:** Lines 60–61 execute 10 requests *before* `t_start = time.perf_counter()`.
- **Evaluation:** The elapsed time of the 10 warmup requests is excluded from `total_duration_sec`. However, as established in item 2, sequential warmup does not pre-populate the connection pool to the target concurrency of 50.

### 6. Measurement Ordering and Repeated Runs
- **Verified Code Fact:** In `main()` (lines 114–118), `sync_res` is executed first, followed immediately by `async_res`.
- **Identified Methodological Limitation:**
  - Neither benchmark is repeated (repetitions = 1).
  - No variance, standard deviation, or confidence intervals can be computed from a single execution.
  - The fixed execution order introduces ordering bias: the second benchmark (`async`) benefits from already-allocated heap memory and established socket subsystem state.

### 7. CPU Utilization and Event-Loop Responsiveness
- **Verified Code Fact:** Lines 25–35 define `/cpu-sync` (`sum(i*i for i in range(200_000))` in thread) and `/cpu-async-blocking` (`sum(i*i ...)` directly on the event loop).
- **Analytical Implication:** In standard CPython, asynchronous code does not parallelize CPU execution. When a coroutine performs CPU-heavy computation without yielding (`await`), it blocks the single event loop thread, preventing all other connections from receiving attention.

---

## 3. Methodological Recommendations for Future Benchmark Execution

1. **Process Isolation:** Uvicorn should run in an independent OS subprocess (via `subprocess.Popen`) rather than an in-process daemon thread to eliminate client-server GIL contention.
2. **Server-Side Timing Instrumentation:** Add an ASGI middleware that measures pure request handling (`time.perf_counter()` inside `call_next`) and emits an `X-Server-Time-Ms` header.
3. **True Concurrent Warmup:** The warmup phase must execute at least 50 concurrent requests to pre-open all 50 pool connections before measurement begins.
4. **Repetitions and Interleaving:** Execute at least 3 to 5 repetitions with interleaved ordering (`Sync` $\to$ `Async` $\to$ `Sync` $\to$ `Async`) to control for system warmup and compute standard errors.
5. **No Universal Superiority Claim:** Document that while asynchronous I/O excels at scaling thousands of idle or non-blocking I/O connections, it confers no throughput advantage for CPU-bound computation and can cause severe tail-latency spikes if blocking code is inadvertently executed on the event loop.

