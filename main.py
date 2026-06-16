import os
import sys

from dotenv import load_dotenv
from greennode_agentbase import GreenNodeAgentBaseApp, PingStatus, RequestContext
from greennode_agentbase.runtime.app import XAccelBufferingMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from api_contracts import AgentApiRouter
from knowledge_store import KnowledgeStore


class SPAStaticFiles(StaticFiles):
    """Serve a React SPA: return index.html for any path not found as a file."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


load_dotenv()

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Cho phep UI (mo bang file:// hoac http://localhost) goi API tu trinh duyet.
# CORS_ALLOW_ORIGINS: danh sach origin cach nhau dau phay; mac dinh "*" (cho moi origin).
_cors_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()]

app = GreenNodeAgentBaseApp(
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        ),
        Middleware(XAccelBufferingMiddleware),
    ]
)
store = KnowledgeStore()
router = AgentApiRouter(store)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    return router.dispatch(payload, context)


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


def bootstrap_store() -> None:
    try:
        store.bootstrap()
        print("[startup] bootstrap OK", flush=True)
    except Exception as exc:
        print(f"[startup] bootstrap warning: {exc}", flush=True)


_ui_dist = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "dist")
if os.path.isdir(_ui_dist):
    app.mount("/", SPAStaticFiles(directory=_ui_dist, html=True), name="ui")
    print(f"[startup] serving UI from {_ui_dist}", flush=True)


if __name__ == "__main__":
    bootstrap_store()
    app.run(port=int(os.getenv("PORT", "8080")), host="0.0.0.0")
