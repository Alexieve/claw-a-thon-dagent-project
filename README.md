# business-knowledge-learning-agent

Agent GreenNode AgentBase giúp team nghiệp vụ thu thập, parse, review, và chuẩn hóa knowledge từ stakeholder hoặc file cứng.

## Agent Này Làm Gì

- Hỗ trợ Flow A teaching nhiều lượt: user dạy, agent tóm tắt, user confirm rồi mới commit.
- Knowledge mới sau khi confirm được ghi thẳng vào knowledge base chuẩn.
- Knowledge đã tồn tại luôn tạo pending change để reviewer approve/reject trước khi cập nhật.
- Owner gốc của knowledge không bị ghi đè khi có thay đổi từ người khác.
- Ingest nội dung file dạng text/pasted text theo cùng policy: mới thì commit, existing thì pending change.
- Trả lời freeform qua action `chat`; user có thể hỏi tự nhiên mà không cần biết format action nội bộ.
- Search approved knowledge bằng LLM rerank nếu cấu hình LLM, fallback deterministic nếu không.
- Phân tích một đoạn text để chỉ ra knowledge đã biết, đang chờ duyệt, đang conflict, hoặc còn thiếu.
- Hỗ trợ Flow B bootstrap: hỏi câu hỏi data, chỉ ra thiếu Domain Knowledge/Data Dictionary, hoặc sinh SQL draft khi đủ context.
- Cho phép bổ sung dần Data Dictionary và Question Examples từ câu hỏi thật.

## Cấu Trúc Dự Án

- `main.py` - Điểm vào AgentBase và định tuyến action mới.
- `knowledge_store.py` - Storage local, parser, teaching session, review workflow, KB versioning.
- `data/raw_events.jsonl` - Append-only log lưu nguyên văn input.
- `data/teaching_sessions.json` - Session teaching nhiều lượt trước khi user confirm.
- `data/chat_sessions.json` - Session hội thoại freeform, pending actions, và trạng thái hỏi/dạy xen kẽ.
- `data/knowledge_candidates.json` - Pending change hoặc candidate cũ cần review.
- `data/knowledge_base.json` - Approved knowledge chuẩn.
- `data/document_chunks.jsonl` - Chunk text từ file cứng.
- `data/data_dictionary.json` - Mapping bảng/cột và alias nghiệp vụ cho Flow B.
- `data/question_examples.json` - SQL mẫu đã approved để tăng chất lượng SQL draft.
- `tests/test_knowledge_store.py` - Unit test cho storage/parser/review flow.

## Cài Đặt

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Khi phát triển local:

```bash
cp .env.example .env
```

LLM là optional nhưng rất nên có nếu muốn agent hội thoại tự nhiên. Nếu có `LLM_API_KEY`, `LLM_BASE_URL`, và `LLM_MODEL`, agent dùng LLM cho parse/summarize, rerank search, intent routing, answer synthesis, và SQL draft có guardrail. Nếu không, agent dùng deterministic fallback parser/search/chat.

Storage mặc định là JSON local trong `data/`. Để dùng Supabase/Postgres, cấu hình:

```bash
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require
```

Khi `DATABASE_URL` tồn tại, agent tự chạy migration trong `db/schema.sql` lúc boot và dùng Postgres cho KB, pending change, teaching session, raw event, document chunk.

Chat context mặc định chạy `auto`: nếu có `CHAT_CONTEXT_MEMORY_ID` thì dùng AgentBase Memory events, nếu chưa có thì fallback local để dễ test Postman.

```bash
CHAT_CONTEXT_BACKEND=auto
CHAT_CONTEXT_MEMORY_ID=mem_xxx
CHAT_CONTEXT_EVENT_LIMIT=12
CHAT_CONTEXT_FALLBACK_ON_MEMORY_ERROR=true
```

AgentBase Memory chỉ dùng cho conversation events theo `user_id` + `session_id`; `chat_sessions` vẫn giữ pending action và teaching/data workflow state.

## Chạy Local

```bash
python3 main.py
```

Agent API sẽ chạy tại:

```text
http://127.0.0.1:8080/invocations
```

Nếu port `8080` đang bận:

```bash
PORT=8081 python3 main.py
```

Health check:

```bash
curl http://127.0.0.1:8080/health
```

Kiểm tra storage backend:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action": "storage_status"}'
```

## API Examples

Entry chính - hỏi freeform:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Tôi muốn biết doanh thu trung bình được gọi là gì?",
    "user_id": "quynh"
  }'
```

Bạn cũng có thể gọi rõ action `chat`:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "chat",
    "message": "RPU khác ARPPU như thế nào?",
    "session_id": "demo-session"
  }'
```

Response `chat` trả `answer` tự nhiên kèm debug/context IDs:

```json
{
  "status": "answered",
  "intent": "knowledge_qa",
  "answer": "Nếu bạn nói doanh thu trung bình trên mỗi active user thì thường gọi là RPU...",
  "requires_confirmation": false,
  "chat_session_id": "chat_xxx",
  "pending_action_id": "",
  "pending_action_type": "",
  "session_state": "idle",
  "resolved_question": "RPU khác ARPPU như thế nào?",
  "conversation_context_used": false,
  "context_terms": [],
  "context_backend": "local",
  "used_knowledge_ids": ["kn_seed_rpu", "kn_seed_arppu"],
  "debug": {
    "llm_used": false,
    "fallback_used": true
  }
}
```

Ví dụ câu hỏi nối ngữ cảnh trong cùng session:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "chat",
    "message": "RPU là gì?",
    "user_id": "quynh",
    "session_id": "demo-session"
  }'

curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "chat",
    "message": "thế tháng 6 theo campaign bao nhiêu?",
    "user_id": "quynh",
    "session_id": "demo-session"
  }'
```

Response thứ hai sẽ có `conversation_context_used: true` và `resolved_question` chứa topic đã nối từ session, ví dụ `RPU thế tháng 6 theo campaign bao nhiêu?`.

Với câu hỏi số liệu, `chat` tự route sang flow data nhưng luôn hỏi confirm trước:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "message": "RPU tháng 6 theo campaign là bao nhiêu?"
  }'
```

Response sẽ có `status: "needs_confirmation"`, `pending_action_type: "data_query"` và `pending_action_id`. Confirm để xử lý:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "message": "confirm",
    "session_id": "chat_xxx",
    "pending_action_id": "act_xxx"
  }'
```

Nếu thiếu mapping bảng/cột sau khi confirm, agent sẽ trả lời tự nhiên rằng cần bổ sung Data Dictionary nào thay vì bịa SQL.

Dạy qua chat cũng dùng pending action, chưa parse hoặc ghi KB cho tới khi bạn confirm:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "message": "AOV là Average Order Value, giá trị đơn hàng trung bình.",
    "user_id": "quynh",
    "session_id": "demo-session"
  }'
```

Sau khi confirm `start_teaching`, agent mới tạo draft. Khi draft đủ rõ, agent tạo tiếp `commit_teaching`; chỉ khi bạn confirm action đó thì KB mới được ghi. Trong lúc draft đang mở, bạn vẫn có thể hỏi chen ngang bằng cùng `session_id`, rồi quay lại confirm/append draft sau.

Flow A - bắt đầu teaching session:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "start_teach_session",
    "message": "FPU là user có first payment. Team Growth hay gọi là paid user đầu tiên.",
    "stakeholder": "Linh",
    "team": "Growth"
  }'
```

Thêm message vào session:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "append_teach_message",
    "session_id": "teach_xxx",
    "message": "FPU thuộc domain Growth và tính theo first payment lifetime."
  }'
```

Confirm session để commit:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "confirm_teach_session",
    "session_id": "teach_xxx",
    "decision": "confirm"
  }'
```

Dạy trực tiếp một đoạn đã được user confirm:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "teach_text",
    "text": "FPU là user có first payment.",
    "stakeholder": "Linh",
    "team": "Growth"
  }'
```

Approve pending change:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "review_candidate",
    "candidate_id": "cand_xxx",
    "decision": "approve"
  }'
```

Approve pending change sau khi sửa:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "review_candidate",
    "candidate_id": "cand_xxx",
    "decision": "approve",
    "updates": {
      "definition": "First Payment User: user phát sinh thanh toán đầu tiên.",
      "paraphrases": ["paid user đầu tiên", "user có first payment"]
    }
  }'
```

Liệt kê pending change:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action": "list_candidates", "status": "pending_change"}'
```

Search approved knowledge:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action": "search_knowledge", "query": "FPU"}'
```

Phân tích một đoạn text:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action": "analyze_text", "text": "So sánh FPU, NPU, NAU và NPR"}'
```

Ingest nội dung file text:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "ingest_document",
    "title": "Growth metric handbook",
    "text": "FPU là user có first payment."
  }'
```

Nếu term trong file là knowledge mới, agent ghi thẳng vào KB. Nếu term đã tồn tại, agent tạo pending change để reviewer duyệt.

Flow B - hỏi câu hỏi data:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "ask_data_question",
    "question": "RPU tháng 6 theo campaign là bao nhiêu?",
    "user_id": "quynh"
  }'
```

Khi chưa có đủ mapping bảng/cột, response sẽ là `needs_dictionary` hoặc `needs_knowledge` kèm danh sách context còn thiếu. Khi đủ Domain Knowledge và Data Dictionary, agent trả `sql_draft`. Nếu có Question Example phù hợp, SQL draft ưu tiên dùng example đã approved.

Thêm Data Dictionary:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "add_data_dictionary",
    "table": "payments",
    "description": "Bảng giao dịch thanh toán",
    "columns": [
      {
        "name": "amount",
        "business_meaning": "Doanh thu thanh toán",
        "data_type": "numeric",
        "aliases": ["revenue", "gmv", "payment amount"]
      },
      {
        "name": "user_id",
        "business_meaning": "User phát sinh giao dịch",
        "data_type": "text",
        "aliases": ["user", "active user"]
      }
    ],
    "owner": "data-team"
  }'
```

Search Data Dictionary:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action": "search_data_dictionary", "query": "gmv"}'
```

Thêm Question Example:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "add_question_example",
    "question": "RPU theo campaign",
    "sql": "SELECT campaign_name, SUM(amount) / COUNT(DISTINCT user_id) AS rpu FROM mart_rpu GROUP BY campaign_name;",
    "explanation": "Mẫu approved cho RPU theo campaign",
    "concepts": ["RPU", "campaign"],
    "used_tables": ["mart_rpu"],
    "owner": "BI"
  }'
```

Search Question Examples:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action": "search_question_examples", "query": "RPU campaign"}'
```

## Test

```bash
python -m unittest discover -s tests -v
```

## Triển Khai

Sử dụng `/agentbase-deploy` khi sẵn sàng build, push, và triển khai Custom Agent này lên AgentBase Runtime.

Phase này vẫn dùng JSON/JSONL local. Database, vector search, AgentBase Memory, và mapping xuống Data Platform được để cho phase sau.
