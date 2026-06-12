---
name: rules-biz-request-to-view-query
description: "Rule hỏi đáp khi xử lý data request Air/OTA Zalopay (search_air, payment_air) — quy trình make-sure mọi request kể cả khớp catalog, kỹ năng hỏi từ think-with-me, output SQL-only, Presto dialect. v3 2026-06-12"
metadata:
  type: reference
---

# Rules: Hỏi đáp Request → SQL (Air/OTA) — v3

> Nguyên tắc gốc: **Không bao giờ tự assume — hiểu xong mới xuất SQL.** Mọi request đều thiếu ít nhất 1 yếu tố: metric, đơn vị đếm, time range, cột thời gian, grain, scope. **Kể cả request khớp catalog/question bank cũng PHẢI make-sure** — catalog cho spec nền, không thay được việc xác nhận với user. Khi buộc phải tự chốt → ghi rõ vào `Assumption` trong header.
>
> Đi kèm: [[catalog-question-bank-air]] (42 câu hỏi/view mẫu) + `playbook_sql_air_views.md` (make-clear + SQL từng view) + [[zlp-ota-metric-definitions]] (định nghĩa metric chốt).

---

## 1. Quy trình hỏi đáp chuẩn — 6 bước (áp dụng cho MỌI request, kể cả có trong catalog)

1. **Tra trước:** request khớp view nào trong question bank / catalog dashboard → lấy spec làm nền. **Khớp catalog ≠ được bỏ qua bước 2–4** — vẫn phải restate và xác nhận từng slot, vì cùng câu chữ nhưng ý user có thể khác spec sẵn.
2. **Restate first — phát biểu lại như sắp làm thật:** trước khi hỏi gì, diễn đạt lại request thành spec hành động cụ thể để user sửa: *"Em hiểu là: đếm số ĐƠN (transaction) trên payment_air, mua trong 01–31/01/2026 theo reqDate, route tách chiều, chỉ nội địa — đúng không chị?"* Sửa-một-bản-sai chính xác hơn mô-tả-từ-đầu. Chưa được confirm thì chưa đi tiếp.
3. **Make-clear:** hỏi các slot còn thiếu theo checklist mục 2, theo cách hỏi ở mục 3. Mỗi câu hỏi **luôn kèm phương án đề xuất + lý do**.
4. **Confirm & close:** chốt lại spec cuối (đúng format header mục 6) trước khi viết SQL. Còn slot nào user chưa trả lời rõ → hỏi lại đúng slot đó, không tự đoán.
5. **Xuất SQL kèm header khai báo.** **CHỈ xuất câu SQL — không chạy, không trả số liệu.** Trang tự chạy trên Superset (Presto/Trino). Dưới SQL nhắc 1–2 assumption rủi ro nhất + cách đổi query nếu user hiểu khác.
6. **Học từ lỗi:** user sửa/báo lỗi → update rule này hoặc playbook ngay, không đợi lặp lại.

---

## 2. Checklist make-clear — 6 nhóm bắt buộc

| # | Nhóm | Phải làm rõ | Vì sao |
|---|------|-------------|--------|
| 1 | **Đơn vị đếm** | transaction / paying user (unique) / lượt search / unique searcher / TPV? | 20.129 giao dịch nhưng chỉ 12.386 user — top theo transaction ≠ top theo user |
| 2 | **⚠ TIME RANGE + CỘT THỜI GIAN** | Range từ ngày nào đến ngày nào? Áp cho **cột nào**: ngày mua `reqDate` / ngày bay `flight_date` / ngày search `search_date` / ngày muốn bay `departure_date`? **Các cột thời gian còn lại có cần constraint không?** | **PHẢI HỎI KỂ CẢ KHI REQUEST ĐÃ CÓ SẴN NGÀY.** "Bay 10/2" vẫn phải hỏi: có giới hạn ngày mua không? Mỗi bảng có ≥2 cột thời gian, chọn sai là sai toàn bộ |
| 3 | **Top N & tiêu chí rank** | Top bao nhiêu? Rank theo metric nào? Cần % share không? | "Phổ biến nhất" không phải con số |
| 4 | **Grain dimension** | Route tách chiều / gộp 2 chiều / theo city (1 city nhiều sân bay)? "Cùng chuyến" = cùng route hay cùng route + ngày bay? | Đổi grain là đổi hẳn kết quả |
| 5 | **Scope/filter** | Domestic/Intl? One-way/Round-trip? Hãng nào? | DOM ~97% nhưng intl khác hẳn về AOV, booking window |
| 6 | **Nguồn** | Demand (`search_air`) hay thực mua (`payment_air`)? So sánh 2 phía = join, là request riêng | 2 bảng kể 2 câu chuyện khác nhau |

**Từ khóa mơ hồ phải quy đổi trước khi viết SQL:** *phổ biến, bán chạy, nhiều, khách, doanh thu, giá trung bình, tỷ lệ chuyển đổi, quay lại, tháng X* — tra bảng dịch trong playbook hoặc hỏi thẳng.

---

## 3. Cách hỏi user — kỹ năng từ /think-with-me

### 3.1. Chọn chế độ hỏi theo loại request

| Loại request | Chế độ | Cách làm |
|--------------|--------|----------|
| **Rõ ràng / lookup** ("top 10 route tháng 1") | Gộp trắc nghiệm | Restate → gom slot thiếu vào **1 lượt, tối đa 4 câu trắc nghiệm**, mỗi câu có option đề xuất (Recommended) + lý do |
| **Mơ hồ / mở** ("phân tích xem Tết bán ổn không", "nghĩ xem nên xem gì") | Think-with-me | Restate → hỏi **từng câu một**, không nhồi option vào câu chữ, mỗi câu kèm đề xuất + why, đợi trả lời rồi mới hỏi tiếp. Hiểu xong mới đề xuất view/SQL — **không advise giữa chừng** |

- Request tiếp nối ngữ cảnh cũ ("top 10 chặng" ngay sau câu trước) → kế thừa slot đã chốt, chỉ hỏi slot mới, ghi rõ "tiếp nối câu trước" trong Assumption.
- User trả lời "Other/Range khác" mà chưa ghi cụ thể → hỏi tiếp **đúng 1 câu đó**, không tự đoán.
- Câu nào tự trả lời được bằng cách đọc data dictionary / file trong folder → tự đọc, đừng hỏi user.

### 3.2. Mài sắc từ ngữ mơ hồ (sharpen fuzzy language)

User dùng từ rộng → gọi tên ra và đề xuất 1 cách hiểu chính xác để user chốt:

| User nói | Hỏi lại để mài sắc |
|----------|--------------------|
| "phổ biến / bán chạy / hot" | Theo transaction, paying user, hay lượt search? Demand hay thực mua? |
| "khách / user" | Mỗi khách đếm 1 lần (unique) hay đếm theo lượt? Window nào? |
| "doanh thu / bán được" | TPV (tổng tiền) hay số đơn? Gross — chưa trừ refund, chấp nhận không? |
| "giá vé trung bình" | Per đơn (AOV) hay per vé (ATP — không tính được, thiếu ticket_num)? |
| "cùng 1 chuyến" | Cùng route, hay cùng route + cùng ngày bay? |
| "trên X lần" | ≥ X hay > X? |
| "tháng X / Tết này" | Theo ngày mua, ngày bay, hay ngày search? Từ ngày nào đến ngày nào? |
| "tăng/giảm/tốt hơn" | So với baseline nào? Đo bằng metric gì? |
| "phân tích / xem thử" | Muốn ra quyết định gì từ số này? Ai đọc kết quả? |

### 3.3. Stress-test bằng kịch bản cụ thể (probe with scenarios)

Slot đã chốt rồi vẫn thử biên bằng 1 case cụ thể — sai biên là sai số:

- "Vé khứ hồi là 1 transaction — chị muốn đếm 1 hay tách 2 chiều?"
- "User search SGN-HAN nhưng mua HAN-SGN — tính là 'mua route đã search' không?"
- "Giao dịch lúc 23:59 ngày 28/02 có nằm trong 'tháng 2' của chị không?" (filter timestamp nửa-mở)
- "VNA bay quốc tế về HAN — có nằm trong 'VNA đi Hà Nội' không?"
- "User search 1/1 nhưng mua 15/3 (ngoài coverage) — chấp nhận rớt khỏi join?"

### 3.4. Các nguyên tắc hỏi còn lại

- **Đừng chấp nhận "tùy / it depends":** chốt case mặc định (80% trường hợp) trước, exception liệt kê sau.
- **Hỏi bằng ví dụ, không hỏi trừu tượng:** "Có bảng số/report cũ nào đúng format chị muốn không?" — 1 ví dụ thật hơn 5 câu mô tả.
- **Probe the implicit:** "Số này lần trước có ai tính sai/lệch vì gì chưa?", "Có ngoại lệ nào mọi người hay quên không?" — user biết gotcha nhưng không tự khai.
- **Quy ước ngôn ngữ: từ thân thuộc đi trước, thuật ngữ kèm trong ngoặc** — vừa dễ hiểu vừa giữ chính xác để đối chiếu SQL/dashboard: "số đơn (transaction)", "số khách — mỗi khách đếm 1 lần (unique paying user)", "tổng tiền (TPV)", "đặt trước ngày bay bao lâu (booking window)", "lượt tìm (search)", "chặng (route)", "tỷ lệ mua sau khi tìm (conversion)". Áp dụng cho cả câu hỏi make-clear lẫn header khai báo. User dùng từ nào thì mirror từ đó.
- Metric đặc thù phải hỏi thêm theo [[zlp-ota-metric-definitions]]: **CR** (step đầu→cuối nào), **RR** (period M→M / W→W), **AOV vs ATP vs ARPPU** (per đơn / per vé / per user + window), **N/F/R** (category hay sub_category — data hiện tại chỉ trong-Air, không tính được NPU/FPU chuẩn).

### 3.5. Red flags — đang làm sai nếu thấy mình…

| Suy nghĩ trong đầu | Vấn đề |
|--------------------|--------|
| "Câu này có trong catalog rồi, xuất luôn" | Catalog cho spec nền — vẫn phải restate + confirm slot |
| "Chắc ý chị ấy là ngày bay" | Đừng assume cột thời gian — checklist #2, đã bị nhắc 1 lần |
| "Để em giải thích cách tính trước đã…" | Hỏi xong hiểu đã, đừng advise giữa chừng |
| "Em đưa 3 phương án chị chọn nhé" (khi chưa hiểu goal) | Chưa hiểu thì chưa được đề xuất |
| "Hỏi thế đủ rồi, range chắc là full coverage" | Slot chưa được confirm = chưa đủ |
| "Số ra đẹp đấy, gửi luôn" | Số đẹp/xấu bất thường → soát checklist mục 7 trước |

---

## 4. Quy tắc kỹ thuật khi viết SQL (Presto/Trino)

**Ngày tháng — lỗi nhiều nhất, convert tất cả về đúng time format:**
1. Literal luôn `DATE '2026-01-01'` / `TIMESTAMP '...'` — string trần sẽ lỗi `Cannot check if date is BETWEEN varchar`.
2. Cột DATE (`search_date`, `flight_date`, `departure_date`): `BETWEEN DATE '...' AND DATE '...'`.
3. Cột TIMESTAMP (`reqDate`, `activity_time`) filter theo ngày: nửa-mở `>= DATE a AND < DATE b + INTERVAL '1' DAY`.
4. Interval: `INTERVAL '7' DAY` (số trong quote). Hiệu thời gian: `date_diff('day', t1, t2)` — không trừ trực tiếp.
5. Grain: `date_trunc('month'|'week', col)`; lấy ngày: `date(col)`; thứ: `format_datetime(col, 'EEEE')`.

**Presto khác:** percentile → `approx_percentile(col, 0.5)`; chia tiền → `CAST(SUM(amount) AS DOUBLE) / ...` (tránh chia nguyên).

**Data quirks (theo dictionary mới nhất — reqDate, day_diff, user_search_group ĐÃ FIX, dùng trực tiếp):**
- `round_type` lẫn case → luôn `UPPER()` khi group/filter/join với `trip_type`.
- Loại `user_search_group = 'Unknown'` (day_diff = −1) khi phân tích booking intent.
- `in_out_bound` 97% null — chỉ dùng trên subset INTERNATIONAL có giá trị, khai báo rõ.
- Lọc hãng bằng `appID` (3568/3569=VNA, 612/678=Vietjet, 606/677=Bamboo, 4096/4341=EnViet, 69/2643=Gotadi; chẵn lẻ DOM/INTL theo dictionary) — KHÔNG lọc bằng `appUser` (tên dùng chung DOM/INTL). EnViet = third party gom Bamboo/Vietravel/Sun PQ → "theo hãng" ≠ "theo provider", hỏi biz.
- Đếm: transaction = `COUNT(transID)`; user = `COUNT(DISTINCT userID/user_id)`. `appTransID` không dùng.
- City → airport: map đầy đủ (HAN=Hà Nội, SGN=TP.HCM...; 1 city có thể nhiều sân bay). Gộp 2 chiều: `least(origin,dest) || '-' || greatest(origin,dest)`.
- **Coverage:** search `2025-11-01→2026-02-28`; payment `2024-12-01→2025-01-31` + `2025-12-01→2026-02-28`. **Join 2 bảng chỉ dùng `2025-12-01→2026-02-28`.** Join là conversion user-level (khai báo match window + grain), KHÔNG phải CR session.

---

## 5. Metric — luôn dùng bản chốt của team

Theo [[zlp-ota-metric-definitions]], override mọi định nghĩa generic. Bẫy nhanh: AOV = TPV/transaction (per đơn, không dùng per-user); ARPPU phải khai báo window; ATP **không tính được** (thiếu ticket_num); CR phải khai báo step + đồng-session; RR phải hỏi period; N/F/R phải hỏi category/sub_category và data hiện tại chỉ cho bản trong-Air.

---

## 6. Template header — comment đầu mọi câu SQL xuất ra

```
-- Metric: <tên + định nghĩa ngắn>
-- Đơn vị đếm: <transaction / unique user / TPV / lượt search>
-- Thời gian: <range> theo cột <reqDate / search_date / flight_date / departure_date> (+ constraint cột thời gian khác nếu có)
-- Grain: <route tách chiều / city-pair / user / ...>
-- Filter: <domestic only, appID, ...>
-- Match rule (nếu join): <window X ngày, cùng user / cùng user+route, anchor>
-- Assumption: <những gì tự chốt thay user>
```

Dưới SQL: nhắc 1–2 điểm user cần check (assumption rủi ro nhất, cách đổi query nếu hiểu khác).

---

## 7. Lỗi đã gặp thực tế — check đầu tiên khi user báo sai

1. Literal ngày thiếu `DATE '...'` → lỗi varchar (gặp 2026-06-12).
2. Tự assume cột thời gian / bỏ qua range cột thời gian thứ hai khi request có sẵn 1 ngày (bị nhắc 2026-06-12) → checklist #2.
3. Quên `UPPER(round_type)` → ra 4 nhóm thay vì 2.
4. Lẫn giai đoạn T12/2024–T1/2025 vào query join (không có search tương ứng).
5. Quên loại `Unknown` trong user_search_group.
6. Chia nguyên thiếu `CAST AS DOUBLE` → AOV/ARPPU bị cắt thập phân.
7. Lọc hãng bằng `appUser` thay vì `appID`.
