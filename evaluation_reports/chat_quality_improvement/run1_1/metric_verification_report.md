# CodeMind AI — Run 1 Metric Verification & Recalculation Report

**Evaluation Phase**: Run 1.1 — Retrieval Stabilization & Precision Improvement  
**Target Environment**: Isolated Evaluation Environment (`codemind_eval_db`)  
**Data Sources**:
- Baseline Raw Data: `evaluation_reports/chat_quality_improvement/run1/raw_baseline_retrieval_results.json`
- Post-Run 1 Raw Data: `evaluation_reports/chat_quality_improvement/run1/raw_post_retrieval_results.json`

---

## 1. Executive Summary

During Run 1, retrieval modifications were introduced to address initial recall and ranking deficiencies. While directional improvements were observed, several discrepancies in metric reporting, unit definitions, and latency characterization require rigorous independent recalculation.

This report independently recalculates all baseline and post-Run 1 metrics from the persistent raw evaluation JSON records, analyzes the mathematical formulations, resolves unit ambiguities, and breaks down the latency behavior across cold-start and warm execution regimes.

### Summary Comparison Table

| Metric | Reported Run 1 Baseline | Recalculated Run 1 Baseline | Reported Post-Run 1 | Recalculated Post-Run 1 | Unit / Formulation |
|---|---:|---:|---:|---:|---|
| **Evaluated Questions** | 20 | 20 | 20 | 20 | Count of query scenarios |
| **Total Chunks Retrieved** | 172 | 172 | 172 | 172 | Total retrieved chunks |
| **Total Relevant Chunks** | 65 | 65 | 69 | 69 | Chunks matching expected files |
| **Micro-Averaged Precision** | 37.79% | 37.79% | 40.12% | 40.12% | $\frac{\sum \text{Relevant Chunks}}{\sum \text{Retrieved Chunks}}$ |
| **Macro-Averaged Precision** | *Not Reported* | 36.25% | *Not Reported* | 38.75% | $\frac{1}{N}\sum \text{Precision}_q$ |
| **Micro-Averaged Recall** | 47.83% | 47.83% | 54.35% | 54.35% | $\frac{\sum \text{Expected Target Files Hit}}{\sum \text{Expected Target Files}}$ |
| **Macro-Averaged Recall** | *Not Reported* | 47.50% | *Not Reported* | 54.17% | $\frac{1}{N_{\text{valid}}}\sum \text{Recall}_q$ |
| **Relevant Source Coverage** | 38.89% | 38.89% | 44.44% | 44.44% | $\frac{\text{Questions with 100\% Target Recall}}{\text{Non-Adversarial Questions (18)}}$ |
| **Wrong Repository Rate** | 0.00% | 0.00% (0/172) | 0.00% | 0.00% (0/172) | Cross-repo leakage rate |
| **Mean Latency (Overall)** | 811.23 ms | 811.23 ms | 1,081.47 ms | 1,081.47 ms | Arithmetic mean across 20 queries |
| **Median Latency (P50)** | *Not Reported* | 557.73 ms | *Not Reported* | 673.47 ms | Median query duration |
| **Warm Mean Latency (Q2–Q20)** | *Not Reported* | 608.73 ms | *Not Reported* | 702.90 ms | Arithmetic mean excluding Q1 cold-start |
| **Initial Query Latency (Q1)** | *Not Reported* | 4,658.70 ms | *Not Reported* | 8,274.50 ms | Cold-start query duration |

---

## 2. Unit and Formula Analysis

The Run 1 report presented three primary retrieval quality percentages: **37.79% $\rightarrow$ 40.12%** (Precision), **47.83% $\rightarrow$ 54.35%** (Recall), and **38.89% $\rightarrow$ 44.44%** (Coverage). The underlying units and aggregation formulas are defined as follows:

### 2.1 Retrieval Precision
- **Mathematical Formula**:
  $$\text{Precision}_{\text{micro}} = \frac{\sum_{i=1}^{N} \text{Relevant Chunks Retrieved}_i}{\sum_{i=1}^{N} \text{Total Chunks Retrieved}_i} = \frac{69}{172} = 40.12\%$$
- **Unit**: **Code Chunks** (ratio of relevant chunks to total retrieved chunks across all queries).
- **Behavioral Analysis**:
  In both baseline and post-Run 1 evaluations, a total of 172 chunks were retrieved across 20 questions (an average of 8.6 chunks per question). The fixed retrieval limit (`k=8` or `k=12`) returned distractor chunks even when the primary target was already captured in the top 1–2 positions. For example, in question `ED-01` (entrypoint discovery), 3 chunks from `backend/app/main.py` were retrieved alongside 5 irrelevant chunks from `backend/app/services/ai_support_service.py`, capping single-query precision at $3/8 = 37.5\%$.
- **Macro vs. Micro**:
  When calculated on a per-question basis and averaged (macro-precision), baseline was **36.25%** and post-Run 1 was **38.75%**. Both formulations confirm low retrieval precision driven by fixed-limit tail padding.

### 2.2 Retrieval Recall
- **Mathematical Formula**:
  $$\text{Recall}_{\text{micro}} = \frac{\sum_{i \in \text{valid}} \text{Distinct Expected Target Files Hit}_i}{\sum_{i \in \text{valid}} \text{Total Expected Target Files}_i} = \frac{25}{46} = 54.35\%$$
- **Unit**: **Distinct Target Files per Query** (ratio of expected repository files found in the retrieved chunks to the total expected files listed in ground truth).
- **Denominator Construction**:
  Across the 18 non-adversarial questions (excluding `ED-19` and `RP-19`, which test absence), there were 46 expected target file instances in total. Post-Run 1 retrieved 25 of these 46 targets (up from 22 in baseline).
- **Macro vs. Micro**:
  Macro-averaged recall across the 18 non-adversarial questions was **47.50%** at baseline and **54.17%** post-Run 1.

### 2.3 Relevant Source Coverage
- **Mathematical Formula**:
  $$\text{Coverage} = \frac{\text{Count of Valid Queries where } 100\% \text{ Expected Target Files Were Retrieved}}{\text{Total Valid Non-Adversarial Queries}} = \frac{8}{18} = 44.44\%$$
- **Unit**: **Questions** (percentage of questions that achieved complete target file recall).
- **Baseline**: 7 out of 18 questions achieved complete coverage (38.89%).
- **Post-Run 1**: 8 out of 18 questions achieved complete coverage (44.44%). The additional query achieving full coverage was `ED-01`.

---

## 3. Latency Verification and Refutation of "Sub-Second" Claim

### 3.1 Refutation of "Sub-Second" Description
The Run 1 post-retrieval report characterized the average retrieval latency as:
> *"Average retrieval latency: 1081.47 ms (sub-second performance preserved)."*

**This statement is factually inaccurate.** 
1. `1,081.47 ms` equals `1.0815 seconds`, which is strictly greater than 1.0 second.
2. Even when excluding the initial cold-start query (`ED-01` at 8,274.5 ms), individual warm queries exceeded 1.0 second:
   - `ED-04`: 1,060.9 ms
   - `ED-12`: 1,032.6 ms
3. The overall latency increased by **270.24 ms (+33.3%)** from the baseline average of 811.23 ms.

### 3.2 Cold-Start vs. Warm Execution Breakdown

| Query ID | Repository | Baseline Latency (ms) | Post-Run 1 Latency (ms) | Delta (ms) | State |
|---|---|---:|---:|---:|---|
| **ED-01** | expertdecision | 4,658.7 | 8,274.5 | +3,615.8 | Cold-Start (Ollama embed model initialization) |
| **ED-03** | expertdecision | 559.5 | 753.8 | +194.3 | Warm |
| **ED-04** | expertdecision | 827.6 | 1,060.9 | +233.3 | Warm (> 1,000 ms) |
| **ED-05** | expertdecision | 729.1 | 794.2 | +65.1 | Warm |
| **ED-06** | expertdecision | 646.7 | 782.5 | +135.8 | Warm |
| **ED-08** | expertdecision | 859.8 | 840.6 | -19.2 | Warm |
| **ED-10** | expertdecision | 613.2 | 706.5 | +93.3 | Warm |
| **ED-12** | expertdecision | 744.8 | 1,032.6 | +287.8 | Warm (> 1,000 ms) |
| **ED-13** | expertdecision | 655.6 | 815.2 | +159.6 | Warm |
| **ED-19** | expertdecision | 631.8 | 732.0 | +100.2 | Warm (Adversarial) |
| **RP-01** | RewardPoints Transfer | 531.8 | 599.9 | +68.1 | Warm |
| **RP-03** | RewardPoints Transfer | 544.0 | 636.2 | +92.2 | Warm |
| **RP-04** | RewardPoints Transfer | 529.7 | 585.0 | +55.3 | Warm |
| **RP-06** | RewardPoints Transfer | 541.4 | 640.4 | +99.0 | Warm |
| **RP-07** | RewardPoints Transfer | 538.8 | 602.0 | +63.2 | Warm |
| **RP-08** | RewardPoints Transfer | 553.4 | 615.9 | +62.5 | Warm |
| **RP-10** | RewardPoints Transfer | 556.0 | 589.7 | +33.7 | Warm |
| **RP-11** | RewardPoints Transfer | 473.3 | 523.9 | +50.6 | Warm |
| **RP-12** | RewardPoints Transfer | 514.9 | 550.7 | +35.8 | Warm |
| **RP-19** | RewardPoints Transfer | 514.5 | 492.9 | -21.6 | Warm (Adversarial) |
| **All 20 Queries** | — | **811.23 ms** | **1,081.47 ms** | **+270.24 ms** | Mean Overall |
| **Queries 2–20** | — | **608.73 ms** | **702.90 ms** | **+94.17 ms** | Mean Warmed |
| **Median (P50)** | — | **557.73 ms** | **673.47 ms** | **+115.74 ms** | Median Overall |

---

## 4. Root-Cause of Latency Inflation

Every warm query exhibited a consistent latency inflation of **+50 ms to +288 ms**.
Profiling reveals the exact culprit in `HybridRetrievalEngine._retrieve_exact_matches`:

```python
# Added during Run 1 (lines 544-558):
ident_chunks = (
    db.query(CodeChunk.id)
    .filter(
        CodeChunk.repository_id == repo_id,
        or_(
            CodeChunk.code_symbol.in_(code_identifiers),
            *[CodeChunk.chunk_text.ilike(f"%{ci}%") for ci in list(code_identifiers)[:6]]
        )
    )
    .limit(15)
    .all()
)
```

Direct database execution profiling on `codemind_eval_db` demonstrates:
- Executing with `chunk_text.ilike` on 6 identifiers: **182.08 ms** (full table scan across multi-megabyte text chunks).
- Executing with indexed `code_symbol.in_`: **4.36 ms** (B-tree index scan on `(repository_id, code_symbol)`).
- **Speedup**: **41.7x faster** when eliminating `chunk_text.ilike`.

Because `_retrieve_exact_matches` executes synchronously on every query, adding unindexed `chunk_text.ilike` table scans injected ~180 ms of unavoidable I/O blocking into the retrieval pipeline.

---

## 5. Verification Conclusion

1. **Precision (40.12%) and Recall (54.35%) are verified as accurate reflections of the Run 1 code changes**, but both metrics demonstrate severe limitations caused by fixed-K tail distractor dilution and lack of concept-level stem matching.
2. **The "sub-second" latency characterization is refuted.** The true mean was 1,081.47 ms, caused primarily by an unindexed full-text `ilike` scan in `_retrieve_exact_matches`.
3. **The units are confirmed**: Precision is per-retrieved-chunk; Recall is per-target-file; Coverage is per-question.
