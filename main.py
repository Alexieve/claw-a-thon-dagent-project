import os

from dotenv import load_dotenv
from greennode_agentbase import GreenNodeAgentBaseApp, PingStatus, RequestContext

from api_contracts import AgentApiRouter
from knowledge_store import KnowledgeStore


load_dotenv()

app = GreenNodeAgentBaseApp()
store = KnowledgeStore()
router = AgentApiRouter(store)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    return router.dispatch(payload, context)


@app.ping
def health_check() -> PingStatus:
    store.bootstrap()
    return PingStatus.HEALTHY


if __name__ == "__main__":
    store.bootstrap()
    app.run(port=int(os.getenv("PORT", "8080")), host="0.0.0.0")
