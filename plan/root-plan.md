Dưới đây là plan implement theo đúng mô hình Flow A/Flow B trong hình, nhưng chia phase để có thể làm được chắc chắn trên code hiện tại.

**Mục Tiêu**

Chuyển agent từ kiểu API đơn lẻ `teach_text -> candidate -> approve` sang 2 flow rõ ràng:

```text
Flow A: Teaching nhiều lượt -> user confirm -> commit KB hoặc pending change
Flow B: User hỏi nghiệp vụ -> truy KB/dictionary/example -> sinh SQL hoặc hỏi thêm
```

Tôi sẽ implement theo hướng JSON/local storage trước, vì project hiện tại đang dùng `data/*.json`. AgentBase Memory có thể thêm sau nếu muốn persist conversation theo platform service.

**Phase 1: Chuẩn Hóa Data Model**

Tôi sẽ thêm các store/file rõ hơn:

```text
data/teaching_sessions.json
data/knowledge_base.json
data/knowledge_candidates.json
data/data_dictionary.json
data/question_examples.json
```

Schema chính:

`teaching_session`

```json
{
  "id": "teach_xxx",
  "status": "clarifying",
  "messages": [],
  "draft": {},
  "created_by": "QuynhVM",
  "team": "Growth",
  "created_at": "...",
  "updated_at": "..."
}
```

`knowledge_base`

```json
{
  "id": "kn_xxx",
  "name": "FPU",
  "canonical_definition": "User có first payment trong kỳ phân tích.",
  "logic": "first_payment_date nằm trong kỳ phân tích",
  "examples": [],
  "paraphrases": [],
  "formula": null,
  "conditions": [],
  "domain": "Growth",
  "owner": "QuynhVM",
  "created_by": "QuynhVM",
  "version": 1,
  "status": "approved",
  "change_history": []
}
```

`pending_change`

```json
{
  "id": "cand_xxx",
  "status": "pending_change",
  "target_knowledge_id": "kn_xxx",
  "proposed_by": "Linh",
  "before": {},
  "after": {},
  "change_summary": "Cập nhật definition và thêm ví dụ"
}
```

Rule quan trọng:

- Knowledge mới sau confirm -> ghi thẳng KB.
- Knowledge đã tồn tại -> tạo `pending_change`.
- `owner` gốc không bị overwrite.
- Approve change -> update KB, tăng `version`, ghi `change_history`.

**Phase 2: Implement Flow A Teaching**

Tôi sẽ thêm các action mới trong `main.py`:

```text
start_teach_session
append_teach_message
summarize_teach_session
confirm_teach_session
cancel_teach_session
```

Flow chi tiết:

1. `start_teach_session`

Input:

```json
{
  "action": "start_teach_session",
  "message": "FPU là user có first payment...",
  "stakeholder": "QuynhVM",
  "team": "Growth"
}
```

Agent làm:

- Tạo session.
- Lưu message đầu tiên.
- Parse draft knowledge sơ bộ.
- Kiểm tra KB đã có term chưa.
- Trả câu hỏi làm rõ nếu thiếu thông tin.

Response:

```json
{
  "session_id": "teach_xxx",
  "status": "clarifying",
  "draft": {},
  "question": "FPU được tính theo first payment trong kỳ hay first payment lifetime?"
}
```

2. `append_teach_message`

Input:

```json
{
  "action": "append_teach_message",
  "session_id": "teach_xxx",
  "message": "Tính theo first payment lifetime, nhưng report theo tháng phát sinh first payment."
}
```

Agent làm:

- Append message.
- Rebuild draft từ toàn bộ session.
- Nếu đủ rõ thì chuyển `awaiting_confirmation`.

3. `summarize_teach_session`

Cho phép user yêu cầu agent tóm tắt bất kỳ lúc nào.

Response:

```json
{
  "status": "awaiting_confirmation",
  "summary": {
    "term": "FPU",
    "definition": "...",
    "logic": "...",
    "examples": [],
    "paraphrases": []
  }
}
```

4. `confirm_teach_session`

Input:

```json
{
  "action": "confirm_teach_session",
  "session_id": "teach_xxx",
  "decision": "confirm"
}
```

Agent làm:

- Nếu term mới: commit thẳng KB.
- Nếu term đã có: tạo `pending_change`.
- Mark session `committed` hoặc `pending_approval`.

**Phase 3: Sửa Review Flow**

`review_candidate` sẽ hỗ trợ 2 loại:

```text
pending_review: backward-compatible với flow cũ
pending_change: flow mới cho existing knowledge
```

Approve `pending_change`:

- Load KB hiện tại.
- Ghi snapshot cũ vào `change_history`.
- Apply field mới từ `after`.
- Giữ nguyên `owner`.
- Tăng `version`.
- Mark candidate `approved`.

Reject `pending_change`:

- Mark candidate `rejected`.
- KB không đổi.

**Phase 4: Implement Flow B Serving MVP**

Tôi sẽ thêm action:

```text
ask_data_question
```

Input:

```json
{
  "action": "ask_data_question",
  "question": "ARPU tháng 6 theo campaign là bao nhiêu?"
}
```

Agent làm:

1. Extract concepts từ câu hỏi.
2. Search 3 nguồn:
   - `knowledge_base`
   - `data_dictionary`
   - `question_examples`
3. Nếu thiếu dictionary, trả `needs_dictionary`.
4. Nếu đủ mapping, sinh SQL draft và explanation.

Response khi thiếu dictionary:

```json
{
  "status": "needs_dictionary",
  "detected_concepts": ["ARPU", "campaign"],
  "known_knowledge": ["ARPU"],
  "missing": ["Không biết campaign nằm ở bảng/cột nào"]
}
```

Response khi đủ context:

```json
{
  "status": "sql_draft",
  "sql": "...",
  "explanation": [
    "ARPU lấy từ Domain Knowledge",
    "campaign map từ Data Dictionary"
  ]
}
```

Ở phase này tôi sẽ không giả vờ có data warehouse. Nếu thiếu bảng/cột, agent phải nói thiếu context thay vì bịa SQL.

**Phase 5: Thêm Data Dictionary Và Query Examples**

Tôi sẽ thêm API quản lý 2 nguồn còn lại:

```text
add_data_dictionary
search_data_dictionary
add_question_example
search_question_examples
```

Data dictionary record:

```json
{
  "table": "payments",
  "columns": [
    {
      "name": "amount",
      "business_meaning": "revenue amount",
      "data_type": "numeric"
    }
  ],
  "relationships": []
}
```

Question example:

```json
{
  "question": "ARPU theo tháng",
  "sql": "SELECT ...",
  "explanation": "..."
}
```

**Phase 6: LLM Usage Policy**

Tôi sẽ giữ policy rõ:

- Flow A parse/summarize có thể dùng LLM nếu env có `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`.
- Nếu không có LLM, dùng parser deterministic hiện tại.
- `confirm_teach_session` không phụ thuộc LLM để commit.
- `review_candidate` không dùng LLM.
- `search_knowledge` không dùng LLM.
- `ask_data_question` có thể dùng LLM để sinh SQL, nhưng chỉ sau khi retrieve đủ KB/dictionary/examples.

**Phase 7: Test**

Tôi sẽ thêm test cho các case chính:

```text
New knowledge confirm -> vào KB ngay
Existing knowledge confirm -> tạo pending_change
Approve pending_change -> update KB, giữ owner, version +1
Reject pending_change -> KB giữ nguyên
Teaching session nhiều lượt -> draft được cập nhật
Flow B thiếu dictionary -> needs_dictionary
Flow B đủ dictionary -> trả sql_draft
Search chỉ trả approved KB
```

**Phase 8: README Và API Examples**

Cập nhật README theo 2 flow:

```text
Flow A Teaching
Flow B Serving
Review pending changes
Data dictionary setup
Question examples setup
```

Thêm curl examples để test endpoint deployed.

**Phase 9: Deploy Lại**

Sau khi test pass:

1. Build image mới.
2. Push lên AgentBase CR.
3. Update runtime `dagent`.
4. Test:
   - `/health`
   - `start_teach_session`
   - `append_teach_message`
   - `confirm_teach_session`
   - `ask_data_question`

**Thứ Tự Tôi Khuyến Nghị Làm**

1. Implement Flow A + new KB policy trước.
2. Test và deploy Flow A.
3. Sau đó implement Flow B MVP với `needs_dictionary`.
4. Cuối cùng mới thêm SQL generation đầy đủ.

Lý do: Flow A là nền để tạo `Domain Knowledge` chuẩn. Nếu chưa có KB policy ổn, Flow B sinh SQL sẽ dễ dựa vào tri thức chưa sạch.