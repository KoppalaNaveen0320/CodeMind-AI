import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

try:
    import tomllib
except ImportError:
    tomllib = None

try:
    import yaml
except ImportError:
    yaml = None

from sqlalchemy.orm import Session
from backend.app.schemas.repository import TechItemRead, TechStackRead, TechStackSummaryRead

logger = logging.getLogger(__name__)

# Directory exclusion set for local disk walks
IGNORED_DIRS: Set[str] = {
    ".git", ".github", ".svn", ".hg", "node_modules", "vendor", "venv", ".venv",
    "env", ".env", "dist", "build", "target", "bin", "obj", "__pycache__",
    ".pytest_cache", ".tox", ".idea", ".vscode", "coverage", "htmlcov"
}

# Mapping of file extensions to canonical languages
EXTENSION_LANGUAGE_MAP: Dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".dart": "Dart",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".swift": "Swift",
    ".php": "PHP",
    ".rb": "Ruby",
    ".cs": "C#",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".less": "Less",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".sql": "SQL",
}

# Classification of languages into frontend vs backend defaults
FRONTEND_LANGUAGES: Set[str] = {
    "JavaScript", "TypeScript", "HTML", "CSS", "SCSS", "Sass", "Less", "Vue", "Svelte", "Dart"
}

BACKEND_LANGUAGES: Set[str] = {
    "Python", "Java", "Go", "Rust", "PHP", "Ruby", "C#", "C", "C++", "Kotlin"
}


class TechStackDetectionService:
    """
    Service for evidence-grounded technology stack detection.
    Analyzes repository package manifests, configuration files, source code imports,
    and file statistics to reliably identify frontend, backend, database, and
    infrastructure technologies without guesswork.
    """

    @classmethod
    def detect_from_files(
        cls,
        manifest_contents: Optional[Union[Dict[str, str], List[str]]] = None,
        all_file_paths: Optional[List[str]] = None,
        chunk_snippets: Optional[List[Tuple[str, str]]] = None,
    ) -> TechStackRead:
        """
        Pure detection logic operating on in-memory manifest contents and file path inventory.
        """
        # Handle case where user passes a list of paths as first argument
        if isinstance(manifest_contents, list):
            all_file_paths = manifest_contents
            manifest_contents = {}
        else:
            manifest_contents = manifest_contents or {}
        all_file_paths = all_file_paths or []
        chunk_snippets = chunk_snippets or []

        frontend_items: List[TechItemRead] = []
        backend_items: List[TechItemRead] = []
        database_items: List[TechItemRead] = []
        infra_items: List[TechItemRead] = []
        detected_languages: Set[str] = set()

        seen_frontend: Set[str] = set()
        seen_backend: Set[str] = set()
        seen_database: Set[str] = set()
        seen_infra: Set[str] = set()

        def add_item(
            target_list: List[TechItemRead],
            seen_set: Set[str],
            name: str,
            category: str,
            confidence: Union[float, str],
            evidence_file: Optional[str] = None,
            version: Optional[str] = None,
            details: Optional[str] = None,
            evidence: Optional[List[str]] = None,
            type: Optional[str] = None,
        ):
            key = (name.lower(), category)
            if key not in seen_set:
                seen_set.add(key)
                ev_list = evidence if evidence is not None else ([f"Found in {evidence_file}"] if evidence_file else [])
                target_list.append(
                    TechItemRead(
                        name=name,
                        category=category,
                        type=type or category,
                        confidence=confidence,
                        evidence=ev_list,
                        evidence_file=evidence_file,
                        version=version,
                        details=details,
                    )
                )

        # 1. Analyze manifest files
        for rel_path, content in manifest_contents.items():
            norm_path = rel_path.replace("\\", "/").lower()
            fname = Path(norm_path).name

            # A. package.json
            if fname == "package.json":
                cls._parse_package_json(
                    content, rel_path,
                    add_item, frontend_items, seen_frontend,
                    backend_items, seen_backend,
                    database_items, seen_database,
                    infra_items, seen_infra,
                    detected_languages
                )

            # B. Python manifests
            elif fname in ("requirements.txt", "requirements-dev.txt", "pipfile") or fname.endswith(".txt") and "requirements" in norm_path:
                cls._parse_python_requirements(
                    content, rel_path,
                    add_item, backend_items, seen_backend,
                    frontend_items, seen_frontend,
                    database_items, seen_database,
                    detected_languages
                )
            elif fname == "pyproject.toml":
                cls._parse_pyproject_toml(
                    content, rel_path,
                    add_item, backend_items, seen_backend,
                    frontend_items, seen_frontend,
                    database_items, seen_database,
                    detected_languages
                )

            # C. pubspec.yaml (Flutter / Dart)
            elif fname == "pubspec.yaml":
                cls._parse_pubspec_yaml(
                    content, rel_path,
                    add_item, frontend_items, seen_frontend,
                    backend_items, seen_backend,
                    database_items, seen_database,
                    infra_items, seen_infra,
                    detected_languages
                )

            # D. Docker & Docker Compose
            elif fname.startswith("dockerfile") or fname.endswith(".dockerfile"):
                cls._parse_dockerfile(
                    content, rel_path,
                    add_item, infra_items, seen_infra,
                    backend_items, seen_backend,
                    database_items, seen_database
                )
            elif "docker-compose" in fname or fname in ("compose.yml", "compose.yaml"):
                cls._parse_docker_compose(
                    content, rel_path,
                    add_item, infra_items, seen_infra,
                    database_items, seen_database
                )

            # E. Go (go.mod)
            elif fname == "go.mod":
                cls._parse_go_mod(
                    content, rel_path,
                    add_item, backend_items, seen_backend,
                    database_items, seen_database,
                    detected_languages
                )

            # F. Rust (Cargo.toml)
            elif fname == "cargo.toml":
                cls._parse_cargo_toml(
                    content, rel_path,
                    add_item, backend_items, seen_backend,
                    database_items, seen_database,
                    detected_languages
                )

            # G. Java / Kotlin (pom.xml, build.gradle, build.gradle.kts)
            elif fname in ("pom.xml", "build.gradle", "build.gradle.kts"):
                cls._parse_jvm_manifest(
                    content, rel_path,
                    add_item, backend_items, seen_backend,
                    database_items, seen_database,
                    detected_languages
                )

            # H. PHP (composer.json)
            elif fname == "composer.json":
                cls._parse_composer_json(
                    content, rel_path,
                    add_item, backend_items, seen_backend,
                    database_items, seen_database,
                    detected_languages
                )

            # I. Ruby (Gemfile)
            elif fname == "gemfile":
                cls._parse_gemfile(
                    content, rel_path,
                    add_item, backend_items, seen_backend,
                    database_items, seen_database,
                    detected_languages
                )

            # J. Nginx configuration
            elif fname == "nginx.conf" or fname.endswith(".nginx") or fname.endswith(".conf") and "nginx" in norm_path:
                add_item(infra_items, seen_infra, "Nginx", "infrastructure", 0.95, rel_path, None, "Nginx server configuration")

        # 2. Analyze code snippets/chunks for import evidence if available
        if chunk_snippets:
            cls._inspect_code_imports(
                chunk_snippets,
                add_item, frontend_items, seen_frontend,
                backend_items, seen_backend,
                database_items, seen_database
            )

        # 3. Analyze file extension counts to supplement language detection
        ext_counts: Dict[str, int] = {}
        for p in all_file_paths:
            ext = Path(p).suffix.lower()
            if ext in EXTENSION_LANGUAGE_MAP:
                lang = EXTENSION_LANGUAGE_MAP[ext]
                ext_counts[lang] = ext_counts.get(lang, 0) + 1
                detected_languages.add(lang)

        # 4. Integrate detected languages into Frontend and Backend categories
        # A. Frontend languages:
        for lang in ("React", "Vue", "Svelte", "Angular"):
            # If framework is detected, ensure JavaScript/TypeScript is acknowledged if files exist
            if any(item.name.lower() == lang.lower() for item in frontend_items):
                if ext_counts.get("TypeScript", 0) > 0 and ("typescript", "language") not in seen_frontend:
                    add_item(frontend_items, seen_frontend, "TypeScript", "language", 0.95, None)
                elif ext_counts.get("JavaScript", 0) > 0 and ("javascript", "language") not in seen_frontend:
                    add_item(frontend_items, seen_frontend, "JavaScript", "language", 0.90, None)

        if ext_counts.get("TypeScript", 0) > 0 and ("typescript", "language") not in seen_frontend:
            # If TS files exist, check if frontend or backend
            add_item(frontend_items, seen_frontend, "TypeScript", "language", 0.85, None)

        if ext_counts.get("JavaScript", 0) > 0 and ("javascript", "language") not in seen_frontend:
            # Check if this repository is not purely backend
            add_item(frontend_items, seen_frontend, "JavaScript", "language", 0.85, None)

        if ext_counts.get("HTML", 0) > 0 and ("html", "language") not in seen_frontend:
            add_item(frontend_items, seen_frontend, "HTML", "language", 0.85, None)

        if ext_counts.get("CSS", 0) > 0 or ext_counts.get("SCSS", 0) > 0:
            if ("css", "language") not in seen_frontend:
                add_item(frontend_items, seen_frontend, "CSS", "language", 0.80, None)

        if ext_counts.get("Dart", 0) > 0 and ("dart", "language") not in seen_frontend:
            add_item(frontend_items, seen_frontend, "Dart", "language", 0.90, None)

        total_source_files = sum(ext_counts.values()) or 1
        is_flutter = any(item.name.lower() == "flutter" for item in frontend_items)
        is_client_only = any(item.name.lower() in ("react", "vue", "svelte", "angular", "flutter") for item in frontend_items)

        # B. Backend languages:
        has_python_backend_evidence = any(
            b.name.lower() in ("fastapi", "flask", "django", "tornado", "starlette", "sanic", "falcon", "celery")
            for b in backend_items
        ) or any("requirements" in m.lower() or "pyproject" in m.lower() or "pipfile" in m.lower() for m in manifest_contents.keys())

        if ext_counts.get("Python", 0) > 0 and ("python", "language") not in seen_backend:
            py_ratio = ext_counts.get("Python", 0) / total_source_files
            if has_python_backend_evidence or (py_ratio > 0.20 and not is_flutter):
                add_item(backend_items, seen_backend, "Python", "language", 0.90, None)

        if ext_counts.get("Go", 0) > 0 and ("go", "language") not in seen_backend:
            add_item(backend_items, seen_backend, "Go", "language", 0.90, None)

        if ext_counts.get("Rust", 0) > 0 and ("rust", "language") not in seen_backend:
            add_item(backend_items, seen_backend, "Rust", "language", 0.90, None)

        if ext_counts.get("Java", 0) > 0 and ("java", "language") not in seen_backend:
            non_android_java = sum(1 for p in all_file_paths if p.endswith(".java") and not p.replace("\\", "/").lower().startswith("android/"))
            if non_android_java > 0:
                add_item(backend_items, seen_backend, "Java", "language", 0.90, None)

        if ext_counts.get("PHP", 0) > 0 and ("php", "language") not in seen_backend:
            add_item(backend_items, seen_backend, "PHP", "language", 0.90, None)

        if ext_counts.get("Ruby", 0) > 0 and ("ruby", "language") not in seen_backend:
            add_item(backend_items, seen_backend, "Ruby", "language", 0.90, None)

        if ext_counts.get("C#", 0) > 0 and ("c#", "language") not in seen_backend:
            add_item(backend_items, seen_backend, "C#", "language", 0.90, None)

        # If Node.js backend frameworks are present (e.g. Express, NestJS), ensure TypeScript/JavaScript is also in backend
        has_node_backend = any(b.name.lower() in ("express", "nestjs", "koa", "fastify", "hapi", "socket.io") for b in backend_items)
        if has_node_backend:
            if ext_counts.get("TypeScript", 0) > 0 and ("typescript", "language") not in seen_backend:
                add_item(backend_items, seen_backend, "TypeScript", "language", 0.90, None)
            elif ext_counts.get("JavaScript", 0) > 0 and ("javascript", "language") not in seen_backend:
                add_item(backend_items, seen_backend, "JavaScript", "language", 0.90, None)
            if ("node.js", "runtime") not in seen_backend:
                add_item(backend_items, seen_backend, "Node.js", "runtime", 0.95, None)

        # 5. Build summary texts
        frontend_names = [it.name for it in frontend_items]
        backend_names = [it.name for it in backend_items]
        db_names = [it.name for it in database_items]
        infra_names = [it.name for it in infra_items]

        frontend_text = ", ".join(frontend_names) if frontend_names else "Not detected"
        backend_text = ", ".join(backend_names) if backend_names else "Not detected"
        db_text = ", ".join(db_names) if db_names else None
        infra_text = ", ".join(infra_names) if infra_names else None

        full_parts = [
            f"Frontend: {frontend_text}",
            f"Backend: {backend_text}"
        ]
        if db_text:
            full_parts.append(f"Database: {db_text}")
        if infra_text:
            full_parts.append(f"Infra: {infra_text}")
        full_summary = "; ".join(full_parts)

        summary = TechStackSummaryRead(
            frontend_text=frontend_text,
            backend_text=backend_text,
            database_text=db_text,
            infrastructure_text=infra_text,
            frontend_summary=frontend_text,
            backend_summary=backend_text,
            database_summary=db_text or "Not detected",
            infrastructure_summary=infra_text or "Not detected",
            full_summary=full_summary,
        )

        return TechStackRead(
            frontend=frontend_items,
            backend=backend_items,
            database=database_items,
            infrastructure=infra_items,
            languages=sorted(list(detected_languages)),
            summary=summary,
            detected_at=datetime.now(timezone.utc),
        )

    # --- Parsers ---

    @classmethod
    def _parse_package_json(
        cls,
        content: str,
        rel_path: str,
        add_item,
        frontend_items, seen_frontend,
        backend_items, seen_backend,
        database_items, seen_database,
        infra_items, seen_infra,
        detected_languages: Set[str],
    ):
        try:
            pkg = json.loads(content)
        except Exception:
            return

        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

        # Frontend frameworks
        fw_map = {
            "react": "React",
            "react-dom": "React",
            "vue": "Vue.js",
            "@angular/core": "Angular",
            "svelte": "Svelte",
            "next": "Next.js",
            "nuxt": "Nuxt",
            "@remix-run/react": "Remix",
            "gatsby": "Gatsby",
            "react-native": "React Native",
            "preact": "Preact",
            "solid-js": "Solid.js",
            "astro": "Astro",
        }
        for pkg_name, label in fw_map.items():
            if pkg_name in deps:
                add_item(frontend_items, seen_frontend, label, "framework", 1.0, rel_path, deps.get(pkg_name))

        # Frontend tools & build systems
        tool_map = {
            "vite": "Vite",
            "webpack": "Webpack",
            "tailwindcss": "Tailwind CSS",
            "sass": "Sass",
            "less": "Less",
            "postcss": "PostCSS",
        }
        for pkg_name, label in tool_map.items():
            if pkg_name in deps:
                add_item(frontend_items, seen_frontend, label, "tool", 1.0, rel_path, deps.get(pkg_name))

        # TypeScript
        if "typescript" in deps:
            add_item(frontend_items, seen_frontend, "TypeScript", "language", 1.0, rel_path, deps.get("typescript"))
            detected_languages.add("TypeScript")

        # Backend frameworks (Node.js)
        backend_fw_map = {
            "express": "Express",
            "@nestjs/core": "NestJS",
            "koa": "Koa",
            "fastify": "Fastify",
            "hapi": "Hapi",
            "@hapi/hapi": "Hapi",
            "socket.io": "Socket.IO",
            "adonisjs": "AdonisJS",
            "@adonisjs/core": "AdonisJS",
        }
        for pkg_name, label in backend_fw_map.items():
            if pkg_name in deps:
                add_item(backend_items, seen_backend, label, "framework", 1.0, rel_path, deps.get(pkg_name))
                add_item(backend_items, seen_backend, "Node.js", "runtime", 0.95, rel_path)

        # Database & ORM
        db_map = {
            "pg": ("PostgreSQL", "database"),
            "mysql": ("MySQL", "database"),
            "mysql2": ("MySQL", "database"),
            "mongodb": ("MongoDB", "database"),
            "mongoose": ("MongoDB", "database"),
            "redis": ("Redis", "database"),
            "ioredis": ("Redis", "database"),
            "sqlite3": ("SQLite", "database"),
            "better-sqlite3": ("SQLite", "database"),
            "prisma": ("Prisma", "orm"),
            "@prisma/client": ("Prisma", "orm"),
            "typeorm": ("TypeORM", "orm"),
            "sequelize": ("Sequelize", "orm"),
        }
        for pkg_name, (label, cat) in db_map.items():
            if pkg_name in deps:
                add_item(database_items, seen_database, label, cat, 1.0, rel_path, deps.get(pkg_name))

    @classmethod
    def _parse_python_requirements(
        cls,
        content: str,
        rel_path: str,
        add_item,
        backend_items, seen_backend,
        frontend_items, seen_frontend,
        database_items, seen_database,
        detected_languages: Set[str],
    ):
        add_item(backend_items, seen_backend, "Python", "language", 1.0, rel_path)
        detected_languages.add("Python")

        lines = content.splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue

            # Strip version specifiers: fastapi>=0.111.0, uvicorn[standard]>=0.30.0
            match = re.match(r"^([a-zA-Z0-9_\-\.]+)(?:\[.*?\])?\s*([<>=!~].*)?$", line)
            if not match:
                continue

            pkg_name = match.group(1).lower().replace("_", "-")
            version = match.group(2).strip() if match.group(2) else None

            # Backend frameworks
            if pkg_name == "fastapi":
                add_item(backend_items, seen_backend, "FastAPI", "framework", 1.0, rel_path, version)
            elif pkg_name == "flask":
                add_item(backend_items, seen_backend, "Flask", "framework", 1.0, rel_path, version)
            elif pkg_name == "django":
                add_item(backend_items, seen_backend, "Django", "framework", 1.0, rel_path, version)
            elif pkg_name == "starlette":
                add_item(backend_items, seen_backend, "Starlette", "framework", 1.0, rel_path, version)
            elif pkg_name == "tornado":
                add_item(backend_items, seen_backend, "Tornado", "framework", 1.0, rel_path, version)
            elif pkg_name == "sanic":
                add_item(backend_items, seen_backend, "Sanic", "framework", 1.0, rel_path, version)
            elif pkg_name == "falcon":
                add_item(backend_items, seen_backend, "Falcon", "framework", 1.0, rel_path, version)
            elif pkg_name == "celery":
                add_item(backend_items, seen_backend, "Celery", "tool", 1.0, rel_path, version)

            # Python frontend frameworks
            elif pkg_name == "streamlit":
                add_item(frontend_items, seen_frontend, "Streamlit", "framework", 1.0, rel_path, version)
            elif pkg_name == "dash":
                add_item(frontend_items, seen_frontend, "Dash", "framework", 1.0, rel_path, version)
            elif pkg_name == "gradio":
                add_item(frontend_items, seen_frontend, "Gradio", "framework", 1.0, rel_path, version)

            # Database & ORM
            elif pkg_name == "sqlalchemy":
                add_item(database_items, seen_database, "SQLAlchemy", "orm", 1.0, rel_path, version)
            elif pkg_name in ("psycopg2", "psycopg2-binary", "psycopg", "asyncpg"):
                add_item(database_items, seen_database, "PostgreSQL", "database", 1.0, rel_path, version)
            elif pkg_name in ("pymongo", "motor"):
                add_item(database_items, seen_database, "MongoDB", "database", 1.0, rel_path, version)
            elif pkg_name in ("redis", "aioredis"):
                add_item(database_items, seen_database, "Redis", "database", 1.0, rel_path, version)
            elif pkg_name in ("mysqlclient", "pymysql"):
                add_item(database_items, seen_database, "MySQL", "database", 1.0, rel_path, version)
            elif pkg_name == "alembic":
                add_item(database_items, seen_database, "Alembic", "orm", 1.0, rel_path, version)
            elif pkg_name == "tortoise-orm":
                add_item(database_items, seen_database, "Tortoise ORM", "orm", 1.0, rel_path, version)
            elif pkg_name == "peewee":
                add_item(database_items, seen_database, "Peewee", "orm", 1.0, rel_path, version)

    @classmethod
    def _parse_pyproject_toml(
        cls,
        content: str,
        rel_path: str,
        add_item,
        backend_items, seen_backend,
        frontend_items, seen_frontend,
        database_items, seen_database,
        detected_languages: Set[str],
    ):
        add_item(backend_items, seen_backend, "Python", "language", 1.0, rel_path)
        detected_languages.add("Python")

        deps_list: List[str] = []
        if tomllib:
            try:
                data = tomllib.loads(content)
                # Poetry
                poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                deps_list.extend(poetry_deps.keys())
                # PEP 621 project.dependencies
                proj_deps = data.get("project", {}).get("dependencies", [])
                deps_list.extend(proj_deps)
            except Exception:
                pass

        if not deps_list:
            # Simple regex fallback
            deps_list = re.findall(r'["\']([a-zA-Z0-9_\-\.]+)(?:[>=<~].*?)?["\']', content)

        # Feed extracted list as synthetic requirements
        synth_reqs = "\n".join(deps_list)
        cls._parse_python_requirements(
            synth_reqs, rel_path,
            add_item, backend_items, seen_backend,
            frontend_items, seen_frontend,
            database_items, seen_database,
            detected_languages
        )

    @classmethod
    def _parse_pubspec_yaml(
        cls,
        content: str,
        rel_path: str,
        add_item,
        frontend_items, seen_frontend,
        backend_items, seen_backend,
        database_items, seen_database,
        infra_items, seen_infra,
        detected_languages: Set[str],
    ):
        add_item(frontend_items, seen_frontend, "Dart", "language", 1.0, rel_path)
        detected_languages.add("Dart")

        if "flutter:" in content or "sdk: flutter" in content:
            add_item(frontend_items, seen_frontend, "Flutter", "framework", 1.0, rel_path)

        if "cloud_firestore" in content:
            add_item(database_items, seen_database, "Cloud Firestore", "database", 1.0, rel_path)
        if "firebase_auth" in content or "firebase_core" in content:
            add_item(infra_items, seen_infra, "Firebase", "infrastructure", 1.0, rel_path)
        if "sqflite" in content:
            add_item(database_items, seen_database, "SQLite", "database", 1.0, rel_path)
        if "hive" in content:
            add_item(database_items, seen_database, "Hive", "database", 1.0, rel_path)

    @classmethod
    def _parse_dockerfile(
        cls,
        content: str,
        rel_path: str,
        add_item,
        infra_items, seen_infra,
        backend_items, seen_backend,
        database_items, seen_database,
    ):
        add_item(infra_items, seen_infra, "Docker", "infrastructure", 1.0, rel_path)

        for line in content.splitlines():
            line_strip = line.strip()
            if line_strip.upper().startswith("FROM "):
                base_img = line_strip[5:].split()[0].lower()
                if "python" in base_img:
                    add_item(backend_items, seen_backend, "Python", "language", 0.95, rel_path)
                elif "node" in base_img:
                    add_item(backend_items, seen_backend, "Node.js", "runtime", 0.90, rel_path)
                elif "golang" in base_img or "go:" in base_img:
                    add_item(backend_items, seen_backend, "Go", "language", 0.95, rel_path)
                elif "rust" in base_img:
                    add_item(backend_items, seen_backend, "Rust", "language", 0.95, rel_path)
                elif "openjdk" in base_img or "maven" in base_img or "gradle" in base_img:
                    add_item(backend_items, seen_backend, "Java", "language", 0.95, rel_path)
                elif "postgres" in base_img:
                    add_item(database_items, seen_database, "PostgreSQL", "database", 1.0, rel_path)
                elif "redis" in base_img:
                    add_item(database_items, seen_database, "Redis", "database", 1.0, rel_path)
                elif "nginx" in base_img:
                    add_item(infra_items, seen_infra, "Nginx", "infrastructure", 1.0, rel_path)

    @classmethod
    def _parse_docker_compose(
        cls,
        content: str,
        rel_path: str,
        add_item,
        infra_items, seen_infra,
        database_items, seen_database,
    ):
        add_item(infra_items, seen_infra, "Docker", "infrastructure", 1.0, rel_path)
        add_item(infra_items, seen_infra, "Docker Compose", "infrastructure", 1.0, rel_path)

        # Inspect images defined in compose
        img_matches = re.findall(r"image:\s*([^\s\n]+)", content, re.IGNORECASE)
        for img in img_matches:
            img_low = img.lower()
            if "postgres" in img_low:
                add_item(database_items, seen_database, "PostgreSQL", "database", 1.0, rel_path, img)
            elif "mysql" in img_low or "mariadb" in img_low:
                add_item(database_items, seen_database, "MySQL", "database", 1.0, rel_path, img)
            elif "redis" in img_low:
                add_item(database_items, seen_database, "Redis", "database", 1.0, rel_path, img)
            elif "mongo" in img_low:
                add_item(database_items, seen_database, "MongoDB", "database", 1.0, rel_path, img)
            elif "elasticsearch" in img_low:
                add_item(database_items, seen_database, "Elasticsearch", "database", 1.0, rel_path, img)
            elif "nginx" in img_low:
                add_item(infra_items, seen_infra, "Nginx", "infrastructure", 1.0, rel_path, img)
            elif "rabbitmq" in img_low:
                add_item(infra_items, seen_infra, "RabbitMQ", "infrastructure", 1.0, rel_path, img)

    @classmethod
    def _parse_go_mod(
        cls,
        content: str,
        rel_path: str,
        add_item,
        backend_items, seen_backend,
        database_items, seen_database,
        detected_languages: Set[str],
    ):
        add_item(backend_items, seen_backend, "Go", "language", 1.0, rel_path)
        detected_languages.add("Go")

        if "github.com/gin-gonic/gin" in content:
            add_item(backend_items, seen_backend, "Gin", "framework", 1.0, rel_path)
        if "github.com/gofiber/fiber" in content:
            add_item(backend_items, seen_backend, "Fiber", "framework", 1.0, rel_path)
        if "github.com/labstack/echo" in content:
            add_item(backend_items, seen_backend, "Echo", "framework", 1.0, rel_path)
        if "github.com/gorilla/mux" in content:
            add_item(backend_items, seen_backend, "Gorilla Mux", "framework", 1.0, rel_path)
        if "google.golang.org/grpc" in content:
            add_item(backend_items, seen_backend, "gRPC", "framework", 1.0, rel_path)

        if "gorm.io/gorm" in content:
            add_item(database_items, seen_database, "GORM", "orm", 1.0, rel_path)
        if "github.com/jackc/pgx" in content or "github.com/lib/pq" in content:
            add_item(database_items, seen_database, "PostgreSQL", "database", 1.0, rel_path)
        if "github.com/go-sql-driver/mysql" in content:
            add_item(database_items, seen_database, "MySQL", "database", 1.0, rel_path)
        if "github.com/redis/go-redis" in content:
            add_item(database_items, seen_database, "Redis", "database", 1.0, rel_path)

    @classmethod
    def _parse_cargo_toml(
        cls,
        content: str,
        rel_path: str,
        add_item,
        backend_items, seen_backend,
        database_items, seen_database,
        detected_languages: Set[str],
    ):
        add_item(backend_items, seen_backend, "Rust", "language", 1.0, rel_path)
        detected_languages.add("Rust")

        if "actix-web" in content:
            add_item(backend_items, seen_backend, "Actix Web", "framework", 1.0, rel_path)
        if "axum" in content:
            add_item(backend_items, seen_backend, "Axum", "framework", 1.0, rel_path)
        if "rocket" in content:
            add_item(backend_items, seen_backend, "Rocket", "framework", 1.0, rel_path)

        if "diesel" in content:
            add_item(database_items, seen_database, "Diesel", "orm", 1.0, rel_path)
        if "sqlx" in content:
            add_item(database_items, seen_database, "SQLx", "orm", 1.0, rel_path)
        if "tokio-postgres" in content:
            add_item(database_items, seen_database, "PostgreSQL", "database", 1.0, rel_path)

    @classmethod
    def _parse_jvm_manifest(
        cls,
        content: str,
        rel_path: str,
        add_item,
        backend_items, seen_backend,
        database_items, seen_database,
        detected_languages: Set[str],
    ):
        norm_p = rel_path.replace("\\", "/").lower()
        is_android_wrapper = norm_p.startswith("android/") or "/android/" in norm_p

        # If it's an Android wrapper (e.g. Flutter / React Native), only parse if Spring Boot or server framework is present
        if is_android_wrapper:
            if "spring-boot" not in content and "org.springframework.boot" not in content:
                return

        add_item(backend_items, seen_backend, "Java", "language", 1.0, rel_path)
        detected_languages.add("Java")

        if "spring-boot" in content or "org.springframework.boot" in content:
            add_item(backend_items, seen_backend, "Spring Boot", "framework", 1.0, rel_path)
        if "hibernate" in content:
            add_item(database_items, seen_database, "Hibernate", "orm", 1.0, rel_path)
        if "postgresql" in content:
            add_item(database_items, seen_database, "PostgreSQL", "database", 1.0, rel_path)
        if "mysql" in content:
            add_item(database_items, seen_database, "MySQL", "database", 1.0, rel_path)

    @classmethod
    def _parse_composer_json(
        cls,
        content: str,
        rel_path: str,
        add_item,
        backend_items, seen_backend,
        database_items, seen_database,
        detected_languages: Set[str],
    ):
        add_item(backend_items, seen_backend, "PHP", "language", 1.0, rel_path)
        detected_languages.add("PHP")

        if "laravel/framework" in content:
            add_item(backend_items, seen_backend, "Laravel", "framework", 1.0, rel_path)
        if "symfony/" in content:
            add_item(backend_items, seen_backend, "Symfony", "framework", 1.0, rel_path)

    @classmethod
    def _parse_gemfile(
        cls,
        content: str,
        rel_path: str,
        add_item,
        backend_items, seen_backend,
        database_items, seen_database,
        detected_languages: Set[str],
    ):
        add_item(backend_items, seen_backend, "Ruby", "language", 1.0, rel_path)
        detected_languages.add("Ruby")

        if "rails" in content:
            add_item(backend_items, seen_backend, "Ruby on Rails", "framework", 1.0, rel_path)
        if "sinatra" in content:
            add_item(backend_items, seen_backend, "Sinatra", "framework", 1.0, rel_path)

    @classmethod
    def _inspect_code_imports(
        cls,
        snippets: List[Tuple[str, str]],
        add_item,
        frontend_items, seen_frontend,
        backend_items, seen_backend,
        database_items, seen_database,
    ):
        for file_path, code in snippets:
            # Python imports
            if "from fastapi import" in code or "import fastapi" in code:
                add_item(backend_items, seen_backend, "FastAPI", "framework", 0.90, file_path)
            if "from flask import" in code or "import flask" in code:
                add_item(backend_items, seen_backend, "Flask", "framework", 0.90, file_path)
            if "from django" in code or "import django" in code:
                add_item(backend_items, seen_backend, "Django", "framework", 0.90, file_path)
            if "from sqlalchemy" in code or "import sqlalchemy" in code:
                add_item(database_items, seen_database, "SQLAlchemy", "orm", 0.90, file_path)

            # JS/TS imports
            if "from 'react'" in code or 'from "react"' in code or "require('react')" in code:
                add_item(frontend_items, seen_frontend, "React", "framework", 0.90, file_path)
            if "from 'express'" in code or 'from "express"' in code or "require('express')" in code:
                add_item(backend_items, seen_backend, "Express", "framework", 0.90, file_path)
                add_item(backend_items, seen_backend, "Node.js", "runtime", 0.85, file_path)

    # --- Discovery Entry Points ---

    @classmethod
    def detect_from_directory(cls, directory_path: Union[str, Path]) -> TechStackRead:
        """
        Scans a local directory on disk for manifest files and source code to determine the technology stack.
        """
        dir_p = Path(directory_path)
        if not dir_p.exists() or not dir_p.is_dir():
            return TechStackRead()

        manifest_contents: Dict[str, str] = {}
        all_file_paths: List[str] = []
        snippets: List[Tuple[str, str]] = []

        manifest_names = {
            "package.json", "requirements.txt", "requirements-dev.txt", "pyproject.toml",
            "pipfile", "pubspec.yaml", "dockerfile", "docker-compose.yml",
            "docker-compose.yaml", "compose.yml", "compose.yaml",
            "go.mod", "cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
            "composer.json", "gemfile", "nginx.conf"
        }

        try:
            for root, dirs, files in os.walk(dir_p):
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
                for f in files:
                    full_p = Path(root) / f
                    rel_p = str(full_p.relative_to(dir_p)).replace("\\", "/")
                    all_file_paths.append(rel_p)

                    f_low = f.lower()
                    is_manifest = (
                        f_low in manifest_names
                        or f_low.startswith("dockerfile")
                        or f_low.endswith(".dockerfile")
                        or "docker-compose" in f_low
                        or (f_low.endswith(".txt") and "requirements" in rel_p.lower())
                    )

                    if is_manifest:
                        try:
                            # Read first 100 KB
                            manifest_contents[rel_p] = full_p.read_text(encoding="utf-8", errors="ignore")[:102400]
                        except Exception as read_err:
                            logger.debug(f"Could not read manifest {rel_p}: {read_err}")

                    # Sample imports from small entrypoint files (e.g. main.py, app.py, server.js)
                    elif f_low in ("main.py", "app.py", "server.js", "index.ts", "app.ts", "main.go") and len(snippets) < 10:
                        try:
                            sample_text = full_p.read_text(encoding="utf-8", errors="ignore")[:4096]
                            snippets.append((rel_p, sample_text))
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Error walking directory {directory_path}: {e}")

        return cls.detect_from_files(manifest_contents, all_file_paths, snippets)

    @classmethod
    def detect_from_db(
        cls, 
        db: Session, 
        repository_id: int,
        manifest_contents: Optional[Dict[str, str]] = None
    ) -> TechStackRead:
        """
        Analyzes an indexed repository in the database by reading its IndexedFile paths,
        CodeChunks for manifest files, or reading clone_url files if locally available.
        """
        from backend.app.models.repository import Repository
        from backend.app.models.indexed_file import IndexedFile
        from backend.app.models.code_chunk import CodeChunk

        repo = db.query(Repository).filter(Repository.id == repository_id).first()
        if not repo:
            return TechStackRead()

        # If repo clone_url exists as local directory on disk, analyze it directly for maximum accuracy
        if repo.clone_url and Path(repo.clone_url).exists() and Path(repo.clone_url).is_dir():
            return cls.detect_from_directory(Path(repo.clone_url))

        # Otherwise analyze indexed files and code chunks from database
        indexed_files = db.query(IndexedFile).filter(IndexedFile.repository_id == repository_id).all()
        if not indexed_files:
            return TechStackRead()

        all_file_paths = [f.path for f in indexed_files]
        manifest_names = {
            "package.json", "requirements.txt", "requirements-dev.txt", "pyproject.toml",
            "pipfile", "pubspec.yaml", "dockerfile", "docker-compose.yml",
            "docker-compose.yaml", "compose.yml", "compose.yaml",
            "go.mod", "cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
            "composer.json", "gemfile", "nginx.conf"
        }

        manifest_paths: List[str] = []
        for p in all_file_paths:
            p_low = p.lower()
            fname = Path(p_low).name
            if (
                fname in manifest_names
                or fname.startswith("dockerfile")
                or fname.endswith(".dockerfile")
                or "docker-compose" in fname
                or (fname.endswith(".txt") and "requirements" in p_low)
            ):
                manifest_paths.append(p)

        loaded_manifest_contents: Dict[str, str] = {}
        if manifest_paths:
            # Query chunks for these manifest files
            chunks = db.query(CodeChunk).filter(
                CodeChunk.repository_id == repository_id,
                CodeChunk.file_path.in_(manifest_paths)
            ).order_by(CodeChunk.file_path, CodeChunk.chunk_index).all()

            chunks_by_file: Dict[str, List[str]] = {}
            for c in chunks:
                # Strip out chunker header "// File: ... | Lines: ...\n" if present
                clean_lines = []
                for line in c.chunk_text.splitlines():
                    if line.startswith("// File:") and "Lines:" in line:
                        continue
                    clean_lines.append(line)
                chunks_by_file.setdefault(c.file_path, []).append("\n".join(clean_lines))

            for fp, chunk_texts in chunks_by_file.items():
                loaded_manifest_contents[fp] = "\n".join(chunk_texts)

        if manifest_contents:
            loaded_manifest_contents.update(manifest_contents)

        # Sample code chunks from entrypoint files for import scanning
        entry_chunks = db.query(CodeChunk).filter(
            CodeChunk.repository_id == repository_id,
            CodeChunk.chunk_index == 0
        ).limit(20).all()

        snippets = [(c.file_path, c.chunk_text) for c in entry_chunks]

        return cls.detect_from_files(loaded_manifest_contents, all_file_paths, snippets)
