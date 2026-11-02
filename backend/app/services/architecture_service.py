import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import or_, not_, func
from sqlalchemy.orm import Session

from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.knowledge_graph import GraphEdge, GraphNode
from backend.app.models.repository import Repository

logger = logging.getLogger(__name__)


@dataclass
class FileRoleClassifier:
    """
    Classifies repository files into architectural roles:
    - core_framework: Reusable framework library internals (e.g. fastapi/, pydantic/, flask/)
    - core_app: User application logic (e.g. app/, src/, backend/)
    - test: Unit/integration test suites (e.g. tests/, spec/)
    - example_tutorial: Documentation tutorials and example apps (e.g. docs_src/, examples/)
    - documentation: Markdown and RST documentation files (e.g. docs/, doc/)
    - configuration: Project manifests, configs, and build files
    - script: Tooling and CI automation (e.g. scripts/, .github/)
    """
    @classmethod
    def classify(cls, file_path: str, repo_name: str = "", project_type: str = "") -> str:
        p = file_path.replace("\\", "/").lower()
        parts = p.split("/")
        top = parts[0] if len(parts) > 1 else ""
        filename = parts[-1]

        # 1. Tests
        if top in {"tests", "test", "spec", "__tests__", "testing"} or filename.startswith("test_") or filename.endswith("_test.py"):
            return "test"

        # 2. Examples / Tutorials
        if top in {"docs_src", "examples", "samples", "demos", "tutorials"}:
            return "example_tutorial"

        # 3. Documentation
        if top in {"docs", "doc"} or filename.endswith((".md", ".rst", ".adoc")):
            return "documentation"

        # 4. Manifests & Configs
        if filename in {
            "pyproject.toml", "setup.py", "setup.cfg", "package.json", "tsconfig.json",
            "cargo.toml", "go.mod", "pom.xml", "build.gradle", "requirements.txt",
            "dockerfile", "docker-compose.yml", "license", "citation.cff"
        }:
            return "configuration"

        # 5. Scripts & Tooling
        if top in {"scripts", "tools", "ci", ".github", "bin"}:
            return "script"

        # 6. Core Framework vs Core App
        clean_repo = repo_name.lower().replace("-", "_").replace(" ", "_")
        if top == clean_repo or top == "fastapi" or project_type in ("framework", "library"):
            if top not in {"docs", "docs_src", "tests", "scripts"}:
                return "core_framework"

        return "core_app"

@dataclass
class DiscoveredComponent:
    component_type: str  # entry_point, frontend_ui, api_route, service, persistence, auth, integration, background_job, config, test
    name: str
    file_path: str
    start_line: int
    end_line: int
    confidence: float
    description: str
    snippet: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_type": self.component_type,
            "name": self.name,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "confidence": self.confidence,
            "description": self.description,
            "snippet": self.snippet,
            "metadata": self.metadata,
        }


@dataclass
class DiscoveredFlow:
    source_component: str
    target_component: str
    flow_type: str  # routes_to, calls, queries, authenticates_with, integrates_with
    evidence: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_component": self.source_component,
            "target_component": self.target_component,
            "flow_type": self.flow_type,
            "evidence": self.evidence,
        }


@dataclass
class RepositoryArchitecture:
    repository_id: int
    repository_name: str
    project_type: str  # monolith, fullstack, frontend, backend, microservice, monorepo, mobile, library, cli
    primary_languages: List[str]
    frameworks: List[str]
    components: List[DiscoveredComponent]
    components_by_type: Dict[str, List[DiscoveredComponent]]
    flows: List[DiscoveredFlow]
    verified_layers: List[str]
    unverified_layers: List[str]
    revision: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_components_of_type(self, comp_type: str, sub_type: Optional[str] = None) -> List[DiscoveredComponent]:
        comps = self.components_by_type.get(comp_type, [])
        if sub_type:
            comps = [c for c in comps if c.metadata.get("sub_type") == sub_type]
        return sorted(comps, key=lambda c: c.confidence, reverse=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "repository_name": self.repository_name,
            "project_type": self.project_type,
            "primary_languages": self.primary_languages,
            "frameworks": self.frameworks,
            "components": [c.to_dict() for c in self.components],
            "components_by_type": {
                k: [c.to_dict() for c in v] for k, v in self.components_by_type.items()
            },
            "flows": [f.to_dict() for f in self.flows],
            "verified_layers": self.verified_layers,
            "unverified_layers": self.unverified_layers,
            "revision": self.revision,
            "created_at": self.created_at.isoformat(),
        }


class ArchitectureAnalysisEngine:
    """
    Generalized Repository Intelligence & Architecture Analysis Engine.
    Discovers architecture components, execution flows, and technology layers
    from actual repository evidence across any programming language, framework,
    or project layout without hardcoded assumptions.
    """

    # In-memory architecture cache keyed by (repo_id, repo_name) -> (cache_key, timestamp, RepositoryArchitecture)
    _cache: Dict[Any, Tuple[str, datetime, RepositoryArchitecture]] = {}

    @classmethod
    def invalidate_cache(cls, repository_id: Optional[int] = None) -> None:
        """Invalidates cached repository architecture analysis."""
        if repository_id is not None:
            to_del = [k for k in cls._cache.keys() if (k == repository_id or (isinstance(k, tuple) and k[0] == repository_id))]
            for k in to_del:
                cls._cache.pop(k, None)
            logger.info(f"Invalidated architecture cache for repository_id={repository_id}")
        else:
            cls._cache.clear()
            logger.info("Invalidated entire architecture cache")

    @classmethod
    def get_repository_architecture(
        cls,
        db: Session,
        repository_id: int,
        force_refresh: bool = False,
    ) -> RepositoryArchitecture:
        """
        Retrieves or computes evidence-backed repository architecture representation.
        Automatically invalidates cache if repository revision, files, or indexed state has updated.
        """
        repo = db.query(Repository).filter(Repository.id == repository_id).first()
        if not repo:
            raise ValueError(f"Repository {repository_id} not found")

        chunk_count = db.query(func.count(CodeChunk.id)).filter(CodeChunk.repository_id == repo.id).scalar() or 0
        file_count = db.query(func.count(IndexedFile.id)).filter(IndexedFile.repository_id == repo.id).scalar() or 0
        max_chunk_id = db.query(func.max(CodeChunk.id)).filter(CodeChunk.repository_id == repo.id).scalar() or 0
        cache_key = f"{repo.id}:{repo.name}:{repo.current_revision or ''}:{repo.last_synced_commit_sha or ''}:{repo.last_indexed_at or ''}:{file_count}:{chunk_count}:{max_chunk_id}"
        cache_dict_key = (repo.id, repo.name)

        if not force_refresh and cache_dict_key in cls._cache:
            stored_key, _, arch = cls._cache[cache_dict_key]
            if stored_key == cache_key:
                return arch

        arch = cls._analyze_repository(db, repo)
        cls._cache[cache_dict_key] = (cache_key, datetime.now(timezone.utc), arch)
        return arch

    @classmethod
    def _analyze_repository(cls, db: Session, repo: Repository) -> RepositoryArchitecture:
        """Performs repository-wide evidence discovery across all indexed files, chunks, and symbols."""
        files = db.query(IndexedFile).filter(IndexedFile.repository_id == repo.id).all()
        chunks = (
            db.query(CodeChunk)
            .filter(
                CodeChunk.repository_id == repo.id,
                not_(CodeChunk.file_path.ilike("%docs/%")),
                not_(CodeChunk.file_path.ilike("%docs_src/%")),
                not_(CodeChunk.file_path.ilike("%uploads/%")),
            )
            .all()
        )
        symbols = db.query(CodeSymbol).filter(CodeSymbol.repository_id == repo.id).all()

        file_paths = [f.path for f in files]
        if not file_paths and chunks:
            file_paths = list({c.file_path for c in chunks})

        # 1. Discover Languages and Frameworks
        languages = cls._detect_languages(file_paths, chunks)
        frameworks = cls._detect_frameworks(file_paths, chunks, repo.tech_stack)

        # 2. Project Layout & Type Detection
        project_type = cls._detect_project_type(file_paths, languages, frameworks, repo.name or '')

        # 3. Discover Components
        components: List[DiscoveredComponent] = []
        seen_component_keys: Set[Tuple[str, str]] = set()

        def add_comp(comp: DiscoveredComponent):
            key = (comp.component_type, comp.file_path)
            # Allow multiple components in same file if distinct names and ranges
            name_key = (comp.component_type, f"{comp.file_path}:{comp.name}")
            if name_key not in seen_component_keys:
                seen_component_keys.add(name_key)
                components.append(comp)

        # A. Entry Points & Bootstrap
        cls._discover_entry_points(chunks, file_paths, add_comp, project_type, repo.name or '')

        # B. Routes, APIs & Controllers
        cls._discover_api_routes(chunks, symbols, file_paths, add_comp, project_type, repo.name or '')

        # C. Services & Business Logic
        cls._discover_services(chunks, symbols, file_paths, add_comp, project_type, repo.name or '')

        # D. Database Models & Persistence
        cls._discover_persistence(chunks, symbols, file_paths, add_comp, project_type, repo.name or '')

        # E. Authentication & Authorization
        cls._discover_auth(chunks, file_paths, add_comp, project_type, repo.name or '')

        # F. External Integrations
        cls._discover_integrations(chunks, file_paths, add_comp)

        # G. Background Jobs & Workers
        cls._discover_background_jobs(chunks, file_paths, add_comp, project_type, repo.name or '')

        # H. Configuration & Deployment Infrastructure
        cls._discover_configuration(chunks, file_paths, add_comp, project_type, repo.name or '')

        # I. Frontend UI Components
        cls._discover_frontend_components(chunks, file_paths, add_comp)

        # J. Mobile Native Components (Android / Host Bridges)
        cls._discover_mobile_native_components(chunks, file_paths, add_comp)

        # K. Tests
        cls._discover_tests(file_paths, add_comp)

        # Group components by type
        components_by_type: Dict[str, List[DiscoveredComponent]] = {}
        for comp in components:
            components_by_type.setdefault(comp.component_type, []).append(comp)
            sub_type = comp.metadata.get("sub_type")
            if sub_type:
                components_by_type.setdefault(sub_type, []).append(comp)

        # 4. Trace Data Flow & Execution Chains
        flows = cls._trace_execution_flows(components_by_type, chunks, db, repo.id)

        # 5. Verified vs Unverified Layers
        verified_layers = []
        unverified_layers = []

        layer_names = [
            ("entry_point", "Application entry points and startup configuration"),
            ("api_route", "API routes, controllers, and request handlers"),
            ("service", "Business logic and domain service modules"),
            ("persistence", "Database models, schemas, and persistence layer"),
            ("auth", "Authentication, token handling, and access control"),
            ("integration", "External integrations and third-party API clients"),
            ("background_job", "Background tasks, workers, and scheduled jobs"),
            ("config", "Configuration, environment variables, and deployment manifests"),
            ("frontend_ui", "Frontend user interface components and views"),
            ("test", "Automated test suites and test fixtures"),
        ]

        for layer_key, layer_label in layer_names:
            if components_by_type.get(layer_key):
                verified_layers.append(layer_label)
            else:
                unverified_layers.append(layer_label)

        return RepositoryArchitecture(
            repository_id=repo.id,
            repository_name=repo.name,
            project_type=project_type,
            primary_languages=languages,
            frameworks=frameworks,
            components=components,
            components_by_type=components_by_type,
            flows=flows,
            verified_layers=verified_layers,
            unverified_layers=unverified_layers,
            revision=repo.current_revision or repo.last_synced_commit_sha,
        )

    # -------------------------------------------------------------------------
    # Detection Sub-Routines
    # -------------------------------------------------------------------------

    @classmethod
    def _detect_languages(cls, file_paths: List[str], chunks: List[CodeChunk]) -> List[str]:
        ext_counts: Dict[str, int] = {}
        for p in file_paths:
            ext = Path(p).suffix.lower()
            if ext:
                ext_counts[ext] = ext_counts.get(ext, 0) + 1

        lang_map = {
            ".py": "Python",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".dart": "Dart",
            ".go": "Go",
            ".rs": "Rust",
            ".java": "Java",
            ".kt": "Kotlin",
            ".kts": "Kotlin",
            ".cs": "C#",
            ".php": "PHP",
            ".rb": "Ruby",
            ".swift": "Swift",
            ".cpp": "C++",
            ".c": "C",
            ".html": "HTML",
            ".css": "CSS",
            ".sql": "SQL",
        }

        detected = {}
        for ext, count in ext_counts.items():
            if ext in lang_map:
                lang = lang_map[ext]
                detected[lang] = detected.get(lang, 0) + count

        sorted_langs = sorted(detected.items(), key=lambda x: x[1], reverse=True)
        return [l[0] for l in sorted_langs]

    @classmethod
    def _detect_frameworks(cls, file_paths: List[str], chunks: List[CodeChunk], tech_stack: Optional[Any]) -> List[str]:
        frameworks: Set[str] = set()
        if tech_stack and isinstance(tech_stack, dict):
            for cat in ["frontend", "backend", "database"]:
                for item in tech_stack.get(cat, []):
                    if isinstance(item, dict) and "name" in item:
                        # Only include genuine frameworks, libraries, and ORMs; exclude raw programming languages, databases, and infra tools
                        cat_type = str(item.get("category", "")).lower()
                        item_type = str(item.get("type", "")).lower()
                        item_name = item["name"]
                        if item_name in ("Python", "JavaScript", "TypeScript", "HTML", "CSS", "Go", "Rust", "Java", "Kotlin", "C#", "Dart", "Docker", "Docker Compose", "PostgreSQL", "MySQL", "SQLite", "Redis", "MongoDB"):
                            continue
                        if any(k in cat_type for k in ["framework", "orm", "library"]) or any(k in item_type for k in ["framework", "orm", "library"]):
                            frameworks.add(item_name)
                        elif item_name in ("FastAPI", "Flask", "Django", "SQLAlchemy", "Alembic", "Express", "React", "Vue", "Flutter", "Spring Boot"):
                            frameworks.add(item_name)

        # Scan code chunks for framework identifiers using strict import or instantiation patterns
        for c in chunks[:100]:
            t = c.chunk_text
            p = c.file_path.lower()
            if any(ex in p for ex in ["tests/", "test/", "uploads/", "fixtures/", "docs/", "alembic/"]):
                continue

            if re.search(r'\b(?:from\s+fastapi\b|import\s+fastapi\b|\bFastAPI\s*\()', t):
                frameworks.add("FastAPI")
            if re.search(r'\b(?:from\s+flask\b|import\s+flask\b|\bFlask\s*\()', t):
                frameworks.add("Flask")
            if re.search(r'\b(?:from\s+django\b|import\s+django\b)', t):
                frameworks.add("Django")
            if re.search(r'\b(?:express\s*\(\s*\)|from\s+[\'"]express[\'"]|require\s*\(\s*[\'"]express[\'"]\))', t):
                frameworks.add("Express")
            if re.search(r'\b(?:from\s+[\'"]react[\'"]|import\s+React\b)', t):
                frameworks.add("React")
            if re.search(r'\b(?:package:flutter/|\brunApp\s*\()', t):
                frameworks.add("Flutter")
            if re.search(r'\b(?:@SpringBootApplication\b|org\.springframework\b)', t):
                frameworks.add("Spring Boot")
            if re.search(r'\b(?:gin-gonic/gin\b|\bgin\.Default\s*\()', t):
                frameworks.add("Gin")
            if re.search(r'\b(?:actix_web::|\buse\s+actix_web\b)', t):
                frameworks.add("Actix-web")
            if re.search(r'\b(?:axum::|\buse\s+axum\b)', t):
                frameworks.add("Axum")
            if re.search(r'\bMicrosoft\.AspNetCore\b', t):
                frameworks.add("ASP.NET Core")
            if re.search(r'\b(?:from\s+[\'"]vue[\'"]|\bcreateApp\s*\()', t):
                frameworks.add("Vue")
            if re.search(r'\bfrom\s+[\'"]svelte[\'"]', t):
                frameworks.add("Svelte")
            if re.search(r'\b@angular/', t):
                frameworks.add("Angular")
            if re.search(r'\b(?:from\s+[\'"]next(?:/server|/image|/router|/navigation)?[\'"]|require\s*\(\s*[\'"]next[\'"]\))', t):
                frameworks.add("Next.js")
            if re.search(r'\bfrom\s+[\'"]nuxt[\'"]', t):
                frameworks.add("Nuxt")
            if re.search(r'\b@nestjs/', t):
                frameworks.add("NestJS")
            if re.search(r'\b(?:from\s+[\'"]react-native[\'"]|\bAppRegistry\b)', t):
                frameworks.add("React Native")

        # Scan manifests in file paths
        p_lower = [fp.lower().replace("\\", "/") for fp in file_paths]
        if any("pubspec.yaml" in fp for fp in p_lower):
            frameworks.add("Flutter")
        if any("pom.xml" in fp or "build.gradle" in fp for fp in p_lower):
            if not any(f in frameworks for f in ["Spring Boot", "Android"]):
                frameworks.add("JVM")

        return sorted(list(frameworks))

    @classmethod
    def _detect_project_type(cls, file_paths: List[str], languages: List[str], frameworks: List[str], repo_name: str = "") -> str:
        clean_repo_name = (repo_name or "").lower().replace("-", "_").replace(" ", "_")
        if clean_repo_name:
            p_check = [fp.lower().replace("\\", "/") for fp in file_paths]
            has_matching_pkg = any(p.startswith(f"{clean_repo_name}/") or p.startswith(f"src/{clean_repo_name}/") for p in p_check)
            if has_matching_pkg:
                has_init = any(p == f"{clean_repo_name}/__init__.py" or p == f"src/{clean_repo_name}/__init__.py" for p in p_check)
                if has_init:
                    return "framework" if any(f in clean_repo_name for f in ["fastapi", "flask", "django", "express", "gin"]) else "library"
        p_lower = [fp.lower().replace("\\", "/") for fp in file_paths]

        if "Flutter" in frameworks or "React Native" in frameworks or any(p.startswith("lib/main.dart") or "android/" in p or "ios/" in p for p in p_lower):
            return "mobile"

        has_apps = any(p.startswith("apps/") or "/apps/" in p for p in p_lower)
        has_packages = any(p.startswith("packages/") or "/packages/" in p for p in p_lower)
        # Only count genuine standalone microservice top-level directories, not standard internal app service directories
        services_count = sum(1 for p in p_lower if (p.startswith("services/") or "/services/" in p) and not any(p.startswith(prefix) for prefix in ["lib/", "backend/", "app/", "src/"]))

        if (has_apps and has_packages) or services_count > 1:
            return "monorepo"

        fe_langs = {"HTML", "CSS", "TypeScript", "JavaScript"}
        be_langs = {"Python", "Go", "Rust", "Java", "Kotlin", "C#", "PHP", "Ruby"}

        has_fe = any(l in fe_langs for l in languages) or any(f in frameworks for f in ["React", "Vue", "Angular", "Next.js", "Vite", "Svelte", "Nuxt"])
        has_be = any(l in be_langs for l in languages) or any(f in frameworks for f in ["FastAPI", "Flask", "Django", "Express", "Spring Boot", "Gin", "NestJS", "Actix-web", "Axum", "ASP.NET Core", "Laravel", "Rails"])

        if has_fe and has_be:
            return "fullstack"
        if has_fe and not has_be:
            return "frontend"
        if has_be and not has_fe:
            return "backend"

        return "monolith"

    @classmethod
    def _discover_entry_points(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp, project_type: str = "monolith", repo_name: str = ""):
        """Discovers application bootstrap and entry points across technologies."""
        if project_type in ("framework", "library"):
            clean_repo = repo_name.lower().replace("-", "_").replace(" ", "_")
            for p in file_paths:
                p_norm = p.lower().replace("\\\\", "/")
                if p_norm.endswith("__init__.py") and not any(ex in p_norm for ex in ["tests/", "test/", "docs/", "docs_src/", "examples/"]):
                    if clean_repo and (p_norm == f"{clean_repo}/__init__.py" or p_norm == f"src/{clean_repo}/__init__.py"):
                        init_chunks = [c for c in chunks if c.file_path.replace("\\\\", "/").lower() == p_norm]
                        snippet = init_chunks[0].chunk_text[:350] if init_chunks else ""
                        add_comp(DiscoveredComponent(
                            component_type="entry_point",
                            name=f"Framework Package Root (`{p}`)",
                            file_path=p,
                            start_line=1,
                            end_line=len(snippet.splitlines()) or 50,
                            confidence=0.99,
                            description=f"Core framework package entry point exporting public APIs and top-level classes (`{p}`).",
                            snippet=snippet,
                            metadata={"sub_type": "framework_package_root", "role": "core_framework"}
                        ))
        entry_patterns = [
            # Python
            (r'\b(?:app|application)\s*=\s*(?:FastAPI|Flask|Sanic|Tornado)\b', "Web Application Instance"),
            (r'\bif\s+__name__\s*==\s*["\']__main__["\']\s*:', "Main Execution Block"),
            (r'\bdef\s+main\s*\(\s*\)\s*:', "Main Function"),
            # JS/TS
            (r'\b(?:const|let|var)\s+app\s*=\s*express\s*\(\s*\)', "Express Application Instance"),
            (r'\bapp\.listen\s*\(', "HTTP Server Listener"),
            (r'\bReactDOM\.(?:createRoot|render)\s*\(', "React UI Root Render"),
            (r'\bNestFactory\.create\s*\(', "NestJS Application Factory"),
            # Dart / Flutter
            (r'\bvoid\s+main\s*\(\s*\)\s*\{[\s\S]*?\brunApp\s*\(', "Flutter Application Entry"),
            (r'\brunApp\s*\(', "Flutter App Runner"),
            # Go
            (r'\bfunc\s+main\s*\(\s*\)\s*\{', "Go Main Function"),
            # Rust
            (r'\bfn\s+main\s*\(\s*\)\s*\{', "Rust Main Function"),
            # Java / Kotlin
            (r'@SpringBootApplication', "Spring Boot Application Annotation"),
            (r'\bpublic\s+static\s+void\s+main\s*\(\s*String', "Java Main Method"),
            # C#
            (r'\bWebApplication\.CreateBuilder\s*\(', "ASP.NET Core WebApplication Builder"),
        ]

        # Prioritize standard entry point filenames
        priority_files = {
            "main.py", "app.py", "server.py", "wsgi.py", "asgi.py", "manage.py",
            "index.ts", "index.tsx", "main.ts", "main.tsx", "server.ts", "server.js",
            "app.ts", "app.tsx", "src/App.tsx", "src/main.tsx", "src/index.tsx",
            "lib/main.dart", "cmd/server/main.go", "main.go", "src/main.rs", "main.rs",
            "Program.cs", "Startup.cs"
        }

        # Directories that should NEVER be considered primary entry points
        excluded_dirs = [
            "services/", "models/", "repositories/", "schemas/", "utils/", "helpers/",
            "migrations/", "alembic/", "tests/", "test/", "uploads/", "fixtures/",
            "docs/", "node_modules/", "site-packages/", ".venv/", "venv/", "examples/"
        ]

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_name = Path(p).name.lower()
            p_full_lower = p.lower()

            if any(ex in p_full_lower for ex in excluded_dirs):
                continue

            txt = c.chunk_text
            is_priority = (p_name in priority_files or any(p.endswith(pf) for pf in priority_files))

            matched = False
            for pat, desc in entry_patterns:
                m = re.search(pat, txt)
                if m:
                    # For generic main execution blocks or main functions, require that the file is a priority file
                    # or located near repository root / cmd directory, avoiding helper/service scripts
                    if pat in (r'\bif\s+__name__\s*==\s*["\']__main__["\']\s*:', r'\bdef\s+main\s*\(\s*\)\s*:'):
                        if not is_priority and p.count("/") > 2 and not any(k in p_full_lower for k in ["/cmd/", "/bin/", "/cli/"]):
                            continue

                    conf = 0.99 if is_priority else 0.90
                    add_comp(DiscoveredComponent(
                        component_type="entry_point",
                        name=f"Entry: {Path(p).name}",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=conf,
                        description=f"{desc} in `{p}`",
                        snippet=txt[:250],
                    ))
                    matched = True
                    break

            if not matched and is_priority:
                # If named like main entry file and contains functions/classes or router inclusion
                if any(k in txt for k in ["FastAPI", "Flask", "router", "include_router", "express", "App", "main", "listen", "runApp"]):
                    add_comp(DiscoveredComponent(
                        component_type="entry_point",
                        name=f"Entry: {Path(p).name}",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.95,
                        description=f"Application bootstrap file `{p}`",
                        snippet=txt[:250],
                    ))

    @classmethod
    def _discover_api_routes(cls, chunks: List[CodeChunk], symbols: List[CodeSymbol], file_paths: List[str], add_comp, project_type: str = "monolith", repo_name: str = ""):
        """Discovers routes, API endpoints, and controllers across technologies."""
        if project_type in ("framework", "library"):
            routing_file = next((p for p in file_paths if "routing.py" in p or "router.py" in p), None)
            if routing_file:
                add_comp(DiscoveredComponent(
                    component_type="api_route",
                    name="Framework Routing Engine (`APIRouter` / `APIRoute`)",
                    file_path=routing_file,
                    start_line=1,
                    end_line=50,
                    confidence=0.99,
                    description=f"Framework routing engine (`{routing_file}`), defining `APIRouter`, `APIRoute`, and route decorator dispatch (`get`, `post`, etc.).",
                    snippet="",
                    metadata={"sub_type": "framework_routing_engine"}
                ))
        route_decorator_patterns = [
            # Python FastAPI / Flask / Django
            r'@(?:router|app|api_router|bp|blueprint)\.(?:get|post|put|delete|patch|options|head|route|api_route)\s*\(\s*["\']([^"\']+)["\']',
            # Express / JS / TS
            r'\b(?:app|router|api)\.(?:get|post|put|delete|patch|use)\s*\(\s*["\']([^"\']+)["\']',
            # Go Gin / Chi / Echo / net/http
            r'\b(?:r|router|api|group)\.(?:GET|POST|PUT|DELETE|PATCH|HandleFunc|Handle)\s*\(\s*["\']([^"\']+)["\']',
            # Java Spring Boot
            r'@(?:GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
            # ASP.NET Core
            r'\[(?:HttpGet|HttpPost|HttpPut|HttpDelete|Route)\s*\(\s*["\']([^"\']+)["\']',
            # Dart / Flutter Route table
            r'["\'](/[\w\-/]+)["\']\s*:\s*\(.*?\)\s*=>',
        ]

        route_dir_patterns = ["routes/", "routers/", "controllers/", "endpoints/", "api/", "handlers/", "views/"]

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/"]):
                continue

            txt = c.chunk_text
            for pat in route_decorator_patterns:
                for match in re.finditer(pat, txt):
                    route_path = match.group(1)
                    add_comp(DiscoveredComponent(
                        component_type="api_route",
                        name=f"Route `{route_path}`",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.95,
                        description=f"API Route `{route_path}` in `{p}`",
                        snippet=txt[:250],
                        metadata={"route_path": route_path},
                    ))

            # Check if file is in a dedicated routes/controllers directory and defines functions
            # Check if file is in a dedicated routes/api directory and defines route handlers
            route_handler_dirs = ["routes/", "routers/", "endpoints/", "api/handlers/", "api/routes/"]
            if any(rd in p_lower for rd in route_handler_dirs):
                if c.code_symbol or any(k in txt for k in ["def ", "function ", "func ", "router", "Router"]):
                    name = c.code_symbol or Path(p).stem
                    add_comp(DiscoveredComponent(
                        component_type="api_route",
                        name=f"Handler `{name}`",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.85,
                        description=f"Route handler `{name}` in `{p}`",
                        snippet=txt[:250],
                    ))

    @classmethod
    def _discover_services(cls, chunks: List[CodeChunk], symbols: List[CodeSymbol], file_paths: List[str], add_comp, project_type: str = "monolith", repo_name: str = ""):
        """Discovers domain services, business logic, state controllers, and managers."""
        service_dirs = ["services/", "service/", "business/", "domain/", "usecases/", "logic/", "managers/", "controllers/", "controller/", "bloc/", "cubit/", "store/"]

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/"]):
                continue

            txt = c.chunk_text
            is_service_dir = any(sd in p_lower for sd in service_dirs)

            # Class definitions ending with Service, Manager, Provider, Processor, Controller, Bloc, Cubit, Store, Notifier
            class_match = re.search(r'\bclass\s+([A-Za-z0-9_]*(?:Service|Manager|Processor|Provider|Usecase|Client|Controller|Bloc|Cubit|Store|Notifier|ViewModel))\b', txt)
            if class_match:
                s_name = class_match.group(1)
                add_comp(DiscoveredComponent(
                    component_type="service",
                    name=s_name,
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.95,
                    description=f"Domain service/controller `{s_name}` in `{p}`",
                    snippet=txt[:250],
                ))
            elif is_service_dir and (c.code_symbol or any(k in txt for k in ["def ", "class ", "function "])):
                s_name = c.code_symbol or Path(p).stem
                add_comp(DiscoveredComponent(
                    component_type="service",
                    name=s_name,
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.85,
                    description=f"Service component `{s_name}` in `{p}`",
                    snippet=txt[:250],
                ))

    @classmethod
    def _discover_persistence(cls, chunks: List[CodeChunk], symbols: List[CodeSymbol], file_paths: List[str], add_comp, project_type: str = "monolith", repo_name: str = ""):
        """Discovers database models, schemas, repositories, and persistence logic."""
        if project_type in ("framework", "library"):
            core_file = next((p for p in file_paths if p.replace("\\\\", "/").startswith(f"{repo_name.lower()}/") and p.endswith(".py")), "pyproject.toml")
            add_comp(DiscoveredComponent(
                component_type="persistence",
                name="Framework Architecture (Database-Agnostic)",
                file_path=core_file,
                start_line=1,
                end_line=50,
                confidence=0.99,
                description=f"{repo_name} is a framework library that does not bundle an internal database engine or database models. Applications integrate databases externally using dependency injection (`Depends(get_db)`). Tutorial models in `docs_src/` are client demonstration examples only.",
                snippet="",
                metadata={"sub_type": "framework_database_agnostic"}
            ))
        model_patterns = [
            # SQLAlchemy / Python
            (r'\bclass\s+([A-Za-z0-9_]+)\s*\(\s*(?:Base|Model|db\.Model)\s*\)', "SQLAlchemy"),
            # Pydantic / Tortoise / Peewee
            (r'\bclass\s+([A-Za-z0-9_]+)\s*\(\s*BaseModel\s*\)', "Pydantic"),
            # Django models
            (r'\bclass\s+([A-Za-z0-9_]+)\s*\(\s*models\.Model\s*\)', "Django"),
            # Java / Kotlin JPA / Spring Data
            (r'@Entity[\s\S]*?\bclass\s+([A-Za-z0-9_]+)', "JPA"),
            # Go GORM
            (r'\btype\s+([A-Za-z0-9_]+)\s+struct\s*\{[\s\S]*?gorm:', "GORM"),
            # Rust Diesel / SQLx
            (r'#\[derive\([^)]*(?:Queryable|Insertable|Model)[^)]*\)\][\s\S]*?\bstruct\s+([A-Za-z0-9_]+)', "Diesel"),
            # C# EF Core
            (r'\bpublic\s+class\s+([A-Za-z0-9_]+)\s*:\s*(?:DbContext|BaseEntity)', "EFCore"),
            # Dart / Flutter models & Freezed / JsonSerializable / Hive
            (r'\bclass\s+([A-Za-z0-9_]+)\s*(?:with\s+[A-Za-z0-9_,\s]+)?\{[\s\S]*?factory\s+\1\.fromJson', "DartModel"),
            (r'@JsonSerializable[\s\S]*?\bclass\s+([A-Za-z0-9_]+)', "DartJson"),
            (r'@HiveType[\s\S]*?\bclass\s+([A-Za-z0-9_]+)', "Hive"),
            # Prisma / Mongoose / TypeORM
            (r'\bmodel\s+([A-Za-z0-9_]+)\s*\{', "Prisma"),
            (r'\bconst\s+([A-Za-z0-9_]+Schema)\s*=\s*new\s+Schema', "Mongoose"),
        ]

        persistence_dirs = ["models/", "entities/", "schemas/", "repositories/", "repository/", "dao/", "db/models", "database/models"]

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/", "alembic/versions/"]):
                continue

            txt = c.chunk_text
            for pat, flavor in model_patterns:
                m = re.search(pat, txt)
                if m:
                    m_name = m.group(1)
                    is_orm = flavor in ("SQLAlchemy", "Django", "JPA", "GORM", "Diesel", "EFCore", "Prisma")
                    conf = 0.98 if (is_orm and "model" in p_lower) else (0.95 if is_orm else 0.80)
                    sub = "model" if is_orm else ("schema" if flavor == "Pydantic" else "model")
                    add_comp(DiscoveredComponent(
                        component_type="persistence",
                        name=f"Model: {m_name}",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=conf,
                        description=f"Data model/schema `{m_name}` in `{p}`",
                        snippet=txt[:250],
                        metadata={"sub_type": sub, "model_name": m_name, "flavor": flavor},
                    ))

            # Repository / DAO classes (strictly distinguishing DAO pattern classes from ORM database model tables)
            is_model_dir = any(pd in p_lower for pd in ["models/", "entities/", "schemas/"])
            repo_match = re.search(r'\bclass\s+([A-Za-z0-9_]*(?:Repository|DAO|Repo))\b', txt)
            if repo_match and not is_model_dir and not any(k in txt for k in ["(Base)", "db.Model", "__tablename__"]):
                r_name = repo_match.group(1)
                add_comp(DiscoveredComponent(
                    component_type="persistence",
                    name=f"Repository: {r_name}",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.95,
                    description=f"Persistence repository `{r_name}` in `{p}`",
                    snippet=txt[:250],
                    metadata={"sub_type": "repository", "repository_name": r_name},
                ))

            # Database session / connection providers (e.g. database.py, db.py, session.py with get_db, SessionLocal, create_engine)
            p_name = Path(p).name.lower()
            if p_name in ["database.py", "db.py", "session.py", "db_session.py", "connection.py", "db.ts", "database.ts"] or any(k in p_lower for k in ["core/database", "db/session", "db/database"]):
                if any(k in txt for k in ["SessionLocal", "create_engine", "get_db", "MongoClient", "DataSource", "Pool", "new PrismaClient"]):
                    add_comp(DiscoveredComponent(
                        component_type="persistence",
                        name=f"Database Provider: {Path(p).stem}",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.90,
                        description=f"Database session/connection provider in `{p}`",
                        snippet=txt[:250],
                        metadata={"sub_type": "db_session"},
                    ))

            # Files in models/ or schemas/ directory with symbols
            if any(pd in p_lower for pd in ["models/", "entities/", "schemas/"]):
                if c.code_symbol and not any(k in c.code_symbol.lower() for k in ["test", "mock"]):
                    add_comp(DiscoveredComponent(
                        component_type="persistence",
                        name=f"Model: {c.code_symbol}",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.85,
                        description=f"Persistence schema/symbol `{c.code_symbol}` in `{p}`",
                        snippet=txt[:250],
                        metadata={"sub_type": "model"},
                    ))
            elif any(pd in p_lower for pd in ["repositories/", "repository/", "dao/"]):
                if c.code_symbol and not any(k in c.code_symbol.lower() for k in ["test", "mock"]):
                    add_comp(DiscoveredComponent(
                        component_type="persistence",
                        name=f"Repository: {c.code_symbol}",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.85,
                        description=f"Repository symbol `{c.code_symbol}` in `{p}`",
                        snippet=txt[:250],
                        metadata={"sub_type": "repository"},
                    ))

    @classmethod
    def _discover_auth(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp, project_type: str = "monolith", repo_name: str = ""):
        """Discovers authentication, authorization, and security mechanisms."""
        if project_type in ("framework", "library"):
            sec_files = [p for p in file_paths if "security" in p.replace("\\\\", "/").lower() and not any(ex in p.lower() for ex in ["tests/", "docs/"])]
            for sf in sec_files:
                add_comp(DiscoveredComponent(
                    component_type="auth",
                    name=f"Security Scheme Utility: {Path(sf).stem}",
                    file_path=sf,
                    start_line=1,
                    end_line=50,
                    confidence=0.95,
                    description=f"Framework security utility and dependency schemes in `{sf}`. Note: {repo_name} is a framework providing security utilities; it does not contain built-in application user accounts, password databases, or user credential storage.",
                    snippet="",
                    metadata={"sub_type": "security_utility"}
                ))
        auth_patterns = [
            (r'\b(?:jwt\.encode|create_access_token|issue_token|generate_jwt)\b', "Token Creation (JWT/Session)"),
            (r'\b(?:jwt\.decode|verify_token|decode_jwt|validate_token)\b', "Token Validation (JWT/Session)"),
            (r'\b(?:bcrypt|argon2|hash_password|verify_password|password_hash)\b', "Password Hashing & Verification"),
            (r'\b(?:Depends\(get_current_user\)|login_required|auth_middleware|RequireAuth|check_permission)\b', "Route Authentication & Access Guard"),
            (r'\b(?:session\.get|session\["user"\]|session\["user_id"\])\b', "Session Management"),
            (r'\b(?:OAuth2|OAuth|GoogleAuth|GitHubAuth)\b', "OAuth / External Identity Provider"),
        ]

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/", "generate_docx", "generate_pdf", "reports/"]):
                continue

            txt = c.chunk_text
            for pat, desc in auth_patterns:
                if re.search(pat, txt):
                    if desc == "OAuth / External Identity Provider" and not any(k in txt for k in ["OAuth2PasswordBearer", "oauth_callback", "initiate_github_login", "OAuth", "GitHubOAuth"]):
                        continue
                    add_comp(DiscoveredComponent(
                        component_type="auth",
                        name=desc,
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.95,
                        description=f"{desc} in `{p}`",
                        snippet=txt[:250],
                    ))

    @classmethod
    def _discover_integrations(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp):
        """Discovers external integrations and third-party services."""
        integration_patterns = [
            (r'\b(?:stripe\.|StripeClient|PaymentGateway)\b', "Stripe / Payment Gateway Integration"),
            (r'\b(?:boto3|aws_sdk|S3Client|AwsClient)\b', "AWS / Cloud Storage Integration"),
            (r'\b(?:sendgrid|mailer|smtp|send_email|send_mail)\b', "Email / Notification Service"),
            (r'\b(?:twilio|sms_client|send_sms)\b', "Twilio / SMS Gateway"),
            (r'\b(?:openai|anthropic|langchain|ollama)\b', "AI / LLM API Integration"),
            (r'\b(?:redis|Redis\(|aioredis)\b', "Redis Cache / Key-Value Store"),
            (r'\b(?:httpx\.AsyncClient|requests\.Session|axios\.create|http\.Client)\b', "External HTTP Client"),
        ]

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/", "generate_docx", "generate_pdf"]):
                continue

            txt = c.chunk_text
            for pat, desc in integration_patterns:
                if re.search(pat, txt):
                    add_comp(DiscoveredComponent(
                        component_type="integration",
                        name=desc,
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.90,
                        description=f"{desc} in `{p}`",
                        snippet=txt[:250],
                    ))

    @classmethod
    def _discover_background_jobs(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp, project_type: str = "monolith", repo_name: str = ""):
        if project_type in ("framework", "library"):
            bg_file = next((p for p in file_paths if "background.py" in p), None)
            if bg_file:
                add_comp(DiscoveredComponent(
                    component_type="background_job",
                    name="Framework BackgroundTasks Engine",
                    file_path=bg_file,
                    start_line=1,
                    end_line=50,
                    confidence=0.99,
                    description=f"Framework background task abstraction (`{bg_file}`), defining `BackgroundTasks` inheriting from Starlette to run asynchronous tasks after returning HTTP responses.",
                    snippet="",
                    metadata={"sub_type": "framework_background_tasks"}
                ))
        """Discovers background processing, schedulers, and queue workers."""
        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/", "generate_docx", "generate_pdf"]):
                continue

            ext = Path(p).suffix.lower()
            txt = c.chunk_text

            # Celery (Python only)
            if ext == ".py" and re.search(r'\b(?:@celery\.task|@app\.task|Celery\()\b', txt):
                add_comp(DiscoveredComponent(
                    component_type="background_job",
                    name="Celery Distributed Task Queue",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.95,
                    description=f"Celery task definition in `{p}`",
                    snippet=txt[:250],
                ))
            # BullMQ / Node Job Worker (JS/TS only)
            elif ext in [".js", ".ts", ".mjs", ".cjs"] and re.search(r'\b(?:BullMQ|new\s+Queue\s*\(|new\s+Worker\s*\()\b', txt):
                add_comp(DiscoveredComponent(
                    component_type="background_job",
                    name="BullMQ / Node Job Worker",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.90,
                    description=f"BullMQ / Node worker in `{p}`",
                    snippet=txt[:250],
                ))
            # Go Goroutines (Go only)
            elif ext == ".go" and re.search(r'\bgo\s+func\s*\(', txt):
                add_comp(DiscoveredComponent(
                    component_type="background_job",
                    name="Go Concurrency Routine",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.90,
                    description=f"Go concurrency routine in `{p}`",
                    snippet=txt[:250],
                ))
            # Kafka / AMQP Message Queue
            elif re.search(r'\b(?:KafkaConsumer|KafkaProducer|confluent_kafka)\b', txt):
                add_comp(DiscoveredComponent(
                    component_type="background_job",
                    name="Apache Kafka Event Stream",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.90,
                    description=f"Kafka event stream worker in `{p}`",
                    snippet=txt[:250],
                ))
            elif re.search(r'\b(?:pika\.BlockingConnection|pika\.SelectConnection)\b', txt):
                add_comp(DiscoveredComponent(
                    component_type="background_job",
                    name="RabbitMQ / AMQP Message Queue",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.90,
                    description=f"RabbitMQ consumer in `{p}`",
                    snippet=txt[:250],
                ))
            # Scheduled Cron Job
            elif re.search(r'\b(?:cron\.schedule|APScheduler|schedule\.every)\b', txt):
                add_comp(DiscoveredComponent(
                    component_type="background_job",
                    name="Scheduled Cron Job",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.90,
                    description=f"Scheduled cron job in `{p}`",
                    snippet=txt[:250],
                ))

    @classmethod
    def _discover_configuration(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp, project_type: str = "monolith", repo_name: str = ""):
        """Discovers configuration, environment variables, and deployment manifests."""
        if project_type in ("framework", "library"):
            app_file = next((p for p in file_paths if "applications.py" in p or "app.py" in p), file_paths[0] if file_paths else "pyproject.toml")
            add_comp(DiscoveredComponent(
                component_type="config",
                name="Framework Application Constructor Parameters",
                file_path=app_file,
                start_line=1,
                end_line=50,
                confidence=0.99,
                description=f"{repo_name} framework configuration is passed directly via `FastAPI(...)` class constructor parameters in `{app_file}`. The framework does not bundle environment-specific deployment configurations (.env, dev/staging/prod environments).",
                snippet="",
                metadata={"sub_type": "framework_constructor_config"}
            ))
        config_filenames = {
            "config.py", "settings.py", "core/config.py", "config/settings.py",
            "package.json", "requirements.txt", "pyproject.toml", "go.mod", "cargo.toml",
            "pom.xml", "build.gradle", "pubspec.yaml", "dockerfile", "docker-compose.yml",
            "docker-compose.yaml", ".env.example"
        }

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_name = Path(p).name.lower()
            if p_name in config_filenames or any(p.lower().endswith(cf) for cf in config_filenames):
                add_comp(DiscoveredComponent(
                    component_type="config",
                    name=f"Config: {Path(p).name}",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.95,
                    description=f"Configuration/manifest file `{p}`",
                    snippet=c.chunk_text[:200],
                ))

    @classmethod
    def _discover_frontend_components(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp):
        """Discovers frontend UI pages, views, and components."""
        fe_dirs = [
            "components/", "pages/", "views/", "screens/", "src/ui", "lib/screens", "lib/views",
            "lib/home", "lib/auth", "lib/components", "templates/", "static/"
        ]

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/", "generate_docx", "generate_pdf"]):
                continue

            ext = Path(p).suffix.lower()
            is_dart_ui = (
                ext == ".dart" and (
                    any(fd in p_lower for fd in ["screens/", "widgets/", "views/", "pages/", "home/", "auth/", "components/"]) or
                    p_lower.endswith(("_page.dart", "_screen.dart", "_view.dart", "_card.dart")) or
                    any(k in c.chunk_text for k in ["StatefulWidget", "StatelessWidget", "Scaffold", "Widget build"])
                )
            )
            is_fe_file = ext in [".tsx", ".jsx", ".vue", ".svelte", ".html"] or is_dart_ui

            if is_fe_file or any(fd in p_lower for fd in fe_dirs):
                name = c.code_symbol or Path(p).stem
                if name and (name[0].isupper() or any(k in c.chunk_text for k in ["Widget", "Component", "render", "return <", "Widget build", "StatefulWidget", "StatelessWidget"])):
                    add_comp(DiscoveredComponent(
                        component_type="frontend_ui",
                        name=f"UI: {name}",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.90,
                        description=f"Frontend UI component `{name}` in `{p}`",
                        snippet=c.chunk_text[:250],
                    ))

    @classmethod
    def _discover_mobile_native_components(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp):
        """Discovers Android and native mobile integration components (manifests, host activities, background services)."""
        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/"]):
                continue

            p_name = Path(p).name

            # Android Manifest
            if p_name.lower() == "androidmanifest.xml" and "main" in p_lower:
                add_comp(DiscoveredComponent(
                    component_type="native_android",
                    name="Android Application Manifest & Permissions",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.98,
                    description=f"Android core manifest in `{p}`",
                    snippet=c.chunk_text[:250],
                ))
            # Android Host Activity
            elif p_name in ["MainActivity.kt", "MainActivity.java"]:
                add_comp(DiscoveredComponent(
                    component_type="native_android",
                    name="Android Native Host (Activity / MethodChannels)",
                    file_path=p,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    confidence=0.98,
                    description=f"Android native bridge host in `{p}`",
                    snippet=c.chunk_text[:250],
                ))
            # Android Native Services, Workers, Receivers
            elif "android/" in p_lower and Path(p).suffix in [".kt", ".java"]:
                txt = c.chunk_text
                if any(k in txt for k in ["Service()", "Worker(", "BroadcastReceiver()", "ForegroundService", "Notification", "WorkManager", "CameraManager"]):
                    comp_name = c.code_symbol or Path(p).stem
                    add_comp(DiscoveredComponent(
                        component_type="native_android",
                        name=f"Android Native: {comp_name}",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.95,
                        description=f"Android native service/receiver `{comp_name}` in `{p}`",
                        snippet=c.chunk_text[:250],
                    ))

    @classmethod
    def _discover_tests(cls, file_paths: List[str], add_comp):
        """Discovers automated tests and test fixtures."""
        for p in file_paths:
            p_clean = p.replace("\\", "/")
            p_lower = p_clean.lower()
            if any(td in p_lower for td in ["tests/", "test/", "__tests__/", "spec/"]) or p_lower.endswith(("_test.py", ".test.ts", ".spec.ts", ".test.js", "_test.go", "test.java")):
                add_comp(DiscoveredComponent(
                    component_type="test",
                    name=f"Test: {Path(p_clean).name}",
                    file_path=p_clean,
                    start_line=1,
                    end_line=50,
                    confidence=0.95,
                    description=f"Test suite file `{p_clean}`",
                ))

    @classmethod
    def _trace_execution_flows(
        cls,
        components_by_type: Dict[str, List[DiscoveredComponent]],
        chunks: List[CodeChunk],
        db: Session,
        repository_id: int,
    ) -> List[DiscoveredFlow]:
        """Identifies how application entry points connect to routes, services, storage, and integrations."""
        flows: List[DiscoveredFlow] = []

        entry_points = components_by_type.get("entry_point", [])
        routes = components_by_type.get("api_route", [])
        services = components_by_type.get("service", [])
        persistence = components_by_type.get("persistence", [])
        integrations = components_by_type.get("integration", [])

        # 1. Entry point -> Routes registration
        if entry_points and routes:
            for ep in entry_points[:3]:
                ep_norm = ep.file_path.replace("\\", "/")
                ep_chunks = [c for c in chunks if c.file_path.replace("\\", "/") == ep_norm]
                ep_text = " ".join([c.chunk_text.lower() for c in ep_chunks]) if ep_chunks else ep.snippet.lower()
                for r in routes[:8]:
                    r_stem = Path(r.file_path).stem.lower()
                    if r_stem in ep_text or any(k in ep_text for k in ["include_router", "add_routes", "router", "routes"]):
                        flows.append(DiscoveredFlow(
                            source_component=f"`{ep.file_path}`",
                            target_component=f"`{r.file_path}`",
                            flow_type="routes_to",
                            evidence=f"Entry point `{ep.file_path}` configures route handler `{r.file_path}`",
                        ))
                        break

        # 2. Routes -> Services
        if routes and services:
            for r in routes[:8]:
                r_norm = r.file_path.replace("\\", "/")
                r_chunks = [c for c in chunks if c.file_path.replace("\\", "/") == r_norm]
                r_text = " ".join([c.chunk_text.lower() for c in r_chunks]) if r_chunks else r.snippet.lower()
                for s in services[:8]:
                    s_name = s.name.lower()
                    s_stem = Path(s.file_path).stem.lower()
                    if s_name in r_text or s_stem in r_text or any(k in r_text for k in [f"{s_stem}.", f"{s_stem}("]):
                        flows.append(DiscoveredFlow(
                            source_component=f"`{r.file_path}`",
                            target_component=f"`{s.file_path}`",
                            flow_type="calls",
                            evidence=f"Route `{r.file_path}` delegates business logic to service `{s.file_path}`",
                        ))
                        break

        # 3. Services / Handlers -> Persistence
        if persistence and (services or routes):
            callers = services[:6] if services else routes[:6]
            for c in callers:
                c_norm = c.file_path.replace("\\", "/")
                c_chunks = [ch for ch in chunks if ch.file_path.replace("\\", "/") == c_norm]
                c_text = " ".join([ch.chunk_text.lower() for ch in c_chunks]) if c_chunks else c.snippet.lower()
                for p in persistence[:8]:
                    p_name = p.name.replace("Model: ", "").replace("Repository: ", "").lower()
                    p_stem = Path(p.file_path).stem.lower()
                    if p_name in c_text or p_stem in c_text:
                        flows.append(DiscoveredFlow(
                            source_component=f"`{c.file_path}`",
                            target_component=f"`{p.file_path}`",
                            flow_type="queries",
                            evidence=f"Component `{c.file_path}` performs database operations on persistence model `{p.file_path}`",
                        ))
                        break

        # 4. Services / Handlers -> External Integrations
        if integrations and (services or routes):
            callers = services[:6] if services else routes[:6]
            for c in callers:
                c_norm = c.file_path.replace("\\", "/")
                c_chunks = [ch for ch in chunks if ch.file_path.replace("\\", "/") == c_norm]
                c_text = " ".join([ch.chunk_text.lower() for ch in c_chunks]) if c_chunks else c.snippet.lower()
                for ig in integrations[:6]:
                    ig_name = ig.name.lower()
                    ig_stem = Path(ig.file_path).stem.lower()
                    if ig_name in c_text or ig_stem in c_text:
                        flows.append(DiscoveredFlow(
                            source_component=f"`{c.file_path}`",
                            target_component=f"`{ig.file_path}`",
                            flow_type="integrates_with",
                            evidence=f"Component `{c.file_path}` invokes third-party integration in `{ig.file_path}`",
                        ))
                        break

        return flows
