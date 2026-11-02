# Phase 2: Threatsheild Static Security Review & Vulnerability Assessment

**Target Repository:** `Threatsheild` (`KoppalaNaveen0320/Threatsheild`, Repository ID `44`)  
**Target Repository Path:** `C:\Users\koppa\OneDrive\Documents\Projects\Threatsheild\`  
**Review Mode:** Strictly Static Source Code Audit (Read-Only)  
**Objective:** Thoroughly evaluate 10 distinct security and cryptographic dimensions against actual source code evidence, distinguishing confirmed vulnerabilities from potential architectural risks.

---

## Executive Summary & Vulnerability Matrix

| Finding ID | Classification | CWE / OWASP | Target File & Lines | Status | Confidence | Severity |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | Hardcoded Cryptographic Key | CWE-321 / OWASP A02:2021 | `backend/app/privacy/engine.py:9` | **CONFIRMED VULNERABILITY** | High | **CRITICAL** |
| **SEC-02** | Insecure Fallback JWT Secret | CWE-798 / OWASP A02:2021 | `backend/app/security/security.py:7` | **CONFIRMED VULNERABILITY** | High | **CRITICAL** |
| **SEC-03** | Missing Env Var Validation | CWE-703 / OWASP A05:2021 | `backend/app/privacy/engine.py:9–10` | **CONFIRMED VULNERABILITY** | High | **MEDIUM** |
| **SEC-04** | Weak JWT Configuration | CWE-613 / OWASP A07:2021 | `backend/app/security/security.py:8–9` | **CONFIRMED VULNERABILITY** | High | **HIGH** |
| **SEC-05** | Multi-Tenant Data Exposure | CWE-639 / OWASP API1:2023 | `backend/app/api/cti.py:98–106` | **CONFIRMED VULNERABILITY** | High | **HIGH** |
| **SEC-06** | Missing Registration Auth Check | CWE-269 / OWASP A01:2021 | `backend/app/api/auth.py:23–39` | **CONFIRMED VULNERABILITY** | High | **CRITICAL** |
| **SEC-07** | Unbounded Query Pattern | CWE-770 / OWASP API4:2023 | `backend/app/api/cti.py:104` | **POTENTIAL RISK** | Medium | **MEDIUM** |
| **SEC-08** | Missing Ciphertext Bound Validation | CWE-129 / OWASP A04:2021 | `backend/app/privacy/engine.py:17–20` | **CONFIRMED VULNERABILITY** | High | **MEDIUM** |
| **SEC-09** | Insecure PRNG for Differential Privacy | CWE-338 / OWASP A02:2021 | `backend/app/privacy/engine.py:32–39` | **CONFIRMED VULNERABILITY** | High | **HIGH** |
| **SEC-10** | Hypothetical In-Memory Token Caching | CWE-384 / OWASP A07:2021 | `backend/app/api/deps.py:13–25` | **POTENTIAL RISK (SCENARIO)** | High | **HIGH** |

---

## Detailed Vulnerability Findings

### Finding SEC-01: Hardcoded Fallback Key for AES-256-GCM
- **File & Line Range:** `backend/app/privacy/engine.py`, Lines 8–10
- **Source Evidence:**
  ```python
  # Robust key for AES-256-GCM (32 bytes)
  _AES_KEY = os.getenv("AES_SECRET_KEY", "0123456789abcdef0123456789abcdef").encode("utf-8")
  aesgcm = AESGCM(_AES_KEY)
  ```
- **Vulnerability Classification:** CWE-321 (Use of Hard-coded Cryptographic Key), OWASP A02:2021 (Cryptographic Failures).
- **Status:** **CONFIRMED VULNERABILITY.**
- **Exploitability Conditions:** If `AES_SECRET_KEY` is omitted from the deployment environment or `.env` file, the application silently boots using the static fallback string `"0123456789abcdef0123456789abcdef"`.
- **Actual Impact:** Any party with repository access or knowledge of default keys can decrypt all organization data encrypted via `encrypt_data()` across database fields.
- **Confidence Level:** High.
- **Remediation:** Remove the fallback default. Require explicit validation at application startup:
  ```python
  _raw_key = os.getenv("AES_SECRET_KEY")
  if not _raw_key or len(_raw_key.encode("utf-8")) != 32:
      raise RuntimeError("FATAL: AES_SECRET_KEY environment variable must be set to exactly 32 bytes.")
  _AES_KEY = _raw_key.encode("utf-8")
  aesgcm = AESGCM(_AES_KEY)
  ```

---

### Finding SEC-02: Hardcoded Insecure Fallback JWT Secret
- **File & Line Range:** `backend/app/security/security.py`, Line 7
- **Source Evidence:**
  ```python
  SECRET_KEY = os.getenv("SECRET_KEY", "supersecretjwtkeychangeinprod")
  ALGORITHM = os.getenv("ALGORITHM", "HS256")
  ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
  ```
- **Vulnerability Classification:** CWE-798 (Use of Hard-coded Credentials), OWASP A02:2021 (Cryptographic Failures).
- **Status:** **CONFIRMED VULNERABILITY.**
- **Exploitability Conditions:** If `SECRET_KEY` is not explicitly declared in production, the application signs and verifies all tokens using `"supersecretjwtkeychangeinprod"`.
- **Actual Impact:** An external attacker can forge signed JWT tokens containing `{"sub": "<target_user_uuid>"}` or admin identifiers and authenticate as any user or administrator in the system.
- **Confidence Level:** High.
- **Remediation:** Fail fast on startup if `SECRET_KEY` is not provided or equals known development defaults:
  ```python
  SECRET_KEY = os.getenv("SECRET_KEY")
  if not SECRET_KEY or SECRET_KEY == "supersecretjwtkeychangeinprod":
      raise RuntimeError("FATAL: A strong, random SECRET_KEY must be configured in environment variables.")
  ```

---

### Finding SEC-03: Missing Startup Validation for Environment Key Length
- **File & Line Range:** `backend/app/privacy/engine.py`, Lines 9–10
- **Source Evidence:**
  ```python
  _AES_KEY = os.getenv("AES_SECRET_KEY", "0123456789abcdef0123456789abcdef").encode("utf-8")
  aesgcm = AESGCM(_AES_KEY)
  ```
- **Vulnerability Classification:** CWE-703 (Improper Check or Handling of Exceptional Conditions), OWASP A05:2021 (Security Misconfiguration).
- **Status:** **CONFIRMED VULNERABILITY.**
- **Exploitability Conditions:** If an operator supplies an `AES_SECRET_KEY` of 16, 20, or 64 characters in `.env`, `AESGCM(key)` raises `ValueError: AESGCM key must be 128, 192, or 256 bits` during module import time, crashing the server. There is no sanity checking of format, encoding, or entropy.
- **Actual Impact:** Denial of Service on application launch; unexpected startup crashes with unhandled Python tracebacks.
- **Confidence Level:** High.
- **Remediation:** Implement explicit Pydantic `BaseSettings` validation checking exact byte lengths and character encoding before instantiating cipher primitives.

---

### Finding SEC-04: Weak JWT Lifetime & Absence of Revocation Mechanisms
- **File & Line Range:** `backend/app/security/security.py:8–9` and `backend/app/api/deps.py:13–25`
- **Source Evidence:**
  ```python
  # security.py
  ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
  ...
  # deps.py
  def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
      try:
          payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
          user_id: str = payload.get("sub")
          ...
      except (JWTError, ValidationError, ValueError):
          raise HTTPException(status_code=401, detail="Could not validate credentials")
      user = db.query(User).filter(User.id == user_uuid).first()
  ```
- **Vulnerability Classification:** CWE-613 (Insufficient Session Expiration), OWASP A07:2021 (Identification and Authentication Failures).
- **Status:** **CONFIRMED VULNERABILITY.**
- **Exploitability Conditions:** Default token lifetime is set to **1,440 minutes (24 hours)**. The token decoding logic in `deps.py` contains **zero token blacklist or revocation checks** in database or Redis.
- **Actual Impact:** If a user's token is intercepted, the attacker maintains authorized access for a full 24 hours. Terminating a user session, changing passwords, or revoking a compromised account cannot invalidate previously issued tokens until they expire.
- **Confidence Level:** High.
- **Remediation:** Reduce access token expiration to 15–30 minutes, issue rotating refresh tokens stored in database/Redis, and check token revocation on each request.

---

### Finding SEC-05: Multi-Tenant Data Exposure in CTI Listing Endpoint
- **File & Line Range:** `backend/app/api/cti.py`, Lines 98–106
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
- **Vulnerability Classification:** CWE-639 (Authorization Bypass Through User-Controlled Key / BOLA), OWASP API1:2023 (Broken Object Level Authorization), OWASP A01:2021 (Broken Access Control).
- **Status:** **CONFIRMED VULNERABILITY.**
- **Exploitability Conditions:** Any authenticated user belonging to Organization A can call `GET /api/cti/` and receive all threat indicators submitted by Organization B without tenant isolation.
- **Actual Impact:** Breach of multi-tenant privacy boundaries in a platform specifically designed for privacy-preserving federated threat intelligence.
- **Confidence Level:** High.
- **Remediation:** Enforce tenant filtering or anonymization policies on CTI records:
  ```python
  query = db.query(CTIRecord)
  if current_user.role != RoleEnum.ADMIN:
      query = query.filter(CTIRecord.organization_id == current_user.organization_id)
  return query.offset(skip).limit(limit).all()
  ```

---

### Finding SEC-06: Privilege Escalation via Unauthenticated Registration
- **File & Line Range:** `backend/app/api/auth.py`, Lines 23–39
- **Source Evidence:**
  ```python
  @router.post("/register", response_model=UserResponse)
  def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
      user = db.query(User).filter(User.email == user_in.email).first()
      if user:
          raise HTTPException(status_code=400, detail="Email already registered")
      
      hashed_password = get_password_hash(user_in.password)
      db_user = User(
          email=user_in.email,
          password_hash=hashed_password,
          organization_id=user_in.organization_id,
          role=user_in.role
      )
      db.add(db_user)
      db.commit()
      db.refresh(db_user)
      return db_user
  ```
- **Vulnerability Classification:** CWE-269 (Improper Privilege Management), OWASP A01:2021 (Broken Access Control).
- **Status:** **CONFIRMED VULNERABILITY.**
- **Exploitability Conditions:** The endpoint is unauthenticated. The input schema `UserCreate` (`backend/app/schemas/domain.py:31–35`) declares `role: RoleEnum = RoleEnum.ANALYST`. A client can supply `{"email": "attacker@evil.com", "password": "...", "organization_id": "...", "role": "ADMIN"}`. Line 34 directly assigns `role=user_in.role`.
- **Actual Impact:** Complete unauthorized administrative takeover of any organization in the system by any unauthenticated attacker.
- **Confidence Level:** High.
- **Remediation:** Restrict registration to standard non-privileged roles (e.g. `RoleEnum.ANALYST`) or require admin authorization for role assignment:
  ```python
  db_user = User(
      email=user_in.email,
      password_hash=hashed_password,
      organization_id=user_in.organization_id,
      role=RoleEnum.ANALYST  # Hardcode default role for self-registration
  )
  ```

---

### Finding SEC-07: Unbounded Query Pattern in CTI and Organization Read
- **File & Line Range:** `backend/app/api/cti.py:100` and `backend/app/api/organizations.py:26`
- **Source Evidence:**
  ```python
  # cti.py
  def get_cti_records(skip: int = 0, limit: int = 100, ...):
      records = db.query(CTIRecord).offset(skip).limit(limit).all()
  ```
- **Vulnerability Classification:** CWE-770 (Allocation of Resources Without Limits or Throttling), OWASP API4:2023 (Unrestricted Resource Consumption).
- **Status:** **POTENTIAL RISK.**
- **Exploitability Conditions:** While a default `limit: int = 100` parameter is defined, FastAPI does not enforce a maximum ceiling via `Query(..., le=100)`. A client can send `GET /api/cti/?limit=1000000`.
- **Actual Impact:** Database memory spike, thread starvation, and Denial of Service under concurrent large queries.
- **Confidence Level:** Medium.
- **Remediation:** Enforce parameter constraints:
  ```python
  limit: int = Query(default=100, ge=1, le=200)
  ```

---

### Finding SEC-08: Missing Ciphertext Length and Truncation Validation
- **File & Line Range:** `backend/app/privacy/engine.py`, Lines 17–20
- **Source Evidence:**
  ```python
  def decrypt_data(encrypted_data: bytes) -> str:
      nonce = encrypted_data[:12]
      ciphertext = encrypted_data[12:]
      return aesgcm.decrypt(nonce, ciphertext, None).decode('utf-8')
  ```
- **Vulnerability Classification:** CWE-129 (Improper Validation of Array Index), OWASP A04:2021 (Insecure Design).
- **Status:** **CONFIRMED VULNERABILITY.**
- **Exploitability Conditions:** AES-GCM requires a 12-byte nonce and a 16-byte authentication tag (minimum 28 bytes total). If `encrypted_data` contains fewer than 28 bytes (e.g. empty bytes `b""` or truncated inputs), slicing `[:12]` produces an invalid/truncated nonce without error checking, and `aesgcm.decrypt` raises an unhandled `cryptography.exceptions.InvalidTag` exception.
- **Actual Impact:** Internal Server Error (HTTP 500) unhandled crash on malformed payloads.
- **Confidence Level:** High.
- **Remediation:** Validate minimum payload length before decryption:
  ```python
  if not encrypted_data or len(encrypted_data) < 28:
      raise ValueError("Invalid ciphertext: payload must be at least 28 bytes (12-byte nonce + 16-byte tag).")
  ```

---

### Finding SEC-09: Insecure Pseudo-Random Number Generator in Differential Privacy
- **File & Line Range:** `backend/app/privacy/engine.py`, Lines 32–39
- **Source Evidence:**
  ```python
  def apply_laplace_noise(value: float, sensitivity: float, epsilon: float) -> float:
      """
      Applies Laplace noise to a numerical value for Differential Privacy.
      M(D) = f(D) + Lap(0, Δf / ε)
      """
      scale = get_laplace_scale(sensitivity, epsilon)
      noise = float(np.random.laplace(0, scale))
      return float(value + noise)
  ```
- **Vulnerability Classification:** CWE-338 (Use of Cryptographically Weak Pseudo-Random Number Generator), OWASP A02:2021 (Cryptographic Failures).
- **Status:** **CONFIRMED VULNERABILITY.**
- **Exploitability Conditions:** `np.random.laplace` relies on NumPy's default Mersenne Twister (MT19937) pseudo-random number generator, which is **not cryptographically secure**. Standard PRNG state can be completely reconstructed after observing 624 consecutive outputs.
- **Actual Impact:** In differential privacy mechanisms, predictable noise allows an adversary to model PRNG state, subtract the injected noise, and reconstruct the underlying private dataset, completely undermining theoretical $(\epsilon, 0)$-differential privacy guarantees.
- **Confidence Level:** High.
- **Remediation:** Use cryptographically secure randomness (e.g. `secrets` or `random.SystemRandom`) with discrete or snapping Laplace mechanisms (e.g. Mironov, 2012; diffprivlib) to prevent reconstruction and floating-point timing attacks.

---

### Finding SEC-10: Hypothetical In-Memory Token Caching Vulnerability Analysis
- **Target Component:** `backend/app/api/deps.py:13–25` (`get_current_user`)
- **Vulnerability Classification:** CWE-384 (Session Fixation / Replay), OWASP A07:2021 (Identification and Authentication Failures).
- **Status:** **POTENTIAL RISK (SCENARIO ANALYSIS).**
- **Hypothetical Change:** If a developer introduces an in-memory dictionary cache:
  ```python
  _USER_CACHE = {}  # {token: user}
  def get_current_user(...):
      if token in _USER_CACHE:
          return _USER_CACHE[token]
  ```
- **Security Vulnerabilities Introduced:**
  1. **Token Expiration Invalidation Bypass:** The cache key is the raw token string. Once cached, `jwt.decode` expiration checks (`exp`) are never re-evaluated. Expired tokens remain valid indefinitely until process restart.
  2. **Memory Leak / Denial of Service:** An attacker generating random invalid tokens could flood the unbounded in-memory cache dictionary, consuming server RAM.
  3. **Role & Permission Desynchronization:** If an administrator disables a user or demotes their role from `ADMIN` to `ANALYST` in the database, the cached user object retains the old privileges.
- **Remediation:** Use a bounded Redis cache with TTL matching the remaining token expiration duration, or re-verify token signatures and expiration on each invocation.

