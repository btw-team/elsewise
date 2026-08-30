import asyncio
import hmac
import ipaddress
import mimetypes
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from elsewise import __version__
from elsewise.agents.app_server import CodexAppServerProvider
from elsewise.agents.claude_cli import ClaudeCodeProvider
from elsewise.agents.fake import FakeAgentProvider
from elsewise.agents.interface import AgentProvider
from elsewise.agents.queue import AgentQueueManager
from elsewise.agents.registry import AgentProviderRegistry
from elsewise.api import router
from elsewise.api.ingest import ingest_websocket
from elsewise.api.router import ui_websocket
from elsewise.api.runtime import runtime_websocket
from elsewise.api.security import safe_http_request
from elsewise.observability import RuntimeDiagnostics
from elsewise.persistence.database import Database
from elsewise.services.errors import ServiceError
from elsewise.services.maintenance import mark_sources_disconnected, perform_startup_maintenance
from elsewise.services.runtime_status import RuntimeStatusService
from elsewise.services.sessions import recover_after_restart
from elsewise.settings.config import SettingsStore
from elsewise.settings.pairing import PairingManager
from elsewise.settings.paths import AppPaths


def _register_web_asset_media_types() -> None:
    # On Windows, mimetypes incorporates registry entries and may map JavaScript
    # files to text/plain. Browsers refuse to execute ES modules served that way.
    mimetypes.add_type("text/javascript", ".js", strict=True)
    mimetypes.add_type("text/javascript", ".mjs", strict=True)


def create_app(
    *,
    database_url: str | None = None,
    pairing_path: Path | None = None,
    settings_path: Path | None = None,
    agent_provider: AgentProvider | AgentProviderRegistry | None = None,
    app_paths: AppPaths | None = None,
) -> FastAPI:
    paths = app_paths or AppPaths.resolve(ensure_exists=database_url is None)
    resolved_url = database_url or os.environ.get("ELSEWISE_DATABASE_URL")
    database = Database(resolved_url) if resolved_url else Database.from_path(paths.database)
    configured_pairing = os.environ.get("ELSEWISE_PAIRING_PATH")
    pairing = PairingManager(
        pairing_path
        or (Path(configured_pairing) if configured_pairing else paths.config / "pairing.json")
    )
    settings = SettingsStore(settings_path or paths.config / "settings.json")
    provider = agent_provider
    if provider is None:
        configured = settings.load()
        provider = (
            AgentProviderRegistry({"codex": FakeAgentProvider(), "claude": FakeAgentProvider()})
            if os.environ.get("ELSEWISE_AGENT_PROVIDER") == "fake"
            else AgentProviderRegistry(
                {
                    "codex": CodexAppServerProvider(configured.codex_executable),
                    "claude": ClaudeCodeProvider(configured.claude_executable),
                }
            )
        )
    agent_queue = AgentQueueManager(database, provider, paths, settings)
    diagnostics = RuntimeDiagnostics()
    runtime_status_service = RuntimeStatusService(
        database, diagnostics, agent_queue, settings, paths
    )
    session_cleanup_tasks: set[asyncio.Task[None]] = set()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.migrate()
        pairing.ensure()
        recover_after_restart(database)
        mark_sources_disconnected(database)
        perform_startup_maintenance(database)
        await agent_queue.start()
        try:
            yield
        finally:
            for task in session_cleanup_tasks:
                task.cancel()
            if session_cleanup_tasks:
                await asyncio.gather(*session_cleanup_tasks, return_exceptions=True)
            try:
                await runtime_status_service.stop()
            finally:
                try:
                    await agent_queue.stop()
                finally:
                    database.dispose()

    application = FastAPI(title="Elsewise", version=__version__, lifespan=lifespan)
    application.state.database = database
    application.state.paths = paths
    application.state.pairing = pairing
    application.state.settings = settings
    application.state.agent_queue = agent_queue
    application.state.diagnostics = diagnostics
    application.state.runtime_status = runtime_status_service
    application.state.session_cleanup_tasks = session_cleanup_tasks
    application.state.request_shutdown = None

    def valid_control_request(request: Request) -> bool:
        client = request.client
        try:
            is_loopback = client is not None and ipaddress.ip_address(client.host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            return False
        try:
            expected = (paths.runtime / "control-token").read_text(encoding="utf-8").strip()
        except OSError:
            expected = ""
        provided = request.headers.get("X-Elsewise-Control-Token", "")
        return bool(expected and provided and hmac.compare_digest(provided, expected))

    @application.middleware("http")
    async def protect_loopback_api(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path.startswith("/api/") and not safe_http_request(request):
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "invalid_origin", "message": "Invalid origin."}},
            )
        return await call_next(request)

    application.include_router(router)

    @application.post("/api/runtime/shutdown", include_in_schema=False)
    async def runtime_shutdown(request: Request) -> JSONResponse:
        if not valid_control_request(request):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "invalid_control_token",
                        "message": "The control token is invalid.",
                    }
                },
            )
        shutdown = request.app.state.request_shutdown
        if shutdown is None:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "shutdown_unavailable",
                        "message": "Runtime shutdown is unavailable.",
                    }
                },
            )
        shutdown()
        return JSONResponse(content={"status": "stopping"})

    @application.post("/api/runtime/agent-drain", include_in_schema=False)
    async def runtime_agent_drain(request: Request) -> JSONResponse:
        if not valid_control_request(request):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "invalid_control_token",
                        "message": "The control token is invalid.",
                    }
                },
            )
        enabled = request.query_params.get("enabled", "true").lower() == "true"
        agent_queue.set_draining(enabled)
        return JSONResponse(content={"draining": enabled})

    @application.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @application.exception_handler(HTTPException)
    async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = str(exc.detail)
        code = (
            detail
            if detail.isidentifier() and detail.islower()
            else ("not_found" if exc.status_code == 404 else "request_failed")
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": detail}},
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "request_validation_error",
                    "message": "The request data is invalid.",
                }
            },
        )

    @application.websocket("/ws/ui")
    async def websocket_route(websocket: WebSocket) -> None:
        await ui_websocket(websocket)

    @application.websocket("/ws/ingest")
    async def ingest_route(websocket: WebSocket) -> None:
        await ingest_websocket(websocket)

    @application.websocket("/ws/runtime")
    async def runtime_websocket_route(websocket: WebSocket) -> None:
        await runtime_websocket(websocket)

    configured_web = os.environ.get("ELSEWISE_WEB_DIST")
    packaged_web = Path(__file__).resolve().parent / "web_dist"
    repository_web = Path(__file__).resolve().parents[3] / "web" / "dist"
    web_dist = Path(configured_web) if configured_web else packaged_web
    if not configured_web and not web_dist.is_dir():
        web_dist = repository_web
    if web_dist.is_dir() and (web_dist / "index.html").is_file():
        assets = web_dist / "assets"
        if assets.is_dir():
            _register_web_asset_media_types()
            application.mount("/assets", StaticFiles(directory=assets), name="web-assets")

        @application.get("/{spa_path:path}", include_in_schema=False)
        async def spa_fallback(spa_path: str) -> FileResponse:
            if spa_path in {"api", "ws"} or spa_path.startswith(("api/", "ws/")):
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(
                web_dist / "index.html",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

    return application


app = create_app()


def main() -> None:
    from elsewise.runtime.server_runner import main as run_server

    run_server()
