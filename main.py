import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from greennode_agentbase import GreenNodeAgentBaseApp, PingStatus, RequestContext

from knowledge_store import KnowledgeStore


load_dotenv()

app = GreenNodeAgentBaseApp()
store = KnowledgeStore()


def build_help() -> dict[str, Any]:
    return {
        "agent": "business-knowledge-learning-agent",
        "purpose": "Thu thập, parse, review, và chuẩn hóa knowledge nghiệp vụ từ stakeholder và file text.",
        "actions": {
            "teach_text": "Dạy agent bằng đoạn văn tự do. Fields: text, stakeholder, team, domain, owner.",
            "review_candidate": "Approve/reject/edit candidate. Fields: candidate_id, decision, updates.",
            "list_candidates": "Liệt kê candidate theo status. Fields: status.",
            "search_knowledge": "Tìm approved knowledge. Fields: query.",
            "analyze_text": "Phân tích text dựa trên approved/pending/conflict knowledge. Fields: text.",
            "ingest_document": "Ingest nội dung file dạng text. Fields: text, title, stakeholder, team, domain, owner.",
            "help": "Hiển thị các action được hỗ trợ.",
        },
    }


def build_analyze_answer(result: dict[str, Any]) -> str:
    parts: list[str] = []
    if result["known"]:
        rendered = "; ".join(
            f"{item['name']}: {item.get('canonical_definition') or 'Đã có trong knowledge base'}"
            for item in result["known"]
        )
        parts.append(f"Đã biết: {rendered}.")
    if result["pending"]:
        parts.append("Đang chờ duyệt: " + ", ".join(item["name"] for item in result["pending"]) + ".")
    if result["conflicts"]:
        parts.append("Đang mâu thuẫn: " + ", ".join(item["name"] for item in result["conflicts"]) + ".")
    if result["unknown"]:
        parts.append("Chưa có knowledge chuẩn: " + ", ".join(result["unknown"]) + ".")
    return " ".join(parts) if parts else "Không phát hiện knowledge liên quan."


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    action = str(payload.get("action") or "help").strip().lower()

    try:
        if action == "help":
            result = build_help()
        elif action == "teach_text":
            result = store.teach_text(
                text=str(payload.get("text") or payload.get("message") or ""),
                stakeholder=str(payload.get("stakeholder") or ""),
                team=str(payload.get("team") or ""),
                domain=str(payload.get("domain") or ""),
                owner=str(payload.get("owner") or ""),
            )
            result["answer"] = (
                f"Đã lưu raw event và tạo {len(result['candidates'])} candidate cần review."
                if result["candidates"]
                else "Đã lưu raw event nhưng chưa parse được candidate rõ ràng."
            )
        elif action == "review_candidate":
            result = store.review_candidate(
                candidate_id=str(payload.get("candidate_id") or ""),
                decision=str(payload.get("decision") or ""),
                updates=payload.get("updates") if isinstance(payload.get("updates"), dict) else None,
            )
            result["answer"] = (
                "Candidate đã được duyệt vào knowledge base."
                if result.get("knowledge")
                else f"Candidate đang ở trạng thái {result['candidate']['status']}."
            )
        elif action == "list_candidates":
            result = {
                "candidates": store.list_candidates(status=str(payload.get("status") or "")),
            }
        elif action == "search_knowledge":
            result = {
                "knowledge": store.search_knowledge(query=str(payload.get("query") or "")),
            }
        elif action == "analyze_text":
            analysis = store.analyze_text(str(payload.get("text") or payload.get("message") or ""))
            result = {"answer": build_analyze_answer(analysis), **analysis}
        elif action == "ingest_document":
            result = store.ingest_document(
                text=str(payload.get("text") or payload.get("content") or ""),
                title=str(payload.get("title") or ""),
                stakeholder=str(payload.get("stakeholder") or ""),
                team=str(payload.get("team") or ""),
                domain=str(payload.get("domain") or ""),
                owner=str(payload.get("owner") or ""),
            )
            result["answer"] = (
                f"Đã ingest {len(result['chunks'])} chunk và tạo {len(result['candidates'])} candidate cần review."
            )
        else:
            result = {
                "error": f"Action chưa được hỗ trợ: {action}",
                "help": build_help(),
            }

        return {
            "status": "success" if "error" not in result else "error",
            "timestamp": datetime.now().isoformat(),
            "session_id": context.session_id,
            "result": result,
        }
    except ValueError as error:
        return {
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "session_id": context.session_id,
            "error": str(error),
        }


@app.ping
def health_check() -> PingStatus:
    store.bootstrap()
    return PingStatus.HEALTHY


if __name__ == "__main__":
    store.bootstrap()
    app.run(port=int(os.getenv("PORT", "8080")), host="0.0.0.0")
