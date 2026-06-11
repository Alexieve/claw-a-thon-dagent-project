# business-knowledge-learning-agent

Agent GreenNode AgentBase giúp team nghiệp vụ thu thập, parse, review, và chuẩn hóa knowledge từ stakeholder hoặc file cứng.

## Agent Này Làm Gì

- Hỗ trợ Flow A teaching nhiều lượt: user dạy, agent tóm tắt, user confirm rồi mới commit.
- Knowledge mới sau khi confirm được ghi thẳng vào knowledge base chuẩn.
- Knowledge đã tồn tại luôn tạo pending change để reviewer approve/reject trước khi cập nhật.
- Owner gốc của knowledge không bị ghi đè khi có thay đổi từ người khác.
- Ingest nội dung file dạng text/pasted text theo cùng policy: mới thì commit, existing thì pending change.
- Search approved knowledge bằng LLM rerank nếu cấu hình LLM, fallback deterministic nếu không.
- Phân tích một đoạn text để chỉ ra knowledge đã biết, đang chờ duyệt, đang conflict, hoặc còn thiếu.

## Cấu Trúc Dự Án

- `main.py` - Điểm vào AgentBase và định tuyến action mới.
- `knowledge_store.py` - Storage local, parser, teaching session, review workflow, KB versioning.
- `data/raw_events.jsonl` - Append-only log lưu nguyên văn input.
- `data/teaching_sessions.json` - Session teaching nhiều lượt trước khi user confirm.
- `data/knowledge_candidates.json` - Pending change hoặc candidate cũ cần review.
- `data/knowledge_base.json` - Approved knowledge chuẩn.
- `data/document_chunks.jsonl` - Chunk text từ file cứng.
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

LLM là optional. Nếu có `LLM_API_KEY`, `LLM_BASE_URL`, và `LLM_MODEL`, agent dùng LLM cho parse/summarize và rerank search. Nếu không, agent dùng deterministic fallback parser/search.

Storage mặc định là JSON local trong `data/`. Để dùng Supabase/Postgres, cấu hình:

```bash
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require
```

Khi `DATABASE_URL` tồn tại, agent tự chạy migration trong `db/schema.sql` lúc boot và dùng Postgres cho KB, pending change, teaching session, raw event, document chunk.

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

## Test

```bash
python -m unittest discover -s tests -v
```

## Triển Khai

Sử dụng `/agentbase-deploy` khi sẵn sàng build, push, và triển khai Custom Agent này lên AgentBase Runtime.

Phase này vẫn dùng JSON/JSONL local. Database, vector search, AgentBase Memory, và mapping xuống Data Platform được để cho phase sau.
