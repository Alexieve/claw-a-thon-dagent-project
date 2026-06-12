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
            "chat": "Entry chính cho hỏi đáp freeform. Fields: message, user_id, session_id.",
            "start_teach_session": "Bắt đầu Flow A teaching nhiều lượt. Fields: message, stakeholder, team, domain, owner.",
            "append_teach_message": "Thêm message vào teaching session. Fields: session_id, message.",
            "summarize_teach_session": "Tóm tắt draft knowledge để user confirm. Fields: session_id.",
            "confirm_teach_session": "Confirm/cancel teaching session. Fields: session_id, decision.",
            "teach_text": "Dạy knowledge đã được user confirm. New knowledge ghi thẳng KB, existing tạo pending change.",
            "review_candidate": "Approve/reject pending change. Fields: candidate_id, decision, updates.",
            "list_candidates": "Liệt kê candidate theo status. Fields: status.",
            "search_knowledge": "Tìm approved knowledge, dùng LLM rerank nếu được cấu hình. Fields: query.",
            "ask_data_question": "Hỏi câu hỏi data; agent trả needs_dictionary/needs_knowledge/sql_draft. Fields: question.",
            "add_data_dictionary": "Thêm mapping bảng/cột đã approved. Fields: table, description, columns, relationships, owner, status.",
            "search_data_dictionary": "Tìm mapping bảng/cột theo table, column, alias, business meaning. Fields: query.",
            "list_data_dictionary": "Liệt kê data dictionary đã lưu.",
            "add_question_example": "Thêm SQL mẫu đã approved. Fields: question, sql, explanation, concepts, used_tables, owner, status.",
            "search_question_examples": "Tìm SQL mẫu theo question/concepts/tables. Fields: query.",
            "list_question_examples": "Liệt kê question examples đã lưu.",
            "storage_status": "Kiểm tra agent đang dùng JSON local hay Postgres/Supabase.",
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
    action = str(payload.get("action") or ("chat" if payload.get("message") or payload.get("question") else "help")).strip().lower()

    try:
        if action == "help":
            result = build_help()
        elif action == "chat":
            result = store.chat(
                message=str(payload.get("message") or payload.get("question") or ""),
                user_id=str(payload.get("user_id") or context.user_id or ""),
                session_id=str(payload.get("session_id") or context.session_id or ""),
                pending_action_id=str(payload.get("pending_action_id") or ""),
                debug_context=bool(payload.get("debug_context")),
                use_runtime_skills=payload.get("use_runtime_skills"),
            )
        elif action == "teach_text":
            result = store.teach_text(
                text=str(payload.get("text") or payload.get("message") or ""),
                stakeholder=str(payload.get("stakeholder") or ""),
                team=str(payload.get("team") or ""),
                domain=str(payload.get("domain") or ""),
                owner=str(payload.get("owner") or ""),
            )
            result["answer"] = (
                f"Đã tạo {len(result['knowledge_created'])} knowledge mới và {len(result['change_requests'])} pending change."
                if result["knowledge_created"] or result["change_requests"]
                else "Đã lưu raw event nhưng chưa parse được knowledge rõ ràng."
            )
        elif action == "start_teach_session":
            result = store.start_teach_session(
                message=str(payload.get("message") or payload.get("text") or ""),
                stakeholder=str(payload.get("stakeholder") or ""),
                team=str(payload.get("team") or ""),
                domain=str(payload.get("domain") or ""),
                owner=str(payload.get("owner") or ""),
            )
        elif action == "append_teach_message":
            result = store.append_teach_message(
                session_id=str(payload.get("session_id") or ""),
                message=str(payload.get("message") or payload.get("text") or ""),
            )
        elif action == "summarize_teach_session":
            result = store.summarize_teach_session(session_id=str(payload.get("session_id") or ""))
        elif action == "confirm_teach_session":
            result = store.confirm_teach_session(
                session_id=str(payload.get("session_id") or ""),
                decision=str(payload.get("decision") or "confirm"),
            )
            result["answer"] = (
                f"Đã ghi {len(result['knowledge_created'])} knowledge mới vào KB."
                if result.get("knowledge_created")
                else f"Đã tạo {len(result.get('change_requests', []))} pending change cần duyệt."
                if result.get("change_requests")
                else "Teaching session đã được hủy."
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
        elif action == "ask_data_question":
            result = store.ask_data_question(question=str(payload.get("question") or payload.get("message") or ""))
        elif action == "add_data_dictionary":
            columns = payload.get("columns")
            relationships = payload.get("relationships")
            result = {
                "data_dictionary": store.add_data_dictionary(
                    table=str(payload.get("table") or ""),
                    description=str(payload.get("description") or ""),
                    columns=columns if isinstance(columns, list) else [],
                    relationships=relationships if isinstance(relationships, list) else [],
                    owner=str(payload.get("owner") or ""),
                    status=str(payload.get("status") or "approved"),
                )
            }
            result["answer"] = f"Đã thêm data dictionary cho bảng {result['data_dictionary']['table']}."
        elif action == "search_data_dictionary":
            result = {
                "data_dictionary": store.search_data_dictionary(query=str(payload.get("query") or "")),
            }
        elif action == "list_data_dictionary":
            result = {
                "data_dictionary": store.list_data_dictionary(),
            }
        elif action == "add_question_example":
            concepts = payload.get("concepts")
            used_tables = payload.get("used_tables")
            result = {
                "question_example": store.add_question_example(
                    question=str(payload.get("question") or ""),
                    sql=str(payload.get("sql") or ""),
                    explanation=str(payload.get("explanation") or ""),
                    concepts=concepts if isinstance(concepts, list) else [],
                    used_tables=used_tables if isinstance(used_tables, list) else [],
                    owner=str(payload.get("owner") or ""),
                    status=str(payload.get("status") or "approved"),
                )
            }
            result["answer"] = f"Đã thêm question example {result['question_example']['id']}."
        elif action == "search_question_examples":
            result = {
                "question_examples": store.search_question_examples(query=str(payload.get("query") or "")),
            }
        elif action == "list_question_examples":
            result = {
                "question_examples": store.list_question_examples(),
            }
        elif action == "storage_status":
            result = store.storage_status()
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
