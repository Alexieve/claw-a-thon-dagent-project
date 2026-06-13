import os
import sys

from dotenv import load_dotenv
from greennode_agentbase import GreenNodeAgentBaseApp, PingStatus, RequestContext
from greennode_agentbase.runtime.app import XAccelBufferingMiddleware
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from api_contracts import AgentApiRouter
from knowledge_store import KnowledgeStore


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


if __name__ == "__main__":
    try:
        store.bootstrap()
    except Exception as exc:
        print(f"[startup] bootstrap warning: {exc}", flush=True)
    app.run(port=int(os.getenv("PORT", "8080")), host="0.0.0.0")
