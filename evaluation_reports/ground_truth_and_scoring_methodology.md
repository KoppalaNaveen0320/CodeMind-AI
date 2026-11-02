# Ground Truth & Independent Scoring Methodology

**Target System:** CodeMind AI Evaluation Framework  
**Scope:** Independent Verification & Mathematical Scoring Metrics  
**Principle:** Ground truth is established strictly by direct disk/AST inspection of source repositories. CodeMind AI's own generated answers are never used as ground truth.

---

## 1. Mathematical Scoring Formulas (Numerators & Denominators)

Every reported metric must publish its exact numerator ($N$) and denominator ($D$), strictly adhering to:
$$\text{Score (\%)} = \frac{N}{D} \times 100$$

| # | Metric | Formal Definition | Numerator ($N$) | Denominator ($D$) |
| :--- | :--- | :--- | :--- | :--- |
| **M1** | **Retrieval Precision** | Fraction of retrieved chunks that contain relevant source code for the question | Count of retrieved chunks containing code directly relevant to question | Total count of chunks retrieved in context ($k \le 12$) |
| **M2** | **Retrieval Recall** | Fraction of essential repository evidence files captured in context | Count of necessary ground-truth implementation files present in retrieved chunks | Total count of ground-truth files required for complete answer |
| **M3** | **Citation Path Accuracy** | Fraction of cited file paths that exist in the target repository | Count of cited file paths verified to exist on disk in the selected repository | Total count of file paths cited in the answer |
| **M4** | **Citation Line Accuracy** | Fraction of cited line ranges matching exact source code bounds | Count of line ranges matching actual target definition bounds within $\pm 3$ lines | Total count of line citations provided in the answer |
| **M5** | **Symbol Accuracy** | Fraction of identified classes/functions/variables that genuinely exist | Count of correctly named symbols verified in repository AST | Total count of distinct symbols referenced in the answer |
| **M6** | **Caller Accuracy** | Fraction of identified callers that are genuine call sites | Count of verified AST call sites (`caller` $\to$ `callee` at exact line) | Total count of claimed caller relationships in the answer |
| **M7** | **Execution Trace Accuracy**| Fraction of sequential execution trace steps verified by code | Count of verified transitions (e.g. `Route` $\to$ `Service` $\to$ `DB`) | Total count of execution transitions claimed in the trace |
| **M8** | **Change-Impact Precision** | Fraction of predicted affected files/symbols that genuinely depend on target | Count of verified dependents (direct callers, importers, tests) | Total count of components predicted to be affected |
| **M9** | **Change-Impact Recall** | Fraction of actual affected dependents identified by analysis | Count of actual affected dependents identified in prediction | Total count of genuine dependents in ground-truth graph |
| **M10**| **Hallucination Rate** | Proportion of factual claims unsupported by verified code | Count of factual assertions about nonexistent entities or fabricated logic | Total count of distinct factual assertions in the answer |
| **M11**| **Uncertainty Calibration** | Correct refusal/acknowledgment of missing or absent entities | Count of appropriate uncertainty assertions or explicit nonexistence claims | Total count of adversarial questions or questions lacking source evidence |
| **M12**| **Security Precision** | Fraction of reported security findings verified by code | Count of confirmed vulnerabilities and insecure configurations verified on disk | Total count of security findings generated in review |

---

## 2. Evaluation Unit & Partial Credit Framework

### A. Definition of the Evaluation Unit
- **Atomic Claim Unit:** An answer is decomposed into individual factual assertions:
  1. *Symbol existence assertion* (e.g. `"Function X exists in File Y"`).
  2. *Line citation assertion* (e.g. `"Lines 15–20 define get_db"`).
  3. *Call relationship assertion* (e.g. `"login_for_access_token calls get_db"`).
  4. *Behavioral assertion* (e.g. `"Missing tenant filter leaks CTI records"`).

### B. Partial Credit Rules
1. **Zero-Tolerance Hallucination Penalty:** If an answer invents a fictitious file, class, or endpoint, the answer score is capped at **0.25**, even if accompanying general explanations are correct.
2. **Valid Citation Requirement:** A valid citation alone does not make an answer correct. An answer receives full credit (1.0) only if:
   - All cited paths exist.
   - Cited lines match ground truth.
   - The reasoning accurately reflects the cited code.
3. **Partial Scoring Grid:**
   - **1.0 (Flawless):** Correct answer, exact citations, zero hallucinations, fully grounded reasoning.
   - **0.75 (Substantially Correct):** Correct code logic and verified files, with minor citation line drift ($\pm 4\text{–}8$ lines) or omitting a secondary caller.
   - **0.50 (Partially Correct):** Identified the correct file and entrypoint, but execution trace is incomplete or includes speculative inferences.
   - **0.25 (Flawed / Speculative):** Generic explanation without code grounding, or correct file citation combined with a hallucinated function.
   - **0.0 (Failed / Hallucinated):** Entirely fabricated entity, wrong repository context, or claim refuted by source evidence.

---

## 3. Independent Verification Procedure

1. **Direct Disk & AST Inspection:** A separate Python verification script (`scratch/verify_ground_truth.py`) parses the actual source code of `expertdecision`, `TokenPool`, and `RewardPoints Transfer` using Python `ast` and Tree-sitter.
2. **Automated Cross-Check:** Every file path and line number cited by CodeMind AI is passed to the verification script to check:
   - `os.path.exists(path)` on disk.
   - `start_line` and `end_line` encompass the declared function or class in AST.
   - AST `Call` visitor confirms caller/callee relationship.
3. **Manual Expert Review:** Architectural flow questions and security findings are manually audited by line-by-line inspection of repository code.

