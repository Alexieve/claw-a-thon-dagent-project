# business-knowledge-learning-agent

Agent GreenNode AgentBase giúp team nghiệp vụ thu thập, parse, review, và chuẩn hóa knowledge từ stakeholder hoặc file cứng.

## Agent Này Làm Gì

- Nhận đoạn văn tự do từ stakeholder và lưu nguyên văn thành raw event.
- Parse đoạn văn thành knowledge candidates như metric, term, dimension, business rule, hoặc synonym.
- Cho reviewer approve/reject/edit candidate trước khi ghi vào knowledge base chuẩn.
- Phát hiện conflict khi candidate mới có cùng tên nhưng định nghĩa khác approved knowledge.
- Ingest nội dung file dạng text/pasted text và đưa qua cùng pipeline candidate review.
- Phân tích một đoạn text để chỉ ra knowledge đã biết, đang chờ duyệt, đang conflict, hoặc còn thiếu.

## Cấu Trúc Dự Án

- `main.py` - Điểm vào AgentBase và định tuyến action mới.
- `knowledge_store.py` - Storage local, parser, review workflow, conflict detection.
- `data/raw_events.jsonl` - Append-only log lưu nguyên văn input.
- `data/knowledge_candidates.json` - Candidate knowledge chờ review hoặc đã xử lý.
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

LLM extraction là optional. Nếu không cấu hình `LLM_API_KEY`, `LLM_BASE_URL`, và `LLM_MODEL`, agent sẽ dùng deterministic fallback parser.

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

## API Examples

Dạy agent bằng đoạn văn:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "teach_text",
    "text": "FPU là user có first payment. Team Growth hay gọi là paid user đầu tiên.",
    "stakeholder": "Linh",
    "team": "Growth"
  }'
```

Approve candidate:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "review_candidate",
    "candidate_id": "cand_xxx",
    "decision": "approve"
  }'
```

Approve candidate sau khi sửa:

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

Liệt kê candidate:

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action": "list_candidates", "status": "pending_review"}'
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

## Test

```bash
python -m unittest discover -s tests -v
```

## Triển Khai

Sử dụng `/agentbase-deploy` khi sẵn sàng build, push, và triển khai Custom Agent này lên AgentBase Runtime.

Phase này vẫn dùng JSON/JSONL local. Database, vector search, AgentBase Memory, và mapping xuống Data Platform được để cho phase sau.
