Mình sẽ làm Flow B theo hướng **bootstrap trước, không cần có sẵn data dictionary hay question examples**. Agent sẽ biết trả lời “thiếu context gì” thay vì bịa SQL, đồng thời có API để bạn bổ sung dần dictionary/examples từ câu hỏi thật.

**Plan Phase 4**
Implement action chính: `ask_data_question`

Input:

```json
{
  "action": "ask_data_question",
  "question": "RPU tháng 6 theo campaign là bao nhiêu?",
  "user_id": "quynh",
  "session_id": "optional"
}
```

Agent xử lý:

1. Extract concepts từ câu hỏi
   - Ví dụ: `RPU`, `tháng 6`, `campaign`
   - Dùng LLM nếu có env, fallback deterministic đơn giản

2. Search `Domain Knowledge`
   - Dùng KB hiện tại: `search_knowledge`
   - Nếu biết `RPU`, lấy definition/logic/formula/paraphrases

3. Search `Data Dictionary`
   - Nếu chưa có dictionary, trả thiếu mapping bảng/cột
   - Ví dụ: `campaign` chưa biết nằm ở bảng/cột nào

4. Search `Question Examples`
   - Nếu chưa có examples, vẫn chạy được
   - Examples chỉ giúp sinh SQL tốt hơn, không bắt buộc

5. Quyết định response
   - Nếu thiếu bảng/cột: trả `needs_dictionary`
   - Nếu thiếu định nghĩa nghiệp vụ: trả `needs_knowledge`
   - Nếu đủ context: trả `sql_draft`
   - Nếu câu hỏi mơ hồ: trả `needs_clarification`

Response khi chưa có dictionary:

```json
{
  "status": "needs_dictionary",
  "question": "RPU tháng 6 theo campaign là bao nhiêu?",
  "detected_concepts": ["RPU", "campaign"],
  "known_knowledge": [
    {
      "name": "RPU",
      "definition": "Revenue Per User..."
    }
  ],
  "missing": [
    {
      "type": "column_mapping",
      "concept": "campaign",
      "question": "campaign nằm ở bảng/cột nào?"
    },
    {
      "type": "table_mapping",
      "concept": "revenue/user/payment",
      "question": "RPU nên lấy revenue và user từ bảng nào?"
    }
  ],
  "answer": "Tôi đã biết RPU là gì, nhưng chưa đủ data dictionary để sinh SQL."
}
```

Response khi đủ context:

```json
{
  "status": "sql_draft",
  "sql": "SELECT ...",
  "explanation": [
    "RPU lấy từ Domain Knowledge",
    "revenue map từ payments.amount",
    "campaign map từ campaigns.campaign_name"
  ],
  "used_knowledge_ids": ["kn_xxx"],
  "used_dictionary_ids": ["dict_xxx"],
  "used_example_ids": []
}
```

**Plan Phase 5**
Thêm lớp `Data Dictionary` và `Question Examples`, nhưng cho phép trống ban đầu.

API mới cho dictionary:

```text
add_data_dictionary
search_data_dictionary
list_data_dictionary
```

Schema dictionary:

```json
{
  "id": "dict_xxx",
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
      "name": "paid_at",
      "business_meaning": "Thời điểm thanh toán",
      "data_type": "timestamp",
      "aliases": ["payment date", "ngày thanh toán"]
    }
  ],
  "relationships": [
    {
      "from": "payments.user_id",
      "to": "users.id",
      "type": "many_to_one"
    }
  ],
  "owner": "data-team",
  "status": "approved"
}
```

API mới cho question examples:

```text
add_question_example
search_question_examples
list_question_examples
```

Schema example:

```json
{
  "id": "qex_xxx",
  "question": "RPU theo tháng",
  "sql": "SELECT ...",
  "explanation": "Tính revenue / active users theo tháng",
  "concepts": ["RPU", "month"],
  "used_tables": ["payments", "users"],
  "owner": "BI",
  "status": "approved"
}
```

**Thứ Tự Implement**
1. Thêm storage cho `data_dictionary` và `question_examples`
   - Với Postgres: thêm tables vào `db/schema.sql`
   - Với JSON fallback: thêm file local tương ứng

2. Thêm CRUD/search APIs cho dictionary/examples
   - Trước mắt chỉ cần add/search/list
   - Chưa cần approval phức tạp như Domain Knowledge

3. Thêm `ask_data_question`
   - Không sinh SQL nếu thiếu dictionary
   - Trả missing context rõ ràng để user biết cần bổ sung gì

4. Thêm SQL draft generator
   - Chỉ chạy khi có đủ domain knowledge + dictionary
   - Dùng LLM nếu có env
   - Prompt bắt buộc chỉ dùng context retrieved, không tự bịa bảng/cột

5. Thêm test
   - Không có dictionary -> `needs_dictionary`
   - Có KB nhưng thiếu column -> `needs_dictionary`
   - Có dictionary đủ -> `sql_draft`
   - Có example gần giống -> response include `used_example_ids`
   - Search dictionary theo alias hoạt động

6. Update README
   - Thêm curl examples cho:
     - `ask_data_question`
     - `add_data_dictionary`
     - `add_question_example`

7. Deploy lại
   - build image
   - push registry
   - update runtime
   - test endpoint deployed

**Ưu tiên thực tế**
Làm trước bản MVP như này:

```text
ask_data_question
add_data_dictionary
search_data_dictionary
add_question_example
search_question_examples
```

Trong MVP, `ask_data_question` chủ yếu giúp bạn biết **thiếu dictionary gì**. Sau khi bạn bổ sung vài mapping bảng/cột thật, mình mới siết tiếp phần sinh SQL. Đây là đường đi ổn nhất khi hiện tại bạn chưa có sẵn bộ mẫu và dictionary.