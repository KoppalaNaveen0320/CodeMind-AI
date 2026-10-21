from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.app.core.config import settings

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))

# Cache-control headers to prevent sensitive dashboard data from lingering in browser cache or history
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
    "Pragma": "no-cache",
    "Expires": "0",
}


def render_authenticated_page(request: Request, template_name: str) -> HTMLResponse:
    """Renders an authenticated template with strict no-cache headers."""
    return templates.TemplateResponse(request=request, name=template_name, headers=NO_CACHE_HEADERS)


def redirect_to_clean(request: Request, clean_path: str) -> RedirectResponse:
    """Redirects legacy .html URLs to their clean counterparts, preserving query parameters."""
    query = request.url.query
    target = f"{clean_path}?{query}" if query else clean_path
    return RedirectResponse(url=target, status_code=302, headers=NO_CACHE_HEADERS)


# ==========================================
# Clean Page Routes (Direct Template Serving)
# ==========================================

@router.get("/landing", response_class=HTMLResponse)
async def view_landing(request: Request):
    return templates.TemplateResponse(request=request, name="landing.html")


@router.get("/login", response_class=HTMLResponse)
async def view_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@router.get("/signup", response_class=HTMLResponse)
async def view_signup(request: Request):
    return templates.TemplateResponse(request=request, name="signup.html")


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def view_dashboard(request: Request):
    return render_authenticated_page(request, "dashboard.html")


@router.get("/repositories", response_class=HTMLResponse)
async def view_repositories(request: Request):
    return render_authenticated_page(request, "repositories.html")


@router.get("/repositories_modal", response_class=HTMLResponse)
@router.get("/repositories-modal", response_class=HTMLResponse)
async def view_repositories_modal(request: Request):
    return render_authenticated_page(request, "repositories_modal.html")


@router.get("/assistant", response_class=HTMLResponse)
async def view_assistant(request: Request):
    return render_authenticated_page(request, "assistant.html")


@router.get("/assistant_empty", response_class=HTMLResponse)
@router.get("/assistant-empty", response_class=HTMLResponse)
async def view_assistant_empty(request: Request):
    return render_authenticated_page(request, "assistant_empty.html")


@router.get("/code_viewer", response_class=HTMLResponse)
@router.get("/code-viewer", response_class=HTMLResponse)
@router.get("/code", response_class=HTMLResponse)
async def view_code_viewer(request: Request):
    return render_authenticated_page(request, "code_viewer.html")


@router.get("/dependencies", response_class=HTMLResponse)
async def view_dependencies(request: Request):
    return render_authenticated_page(request, "dependencies.html")


@router.get("/impact_analysis", response_class=HTMLResponse)
@router.get("/impact-analysis", response_class=HTMLResponse)
@router.get("/impact", response_class=HTMLResponse)
async def view_impact_analysis(request: Request):
    return render_authenticated_page(request, "impact_analysis.html")


@router.get("/git_history", response_class=HTMLResponse)
@router.get("/git-history", response_class=HTMLResponse)
@router.get("/history", response_class=HTMLResponse)
async def view_git_history(request: Request):
    return render_authenticated_page(request, "git_history.html")


@router.get("/security_insights", response_class=HTMLResponse)
@router.get("/security-insights", response_class=HTMLResponse)
@router.get("/security", response_class=HTMLResponse)
async def view_security_insights(request: Request):
    return render_authenticated_page(request, "security_insights.html")


@router.get("/docs", response_class=HTMLResponse)
@router.get("/documentation", response_class=HTMLResponse)
async def view_docs(request: Request):
    return render_authenticated_page(request, "docs.html")


@router.get("/settings", response_class=HTMLResponse)
async def view_settings(request: Request):
    return render_authenticated_page(request, "settings.html")


@router.get("/index", response_class=HTMLResponse)
@router.get("/suite", response_class=HTMLResponse)
async def view_suite_preview(request: Request):
    return render_authenticated_page(request, "index.html")


# ==========================================
# Legacy .html Redirect Routes (HTTP 302 with Query Params Preserved)
# ==========================================

@router.get("/landing.html")
async def redirect_landing_html(request: Request):
    return redirect_to_clean(request, "/landing")


@router.get("/login.html")
async def redirect_login_html(request: Request):
    return redirect_to_clean(request, "/login")


@router.get("/signup.html")
async def redirect_signup_html(request: Request):
    return redirect_to_clean(request, "/signup")


@router.get("/dashboard.html")
async def redirect_dashboard_html(request: Request):
    return redirect_to_clean(request, "/dashboard")


@router.get("/repositories.html")
async def redirect_repositories_html(request: Request):
    return redirect_to_clean(request, "/repositories")


@router.get("/repositories_modal.html")
async def redirect_repositories_modal_html(request: Request):
    return redirect_to_clean(request, "/repositories_modal")


@router.get("/assistant.html")
async def redirect_assistant_html(request: Request):
    return redirect_to_clean(request, "/assistant")


@router.get("/assistant_empty.html")
async def redirect_assistant_empty_html(request: Request):
    return redirect_to_clean(request, "/assistant_empty")


@router.get("/code_viewer.html")
async def redirect_code_viewer_html(request: Request):
    return redirect_to_clean(request, "/code_viewer")


@router.get("/dependencies.html")
async def redirect_dependencies_html(request: Request):
    return redirect_to_clean(request, "/dependencies")


@router.get("/impact_analysis.html")
async def redirect_impact_analysis_html(request: Request):
    return redirect_to_clean(request, "/impact_analysis")


@router.get("/git_history.html")
async def redirect_git_history_html(request: Request):
    return redirect_to_clean(request, "/git_history")


@router.get("/security_insights.html")
async def redirect_security_insights_html(request: Request):
    return redirect_to_clean(request, "/security_insights")


@router.get("/docs.html")
async def redirect_docs_html(request: Request):
    return redirect_to_clean(request, "/docs")


@router.get("/settings.html")
async def redirect_settings_html(request: Request):
    return redirect_to_clean(request, "/settings")


@router.get("/index.html")
async def redirect_index_html(request: Request):
    return redirect_to_clean(request, "/index")
