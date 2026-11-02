# Blind Evaluation Methodology & 60-Question Test Suite

**Evaluation Target:** Universal Multi-Repository Generalization  
**Scope:** 3 Repositories $\times$ 20 Questions = **60 Unique Evaluation Questions**  
**Design Principle:** Generated strictly independently of CodeMind AI's internal state or answers.

---

## 1. Twenty Core Evaluation Dimensions

Each repository question set maps 1:1 to the 20 mandated technical dimensions:
1. Entrypoint detection
2. Architecture identification
3. Module relationships
4. Cross-file execution tracing
5. Direct function caller verification
6. Import dependency analysis
7. Circular dependency analysis
8. Database models & ORM
9. Schema and migration relationships
10. Authentication mechanisms
11. Authorization & RBAC enforcement
12. Configuration & environment management
13. API integration
14. Error handling & validation exceptions
15. Background tasks / asynchronous processing
16. Change-impact analysis
17. Security reasoning & vulnerabilities
18. Missing functionality / out-of-scope boundaries
19. Adversarial nonexistent entity rejection
20. Multi-turn follow-up consistency

---

## 2. Question Set A: `expertdecision` (Python Backend — Repo ID 46)

| Q# | Dimension | Evaluation Question |
| :--- | :--- | :--- |
| **ED-01** | Entrypoint | Identify the primary application entrypoint for the `expertdecision` backend. Show how the FastAPI application is initialized and where routers are included. |
| **ED-02** | Architecture | Describe the architectural layering of `expertdecision` (API $\to$ Services $\to$ Repositories $\to$ Models). Identify the primary directory for each layer. |
| **ED-03** | Module Relationships | Explain how `backend/app/api/decision_api.py` interacts with the service layer. Which service class does it instantiate or inject? |
| **ED-04** | Execution Tracing | Trace the complete execution flow of creating a decision alternative: from endpoint handler in `alternative_api.py` down to database insertion. |
| **ED-05** | Caller Verification | Identify the function responsible for database session creation in `backend/app/database/session.py`. List at least 3 distinct API router files that call or depend on it. |
| **ED-06** | Import Dependencies | Analyze the imports of `backend/app/models/decision.py`. Does it import from the repository layer or schemas? |
| **ED-07** | Circularity | Check for circular dependencies between `models/`, `schemas/`, and `services/` in `expertdecision`. Are there any runtime circular imports? |
| **ED-08** | Database Models | Identify the primary key, foreign keys, and relationships defined on the `Decision` model in `backend/app/models/`. |
| **ED-09** | Migrations | Does `expertdecision` use Alembic for database migrations? Where are the migration version scripts located? |
| **ED-10** | Authentication | How is user authentication implemented in `expertdecision`? Which file decodes JWT tokens and extracts user identity? |
| **ED-11** | Authorization | Trace how role-based access control (RBAC) is enforced on administrative endpoints (e.g. `role_api.py`). |
| **ED-12** | Configuration | How are environment variables and database URLs loaded in `backend/app/config/`? Does it use Pydantic `BaseSettings`? |
| **ED-13** | API Integration | How does `expertdecision` integrate with email or notification services (e.g. in `email_api.py` or `notification_api.py`)? |
| **ED-14** | Error Handling | How are 404 and 422 HTTP exceptions handled when an alternative or decision entity is not found? |
| **ED-15** | Background Tasks | Does `expertdecision` utilize FastAPI `BackgroundTasks`, Celery, or Redis for asynchronous job processing? |
| **ED-16** | Change Impact | If a new column `priority_level` is added to the `Decision` model, what schemas, repositories, and API routers are directly affected? |
| **ED-17** | Security Reasoning | Evaluate whether password hashes are exposed in user API responses or if unauthenticated users can access decision audit trails. |
| **ED-18** | Missing Functionality | Does `expertdecision` implement OAuth2 social login (Google/GitHub) or biometric authentication? |
| **ED-19** | Adversarial Entity | How does `DecisionBlockchainConsensusService` validate voting blocks in `expertdecision`? |
| **ED-20** | Follow-Up | Following Question 1, what port and host are configured by default in `main.py` or `run.py`? |

---

## 3. Question Set B: `RewardPoints Transfer` (TypeScript/React + FastAPI)

| Q# | Dimension | Evaluation Question |
| :--- | :--- | :--- |
| **RP-01** | Entrypoint | Identify the frontend entrypoint and the backend entrypoint in `RewardPoints Transfer`. Show `main.tsx` and `backend/app/main.py`. |
| **RP-02** | Architecture | Explain the fullstack architecture connecting the React frontend (Vite/Tailwind) to the FastAPI backend. |
| **RP-03** | Module Relationships | In `frontend/src/services/api.ts`, how is the Axios HTTP client configured (base URL, headers, interceptors)? |
| **RP-04** | Execution Tracing | Trace a points transfer request from the React UI (`TransferForm` or `TransferModal`) $\to$ API client $\to$ FastAPI endpoint $\to$ balance deduction in database. |
| **RP-05** | Caller Verification | Find the balance calculation function in the backend. Identify all callers across endpoints and services with exact file lines. |
| **RP-06** | Import Dependencies | Analyze the imports in `frontend/src/pages/Dashboard.tsx`. Which hooks, components, and services does it depend on? |
| **RP-07** | Circularity | Are there any circular imports between frontend context providers (`AuthContext`) and API service modules? |
| **RP-08** | Database Models | Identify the database models representing users, point balances, and transfer transactions in `backend/app/models/`. |
| **RP-09** | Migrations | Trace the Alembic migrations in `backend/alembic/versions/`. What initial tables are created? |
| **RP-10** | Authentication | How is JWT token storage and injection handled on the frontend? Does it use `localStorage`, memory, or cookies? |
| **RP-11** | Authorization | How does the backend prevent a user from transferring more points than their verified available balance? |
| **RP-12** | Configuration | How does the frontend read `VITE_API_URL` and what fallback default is defined in `.env.example`? |
| **RP-13** | API Integration | What HTTP status code and response payload are returned when a points transfer succeeds vs when balance is insufficient? |
| **RP-14** | Error Handling | How are backend validation errors (e.g. HTTP 422) captured and displayed to the user in React toast/alert components? |
| **RP-15** | Background Tasks | Does the points transfer system send background email notifications or webhooks after a transfer completes? |
| **RP-16** | Change Impact | If a transfer fee percentage is added to transfers, what frontend form components, schemas, and backend transaction models must change? |
| **RP-17** | Security Reasoning | Is there a race condition or double-spending vulnerability if two points transfer requests are submitted concurrently for the same balance? |
| **RP-18** | Missing Functionality | Does `RewardPoints Transfer` implement cryptocurrency conversion or external bank payout gateways (Stripe/PayPal)? |
| **RP-19** | Adversarial Entity | Trace how `QuantumLedgerProofValidator` verifies transfer validity in `RewardPoints Transfer`. |
| **RP-20** | Follow-Up | Following Question 4, how does the frontend UI update the displayed user balance after the transfer API returns success? |

---

## 4. Question Set C: `TokenPool` (Mixed-Language — Repo ID 45)

| Q# | Dimension | Evaluation Question |
| :--- | :--- | :--- |
| **TP-01** | Entrypoint | Identify the server entrypoint in `TokenPool` and show how Gunicorn and Uvicorn workers are configured in `gunicorn.conf.py`. |
| **TP-02** | Architecture | Describe the multi-container architecture in `docker-compose.production.yml` (backend, frontend, Nginx, PostgreSQL). |
| **TP-03** | Module Relationships | Explain how Nginx (`nginx/nginx.conf` or `default.conf`) routes requests between static frontend assets and the FastAPI `/api` proxy. |
| **TP-04** | Execution Tracing | Trace how a token capacity order or dispute is created in the backend API and persisted to PostgreSQL. |
| **TP-05** | Caller Verification | Find the database session dependency in `backend/app/database.py`. Identify at least 3 distinct API routers that depend on it. |
| **TP-06** | Import Dependencies | Analyze the dependencies in `backend/requirements.txt` vs what is imported in `backend/app/main.py`. |
| **TP-07** | Circularity | Check whether any circular import exists between `backend/app/models/` and `backend/app/schemas/`. |
| **TP-08** | Database Models | Identify the schema for token providers, pools, and capacity allocations in `backend/app/models/`. |
| **TP-09** | Migrations | Inspect `alembic.ini` and `alembic/versions/`. What is the latest revision identifier in `TokenPool`? |
| **TP-10** | Authentication | How is API key or bearer token authentication handled for AI token providers connecting to TokenPool? |
| **TP-11** | Authorization | How does TokenPool segregate capacity provider permissions from consumer marketplace permissions? |
| **TP-12** | Configuration | How does `TokenPool` handle production environment configuration in `.env.production.example`? |
| **TP-13** | API Integration | How does TokenPool connect to external LLM providers (e.g. OpenAI, Anthropic, Gemini) to verify token quotas? |
| **TP-14** | Error Handling | How are provider connection timeouts and token exhaustion errors handled and reported to consumers? |
| **TP-15** | Background Tasks | Does TokenPool use Celery, Redis, or background threads for periodic health checks of connected token pools? |
| **TP-16** | Change Impact | If a provider rating score is added, what database tables, provider schemas, and marketplace views are affected? |
| **TP-17** | Security Reasoning | Evaluate whether provider API keys are stored in plaintext or encrypted at rest in the database. |
| **TP-18** | Missing Functionality | Does TokenPool implement an automated credit card billing system or automatic invoice generation? |
| **TP-19** | Adversarial Entity | Explain how `ZeroKnowledgeTokenProofService` generates validity proofs for token allocations in TokenPool. |
| **TP-20** | Follow-Up | Following Question 2, what port does Nginx expose to external traffic, and how is SSL termination configured? |

---

> [!NOTE]
> **Status:** Strictly static question formulation. **No queries have been submitted to CodeMind.**

