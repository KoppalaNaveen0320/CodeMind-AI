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
        project_type = cls._detect_project_type(file_paths, languages, frameworks)

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
        cls._discover_entry_points(chunks, file_paths, add_comp)

        # B. Routes, APIs & Controllers
        cls._discover_api_routes(chunks, symbols, file_paths, add_comp)

        # C. Services & Business Logic
        cls._discover_services(chunks, symbols, file_paths, add_comp)

        # D. Database Models & Persistence
        cls._discover_persistence(chunks, symbols, file_paths, add_comp)

        # E. Authentication & Authorization
        cls._discover_auth(chunks, file_paths, add_comp)

        # F. External Integrations
        cls._discover_integrations(chunks, file_paths, add_comp)

        # G. Background Jobs & Workers
        cls._discover_background_jobs(chunks, file_paths, add_comp)

        # H. Configuration & Deployment Infrastructure
        cls._discover_configuration(chunks, file_paths, add_comp)

        # I. Frontend UI Components
        cls._discover_frontend_components(chunks, file_paths, add_comp)

        # J. Tests
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
    def _detect_project_type(cls, file_paths: List[str], languages: List[str], frameworks: List[str]) -> str:
        p_lower = [fp.lower().replace("\\", "/") for fp in file_paths]
        has_apps = any(p.startswith("apps/") or "/apps/" in p for p in p_lower)
        has_packages = any(p.startswith("packages/") or "/packages/" in p for p in p_lower)
        services_count = sum(1 for p in p_lower if p.startswith("services/") or "/services/" in p)

        if (has_apps and has_packages) or services_count > 1:
            return "monorepo"

        if "Flutter" in frameworks or "React Native" in frameworks or any(p.startswith("lib/main.dart") or "android/" in p or "ios/" in p for p in p_lower):
            return "mobile"

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
    def _discover_entry_points(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp):
        """Discovers application bootstrap and entry points across technologies."""
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
    def _discover_api_routes(cls, chunks: List[CodeChunk], symbols: List[CodeSymbol], file_paths: List[str], add_comp):
        """Discovers routes, API endpoints, and controllers across technologies."""
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
    def _discover_services(cls, chunks: List[CodeChunk], symbols: List[CodeSymbol], file_paths: List[str], add_comp):
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
    def _discover_persistence(cls, chunks: List[CodeChunk], symbols: List[CodeSymbol], file_paths: List[str], add_comp):
        """Discovers database models, schemas, repositories, and persistence logic."""
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

            # Repository / DAO classes
            repo_match = re.search(r'\bclass\s+([A-Za-z0-9_]*(?:Repository|DAO|Repo))\b', txt)
            if repo_match:
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
    def _discover_auth(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp):
        """Discovers authentication, authorization, and security mechanisms."""
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
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/"]):
                continue

            txt = c.chunk_text
            for pat, desc in auth_patterns:
                if re.search(pat, txt):
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
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/"]):
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
    def _discover_background_jobs(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp):
        """Discovers background processing, schedulers, and queue workers."""
        job_patterns = [
            (r'\b(?:@celery\.task|@app\.task|celery|Celery\()\b', "Celery Distributed Task Queue"),
            (r'\b(?:BullMQ|Queue\s*\(|Worker\s*\()\b', "BullMQ / Node Job Worker"),
            (r'\b(?:Sidekiq|Resque)\b', "Ruby Sidekiq Background Job"),
            (r'\b(?:kafka|KafkaConsumer|KafkaProducer|confluent_kafka)\b', "Apache Kafka Event Stream"),
            (r'\b(?:rabbitmq|pika\.|amqp)\b', "RabbitMQ / AMQP Message Queue"),
            (r'\b(?:cron|cron\.schedule|APScheduler|schedule\.every)\b', "Scheduled Cron Job"),
            (r'\b(?:go\s+func\s*\(|goroutine|channel)\b', "Go Concurrency Routine"),
        ]

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/"]):
                continue

            txt = c.chunk_text
            for pat, desc in job_patterns:
                if re.search(pat, txt):
                    add_comp(DiscoveredComponent(
                        component_type="background_job",
                        name=desc,
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.90,
                        description=f"{desc} in `{p}`",
                        snippet=txt[:250],
                    ))

    @classmethod
    def _discover_configuration(cls, chunks: List[CodeChunk], file_paths: List[str], add_comp):
        """Discovers configuration, environment variables, and deployment manifests."""
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
        fe_dirs = ["components/", "pages/", "views/", "screens/", "src/ui", "lib/screens", "lib/views"]

        for c in chunks:
            p = c.file_path.replace("\\", "/")
            p_lower = p.lower()
            if any(ex in p_lower for ex in ["tests/", "test/", "uploads/", "fixtures/"]):
                continue

            ext = Path(p).suffix.lower()
            is_fe_file = ext in [".tsx", ".jsx", ".vue", ".svelte"] or (ext == ".dart" and any(fd in p_lower for fd in ["screens/", "widgets/", "views/"]))

            if is_fe_file or any(fd in p_lower for fd in fe_dirs):
                name = c.code_symbol or Path(p).stem
                # Filter out pure utility functions
                if name[0].isupper() or any(k in c.chunk_text for k in ["Widget", "Component", "render", "return <", "Widget build"]):
                    add_comp(DiscoveredComponent(
                        component_type="frontend_ui",
                        name=f"UI: {name}",
                        file_path=p,
                        start_line=c.start_line,
                        end_line=c.end_line,
                        confidence=0.90,
                        description=f"Frontend UI component `{name}` in `{p}`",
                        snippet=c.chunk_text[:200],
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
