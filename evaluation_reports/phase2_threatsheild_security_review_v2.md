# Phase 2: Threatsheild Security Review & Source Evidence Verification (v2)

**Target Repository:** `Threatsheild` (`KoppalaNaveen0320/Threatsheild`, Repository ID `44`)  
**Target Path:** `C:\Users\koppa\OneDrive\Documents\Projects\Threatsheild\`  
**Review Mode:** Strictly Static Source Code & Deployment Manifest Audit (Read-Only)  
**Objective:** Deliver an evidence-grounded security audit across 15 areas, incorporating deployment manifest analysis, full execution-path tracing, and clear distinctions between confirmed vulnerabilities, insecure configurations, design trade-offs, and potential risks.

---

## 1. Vulnerability & Risk Taxonomy

To maintain analytical rigor, all findings are categorized into 5 distinct tiers:
1. **Confirmed Vulnerability:** An architectural defect or code flaw that can be directly triggered to cause a security failure under realistic operating conditions.
2. **Insecure Configuration:** A dangerous default setting or credential pattern present in repository code or deployment manifests.
3. **Potential Risk:** An unbounded pattern or edge-case behavior that may cause degradation or failure under adversarial input.
4. **Design Trade-Off:** An architectural choice (e.g. token lifetime, PRNG selection) that balances usability/performance against theoretical security bounds.
5. **Hypothetical Scenario:** A security consequence that would only arise if specific hypothetical code modifications were introduced.

---

## 2. Comprehensive Security Findings Matrix

| Finding ID | Title | File & Lines | Category | Severity | Confidence | Deployment Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | Hardcoded AES-GCM Key Fallback | `backend/app/privacy/engine.py:9` | Insecure Configuration | **HIGH** | High | **Active in Docker Compose** (Key omitted from compose) |
| **SEC-02** | Hardcoded JWT Secret | `backend/app/security/security.py:7` | Insecure Configuration | **CRITICAL** | High | **Active in Docker Compose** (`SECRET_KEY` set to default) |
| **SEC-03** | Missing Key Length Validation | `backend/app/privacy/engine.py:9–10` | Insecure Configuration | **MEDIUM** | High | Overlaps SEC-01 (Crashes if key length $\ne$ 32B) |
| **SEC-04** | 24-Hour JWT Lifetime & No Blacklist | `backend/app/security/security.py:8–9` | Design Trade-Off | **MEDIUM** | High | Standard long-lived token; requires stolen token |
| **SEC-05** | Multi-Tenant CTI Data Exposure | `backend/app/api/cti.py:98–106` | Confirmed Vulnerability | **HIGH** | High | Executable by any authenticated user |
| **SEC-06** | Privilege Escalation in Registration | `backend/app/api/auth.py:23–39` | Confirmed Vulnerability | **CRITICAL** | High | Executable by any unauthenticated attacker |
| **SEC-07** | Unbounded Query Pagination Limit | `backend/app/api/cti.py:100` | Potential Risk | **LOW** | Medium | Bounded by default (100), overrideable by client |
| **SEC-08** | Unchecked Ciphertext Truncation | `backend/app/privacy/engine.py:17–20` | Confirmed Vulnerability | **MEDIUM** | High | Raises unhandled `InvalidTag` on short input |
| **SEC-09** | NumPy MT19937 PRNG for Laplace DP | `backend/app/privacy/engine.py:32–39` | Design Trade-Off | **MEDIUM** | High | Theoretical state reconstruction attack |
| **SEC-10** | Hypothetical In-Memory Token Cache | `backend/app/api/deps.py:13–25` | Hypothetical Scenario | **HIGH** | High | Evaluates impact if caching were introduced |

---

## 3. Detailed Source-Grounded Analyses

### Finding SEC-01: Hardcoded AES-GCM Key Fallback
- **File & Line Range:** `backend/app/privacy/engine.py`, Lines 8–10
- **Source Evidence:**
  ```python
  # Robust key for AES-256-GCM (32 bytes)
  _AES_KEY = os.getenv("AES_SECRET_KEY", "0123456789abcdef0123456789abcdef").encode("utf-8")
  aesgcm = AESGCM(_AES_KEY)
  ```
- **Deployment Manifest Audit:** In `docker-compose.yml:29–33`, `AES_SECRET_KEY` is **completely omitted** from the backend container environment. As a result, any container launched via `docker-compose up` **actually runs with the hardcoded fallback key** `"0123456789abcdef0123456789abcdef"`.
- **CWE / OWASP:** CWE-321 (Hard-coded Cryptographic Key), OWASP A02:2021 (Cryptographic Failures).
- **Exploitability Conditions:** Any attacker with knowledge of the public repository can decrypt all data encrypted via `encrypt_data()` (e.g. sensitive incident payloads or private organizational telemetry).
- **Actual Impact:** Complete loss of confidentiality for AES-GCM encrypted database fields in standard Docker deployments.
- **Remediation:** Remove fallback string and fail fast on startup if `AES_SECRET_KEY` is unset or not 32 bytes:
  ```python
  _raw = os.getenv("AES_SECRET_KEY")
  if not _raw or len(_raw.encode("utf-8")) != 32:
      raise RuntimeError("FATAL: AES_SECRET_KEY must be provided as a 32-byte secret.")
  _AES_KEY = _raw.encode("utf-8")
  aesgcm = AESGCM(_AES_KEY)
  ```

---

### Finding SEC-02: Hardcoded Fallback JWT Secret Active in Production Manifest
- **File & Line Range:** `backend/app/security/security.py`, Line 7
- **Source Evidence:**
  ```python
  SECRET_KEY = os.getenv("SECRET_KEY", "supersecretjwtkeychangeinprod")
  ALGORITHM = os.getenv("ALGORITHM", "HS256")
  ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
  ```
- **Deployment Manifest Audit:** In `docker-compose.yml:31`, the environment block declares:
  ```yaml
  SECRET_KEY: supersecretjwtkeychangeinprod
  ```
  The deployment configuration explicitly binds `SECRET_KEY` to the known default.
- **CWE / OWASP:** CWE-798 (Use of Hard-coded Credentials), OWASP A02:2021.
- **Exploitability Conditions:** An attacker signs an arbitrary JWT with `algorithm="HS256"` and secret `"supersecretjwtkeychangeinprod"`, injecting `{"sub": "<target_user_id>"}`.
- **Actual Impact:** Full authentication bypass; attacker can impersonate any administrator or analyst.
- **Remediation:** Mandate injection of a high-entropy secret via Docker secret or production `.env` and reject known defaults during initialization.

---

### Finding SEC-03: Missing Startup Validation for Key Format (Overlapping)
- **File & Line Range:** `backend/app/privacy/engine.py:9–10`
- **Analysis:** Overlaps with SEC-01. If an operator configures `AES_SECRET_KEY` with an invalid length (e.g. 16 or 24 characters instead of 32 for AES-256), `AESGCM` raises `ValueError` on module load, crashing Uvicorn at boot time.
- **Classification:** Insecure Configuration / Improper Exception Handling (CWE-703).
- **Remediation:** Add startup validation with descriptive logging.

---

### Finding SEC-04: 24-Hour JWT Expiration & Lack of Revocation
- **File & Line Range:** `backend/app/security/security.py:8–9` and `backend/app/api/deps.py:13–25`
- **Source Evidence:** `ACCESS_TOKEN_EXPIRE_MINUTES = 1440` (24 hours). `deps.py:get_current_user` decodes the token with `jwt.decode` and looks up `User` in the database, with **zero token blacklist or revocation verification**.
- **Realistic Threat Model:** A 24-hour token lifetime is a common trade-off in REST APIs without active token refresh flows. It is **not automatically exploitable on its own**. Exploitability requires an adversary to first compromise or intercept the bearer token (e.g. via XSS, network sniffing, or client log exposure).
- **Impact When Compromised:** Once intercepted, the token cannot be invalidated by logging out or resetting passwords; it remains valid for up to 24 hours.
- **Classification:** Design Trade-Off / Insufficient Session Expiration (CWE-613).
- **Remediation:** Shorten token lifetime to 15–30 minutes, introduce refresh tokens, and maintain an invalidation blacklist in Redis.

---

### Finding SEC-05: Multi-Tenant CTI Data Exposure
- **File & Line Range:** `backend/app/api/cti.py`, Lines 98–106
- **Complete Execution Trace:**
  ```mermaid
  sequenceDiagram
      actor UserA as Organization A User
      participant Route as GET /api/cti/ (cti.py:98)
      participant Auth as get_current_active_user (deps.py:27)
      participant DB as PostgreSQL (CTIRecord)
      
      UserA->>Route: GET /api/cti/ (Bearer Token Org A)
      Route->>Auth: Verify JWT and extract user
      Auth-->>Route: User object (organization_id = Org A)
      Route->>DB: db.query(CTIRecord).offset(skip).limit(limit).all()
      Note over Route,DB: NO WHERE organization_id clause!
      DB-->>Route: All CTIRecords (including Org B, Org C, etc.)
      Route-->>UserA: HTTP 200 with all tenants' threat indicators
  ```
- **Source Evidence:**
  ```python
  @router.get("/", response_model=List[CTIResponse])
  def get_cti_records(
      skip: int = 0,
      limit: int = 100,
      db: Session = Depends(get_db),
      current_user: User = Depends(get_current_active_user)
  ):
      records = db.query(CTIRecord).offset(skip).limit(limit).all()
      return records
  ```
- **Contrast with Properly Isolated Routes:** In `backend/app/api/incidents.py:70–72`, tenant filtering is explicitly enforced:
  `if current_user.role != RoleEnum.ADMIN: query = query.filter(Incident.organization_id == current_user.organization_id)`.
  In `cti.py:104`, this check is entirely missing.
- **Classification:** Confirmed Vulnerability (CWE-639 / OWASP API1:2023 - BOLA).
- **Actual Impact:** Cross-tenant threat intelligence leakage across organizations.
- **Remediation:** Add explicit tenant scoping or role-based sharing filters.

---

### Finding SEC-06: Privilege Escalation via Unauthenticated Registration
- **File & Line Range:** `backend/app/api/auth.py`, Lines 23–39
- **Complete Execution Trace:**
  1. `UserCreate` schema (`schemas/domain.py:31–35`):
     ```python
     class UserCreate(UserBase):
         password: str
         organization_id: UUID
         role: RoleEnum = RoleEnum.ANALYST  # Client can override!
     ```
  2. `POST /api/auth/register` (`api/auth.py:23–39`):
     ```python
     @router.post("/register", response_model=UserResponse)
     def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
         ...
         db_user = User(
             email=user_in.email,
             password_hash=hashed_password,
             organization_id=user_in.organization_id,
             role=user_in.role  # <-- DIRECT ASSIGNMENT FROM CLIENT
         )
         db.add(db_user)
         db.commit()
     ```
  3. The route has **zero authentication dependency** (`db: Session = Depends(get_db)` only).
  4. An unauthenticated attacker sends `{"email": "admin@attacker.com", "password": "...", "organization_id": "<valid_uuid>", "role": "ADMIN"}`.
  5. The user is committed with `role = RoleEnum.ADMIN`.
- **Classification:** Confirmed Vulnerability (CWE-269 - Improper Privilege Management).
- **Actual Impact:** Complete administrative takeover of any organization.
- **Remediation:** Hardcode `role=RoleEnum.ANALYST` for self-registration, and require admin authentication on an internal user provisioning endpoint for assigning elevated roles.

---

### Finding SEC-07: Query Pagination Parameter Limits
- **File & Line Range:** `backend/app/api/cti.py:100` and `backend/app/api/organizations.py:26`
- **Source Evidence:** `limit: int = 100` is declared as a plain Python default without Pydantic/FastAPI `Query(default=100, le=200)` constraints.
- **Realistic Threat Model:** Clients can pass arbitrary integer values (e.g. `?limit=500000`). While bounded by default, passing large values causes high memory allocation in SQLAlchemy.
- **Classification:** Potential Risk (CWE-770 / OWASP API4:2023).
- **Remediation:** Add `limit: int = Query(default=100, ge=1, le=200)`.

---

### Finding SEC-08: Unchecked Ciphertext Length and Truncation
- **File & Line Range:** `backend/app/privacy/engine.py`, Lines 17–20
- **Source Evidence:**
  ```python
  def decrypt_data(encrypted_data: bytes) -> str:
      nonce = encrypted_data[:12]
      ciphertext = encrypted_data[12:]
      return aesgcm.decrypt(nonce, ciphertext, None).decode('utf-8')
  ```
- **Vulnerability Mechanism:** AES-GCM requires a 12-byte nonce and a 16-byte authentication tag (minimum 28 bytes total). If an empty byte string `b""` or truncated payload (< 28 bytes) is passed to `decrypt_data`, slicing produces an incomplete nonce and empty ciphertext, causing `aesgcm.decrypt` to raise `cryptography.exceptions.InvalidTag`.
- **Classification:** Confirmed Vulnerability / Improper Input Handling (CWE-129).
- **Remediation:** Validate `if len(encrypted_data) < 28: raise ValueError("Invalid ciphertext length.")`.

---

### Finding SEC-09: Non-Cryptographic Randomness for Laplace Differential Privacy
- **File & Line Range:** `backend/app/privacy/engine.py`, Lines 32–39
- **Source Evidence:**
  ```python
  def apply_laplace_noise(value: float, sensitivity: float, epsilon: float) -> float:
      scale = get_laplace_scale(sensitivity, epsilon)
      noise = float(np.random.laplace(0, scale))
      return float(value + noise)
  ```
- **Realistic Threat Model & Exploitability:**
  `np.random.laplace` uses NumPy's legacy Mersenne Twister (MT19937) PRNG. MT19937 is **not cryptographically secure**: observing 624 32-bit state outputs allows complete recovery of the internal state.
  - *Practical Exploitability:* In a high-throughput API where an analyst queries multiple Laplace-perturbed statistics, a sophisticated adversary can collect consecutive noise samples, recover the MT19937 state, predict all future noise values, subtract them from query responses, and reconstruct private raw values with zero noise.
  - *Floating-Point Attack:* Standard floating-point Laplace implementations are also vulnerable to Mironov's low-order bit reconstruction attack.
- **Classification:** Design Trade-Off / Cryptographic Weakness (CWE-338).
- **Remediation:** Use `secrets.SystemRandom` or a cryptographically verified differential privacy library (e.g. Google's Differential Privacy library or IBM's diffprivlib) with discrete snapping mechanisms.

---

### Finding SEC-10: Hypothetical In-Memory Token Caching Vulnerability Analysis
- **Target Component:** `backend/app/api/deps.py:13–25`
- **Scenario:** A developer attempts to optimize database queries by adding a global in-memory cache dictionary: `_TOKEN_CACHE[token] = user`.
- **Classification:** Hypothetical Scenario / Potential Risk (CWE-384).
- **Risks Introduced:**
  1. *Stale Expiration:* `jwt.decode` expiration is bypassed on cache hits; expired tokens remain usable indefinitely until process reboot.
  2. *Revocation Failure:* Disabling a user in PostgreSQL does not invalidate their active cached session.
  3. *Memory Exhaustion:* Unbounded token keys create an in-memory DoS risk.
- **Remediation:** If caching is needed, use Redis with explicit TTL set to `token.exp - current_time`.

---

> [!NOTE]
> **Status:** Strictly static review report. **No Threatsheild source files have been modified.**

