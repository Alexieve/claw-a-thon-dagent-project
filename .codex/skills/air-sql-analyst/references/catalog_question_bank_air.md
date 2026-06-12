---
name: catalog-question-bank-air
description: "Bộ 66 câu hỏi/view khả thi từ search_air + payment_air, chia 4 level — mỗi view full spec 7-slot, sẵn sàng chạy query hoặc promote lên dashboard. #43–66 merge từ Manager View (extended)"
metadata:
  type: reference
---

# Question Bank: Air/OTA Views — chia theo Level

> Sinh từ `data_dictionary_air.xlsx` + `ref_zlp_metric_definitions.md`. Spec mỗi view theo template 7-slot của [[rules-effective-data-request]] (A2). View đánh dấu ✅ = đã có trên 2 dashboard baseline (catalog A4). Bản mở rộng góc Sales Manager (100 câu): [[catalog-question-bank-air-extended]].
>
> **Coverage để chọn time range:** `search_air` 01/11/2025–28/02/2026. `payment_air` gồm 2 giai đoạn: T12/2024–T1/2025 và T12/2025–T2/2026 (so YoY Tết). Join 2 bảng chỉ dùng giai đoạn trùng (T12/2025–T2/2026).
>
> **Lưu ý version:** dictionary mới nhất xác nhận `reqDate`, `day_diff`, `user_search_group` **ĐÃ FIX** — dùng trực tiếp (mục 4 của rules_biz_request viết trước khi fix). Riêng `day_diff = −1` / group `Unknown` (75 dòng) vẫn loại khi phân tích.

---

## LEVEL 1 — Mô tả & lookup (1 bảng, query thẳng)

### 1A. Demand — nguồn `search_air`

| # | Câu hỏi | Metric (đơn vị đếm) | Time column | Grain | Filter/Note |
|---|---------|--------------------|-------------|-------|-------------|
| 1 | Mỗi ngày bao nhiêu người tìm vé? ✅ | unique searcher | `search_date` | daily | — |
| 2 | Nhu cầu bay dồn vào ngày nào? ✅ | unique searcher | `departure_date` | daily | demand curve forward-looking |
| 3 | User search giờ nào trong ngày? ✅ | lượt search | hour(`activity_time`) | 0–23h | — |
| 4 | Search rơi vào thứ nào? ✅ | lượt search | `search_day_in_week` | weekday | — |
| 5 | Muốn bay vào thứ nào? ✅ | lượt search | `departure_day_in_week` | weekday | — |
| 6 | Top route được tìm nhiều nhất? ✅ | unique searcher (+ % share) | range `search_date` | route tách chiều | hỏi biz: top N? gộp 2 chiều? |
| 7 | Top điểm đến hot? ✅ | unique searcher | range `search_date` | `dest` | dest có 440 code, gồm intl |
| 8 | Tỷ lệ tìm 1 chiều vs khứ hồi? | % lượt search | range `search_date` | `trip_type` | One-way ~83% baseline |
| 9 | User định đặt sớm hay sát ngày? | lượt search (% theo bucket) | range `search_date` | `user_search_group` | loại 75 dòng Unknown |

### 1B. Thực mua — nguồn `payment_air`

| # | Câu hỏi | Metric (đơn vị đếm) | Time column | Grain | Filter/Note |
|---|---------|--------------------|-------------|-------|-------------|
| 10 | Mỗi ngày bao nhiêu đơn / khách mua? ✅ | transaction; unique paying user | date(`reqDate`) | daily × provider | — |
| 11 | TPV theo ngày/tháng? | TPV = SUM(amount) | date(`reqDate`) | daily/monthly | gross, chưa có refund |
| 12 | Đơn dồn vào ngày bay nào? ✅ | transaction | `flight_date` | daily | — |
| 13 | Mua vé giờ nào, thứ nào? ✅ | transaction | hour(`reqDate`) / weekday | hour / weekday × provider | — |
| 14 | Top route thực mua? ✅ | transaction + paying user (+ % share) | range `reqDate` | route tách chiều | — |
| 15 | Thị phần các hãng/provider? | transaction / TPV (% share) | range `reqDate` | `appID`×`appUser` | ⚠ EnViet = third party gom Bamboo/Vietravel/Sun PQ → "theo hãng" ≠ "theo appUser", hỏi biz cắt theo gì |
| 16 | Domestic vs International chiếm bao nhiêu? | transaction / TPV | range `reqDate` | `flight_type` | DOM ~97% |
| 17 | Mua 1 chiều hay khứ hồi? | transaction (% share) | range `reqDate` | `round_type` | **bắt buộc UPPER()** trước khi group (lẫn case ở data T12/2024–T1/2025) |
| 18 | Khách mua sớm hay sát ngày bay? | transaction (% theo bucket) | range `reqDate` | `booking_window_group` | bucket chuẩn: Same day → >60 days |

### 1C. Bổ sung từ Manager View (E# = số câu trong [[catalog-question-bank-air-extended]])

| # | Câu hỏi | Metric (đơn vị đếm) | Time column | Grain | Filter/Note |
|---|---------|--------------------|-------------|-------|-------------|
| 43 | Hôm nay/tháng này so hôm qua/tháng trước tăng giảm bao nhiêu %? (E4, E5, E10) | % change transaction & TPV | date(`reqDate`) | D vs D-1; M vs M-1 | growth snapshot |
| 44 | Rank hãng theo doanh số: top/bottom, ai có nguy cơ bị loại? (E11–15, E18) | transaction + TPV, top 3 / bottom 3 | range `reqDate` | hãng | ⚠ EnViet third party gom nhiều hãng — chốt grain hãng vs appUser với biz |
| 45 | Khứ hồi chiếm bao nhiêu % TPV? (E22) | % TPV | range `reqDate` | UPPER(`round_type`) | gốc #17 mới có % transaction |
| 46 | DOM/INTL × 1 chiều/khứ hồi — combo nào bán nhiều nhất? (E23–24) | transaction | range `reqDate` | `flight_type` × UPPER(`round_type`) | — |
| 47 | Điểm khởi hành nào có khách mua nhiều nhất? (E42) | transaction | range `reqDate` | `origin` | gốc #7 mới có top dest |
| 48 | Top khách chi tiêu nhiều nhất? (E35) | TPV per userID, top N | range `reqDate` | userID | VIP list; chốt N với biz |

---

## LEVEL 2 — Phân tích sâu 1 bảng (cắt chéo dimension, metric dẫn xuất)

| # | Câu hỏi | Spec | Note |
|---|---------|------|------|
| 19 | Giá trị đơn trung bình (AOV) theo tháng / hãng / route / DOM-INTL? | AOV = TPV/transaction, `payment_air`, theo month(`reqDate`), grain = dimension chọn | AOV per **đơn**, không phải per vé (thiếu ticket_num → không tính được ATP) và không dùng cho góc per-user |
| 20 | Phân phối giá trị đơn? Đơn to bất thường? | histogram/percentile `amount`, `payment_air`, range `reqDate` | range 592K–48.8M; p50/p90/p99 + outlier review |
| 21 | Booking window khác nhau thế nào giữa các route / hãng / 1 chiều–khứ hồi? | median + phân phối `booking_window`, grain route / `appUser` / UPPER(`round_type`) | RoundTrip & intl kỳ vọng đặt sớm hơn |
| 22 | Càng gần Tết hành vi đặt vé đổi ra sao? ✅ (Countdown) | transaction theo days-to-Tết, so Tết 2026 vs Tết 2025, × provider | view sẵn: Overview Countdown + theo hãng |
| 23 | Nhu cầu (search) cho từng ngày bay tương lai — ngày nào sắp "cháy"? | unique searcher theo `departure_date` × route, filter departure_date > today | đầu vào cho alert demand spike |
| 24 | 1 user search bao nhiêu lần / bao nhiêu route trước khi quyết? | AVG + phân phối lượt search và COUNT(DISTINCT route) per user_id, `search_air`, range `search_date` | 1.62M search / 125K user ≈ 13 lượt/user — xem phân phối, không chỉ mean |
| 25 | Search khứ hồi nhiều (17%) nhưng mua khứ hồi ít (6.5%) — gap ở đâu? | % trip_type (search) vs % UPPER(round_type) (payment), cùng range, cắt theo route | so sánh tỷ trọng 2 nguồn, chưa cần join user |
| 26 | Chặng quốc tế: chiều đi hay chiều về nhiều hơn? | transaction theo `in_out_bound`, filter flight_type=INTERNATIONAL | ⚠ cột 97% null — chỉ dùng trên subset 598 dòng có giá trị, khai báo rõ |
| 27 | Demand theo thành phố (gộp sân bay)? | unique searcher / transaction, grain city (map city→[airport codes]) | cần build bảng map IATA→city trước (SGN/Tân Sơn Nhất...; 1 city nhiều sân bay) |
| 28 | Route gộp 2 chiều — cặp thành phố nào lớn nhất? | transaction / searcher, grain LEAST‖GREATEST(origin,dest) | biến thể của view Route, hỏi biz trước khi đổi grain |

### Bổ sung từ Manager View

| # | Câu hỏi | Spec | Note |
|---|---------|------|------|
| 49 | Hãng / route / provider nào tăng trưởng nhanh nhất hoặc giảm mạnh nhất MoM? (E17, E50, E57–58, E87) | % MoM transaction & TPV, grain hãng / route / provider | momentum + at-risk; caveat EnViet khi grain = hãng |
| 50 | Tuyến nào bán chậm nhất, có cơ hội tăng không? (E43) | transaction bottom 3, by route | underperformer |
| 51 | Bao nhiêu % doanh số từ top N tuyến / kênh / hãng? (E45, E60, E89) | % TPV concentration, top 10 route / top 3 provider / top 5 hãng | dependency risk |
| 52 | Khách đặt sớm (>30d) vs sát ngày (<7d) chiếm bao nhiêu % doanh số? (E61–62) | % TPV theo `booking_window_group` | gốc #18 mới có % transaction |
| 53 | Nhóm booking window nào có repeat rate cao hơn? (E63) | % user ≥2 transaction, by booking_window_group | loyalty by segment |
| 54 | Kênh nào có repeat rate cao nhất? (E55) | % repeat user, by provider | loyalty by channel |
| 55 | Khách kênh nào chi tiêu nhiều nhất? (E59) | TPV per user, by provider | khai báo window = coverage |
| 56 | DOM hay INTL tăng nhanh hơn? (E75) | % MoM growth, by flight_type | market momentum |
| 57 | Trend doanh số 3 tháng T12/2025–T2/2026? (E71) | transaction + TPV monthly | ⚠ mùa Tết — đọc trend phải tách seasonality |

---

## LEVEL 3 — Join 2 bảng (demand ↔ thực mua) — request mới, không có view sẵn

> Khóa join: `search_air.user_id = payment_air.userID`. Chỉ dùng giai đoạn trùng coverage (T12/2025–T2/2026). **Không phải CR session chuẩn** (không có tracking_session_id) → luôn khai báo: match window bao nhiêu ngày, match cùng route hay chỉ cùng user.

| # | Câu hỏi | Spec | Note |
|---|---------|------|------|
| 29 | Bao nhiêu % người search rồi mua? | unique buyer / unique searcher, match user_id, window search→pay **X ngày** (đề xuất 7), range chung | đây là user-level conversion, không phải CR funnel |
| 30 | Conversion theo route — route nào search nhiều mua ít? | conversion rate per route, match cùng user **+ cùng route**, window X ngày | output: bảng route × searcher × buyer × CR%, sort CR thấp |
| 31 | Từ lần search đầu đến lúc mua mất bao lâu? | median/phân phối (min(`reqDate`) − min(`activity_time`)) per user×route | time-to-purchase; cắt theo route, booking_window_group |
| 32 | Khách search xong mua khác route không? | % buyer có route mua ∉ tập route đã search (window X ngày) | đo "đổi ý" / search hộ |
| 33 | Định đặt (day_diff lúc search) vs thực đặt (booking_window lúc mua) lệch nhau không? | so phân phối `user_search_group` (search) vs `booking_window_group` (payment) trên user đã match | cùng bucket structure, payment không có Unknown |
| 34 | Danh sách user search nhiều chưa mua (remarketing)? | user_id có ≥N lượt search route R trong X ngày, không có transaction | output list + route + lần search cuối; chốt N, X với biz |
| 35 | Searcher mua trong bao nhiêu lần mở lại? (proxy) | số ngày search distinct trước khi mua, per buyer | proxy cho session count — khai báo là proxy, không phải tracking_session_id |

### Bổ sung từ Manager View

| # | Câu hỏi | Spec | Note |
|---|---------|------|------|
| 58 | Khách search nội địa có mua quốc tế không? (E79) | % cross-market buyer, match user_id, window 7 ngày | cần map airport→DOM/INTL cho search trước |
| 59 | Buyer 1 lần có search route khác sau khi mua không? (cross-sell proxy) (E95) | % buyer 1-đơn có search route ≠ route đã mua, sau ngày mua, window 7 ngày | proxy intent — khai báo là proxy |

---

## LEVEL 4 — Lifecycle / cohort / YoY

> ⚠ N/F/R đúng định nghĩa team cần data **toàn Zalopay** (NPU) hoặc **category/sub_category khác** (FPU) — data hiện chỉ có Air. Các view dưới là bản trong-phạm-vi-Air, phải khai báo rõ caveat này khi report.

| # | Câu hỏi | Spec | Note |
|---|---------|------|------|
| 36 | Khách mua Tết 2025 có quay lại mua Tết 2026 không? | % userID giai đoạn T12/2024–T1/2025 xuất hiện lại T12/2025–T2/2026, `payment_air` | tận dụng đúng 2 giai đoạn coverage — view YoY retention đáng làm nhất |
| 37 | Trong mùa này, bao nhiêu khách mua ≥2 lần? | phân phối số transaction per userID, range `reqDate` | 20.1K trans / 12.4K user → có lớp repeat đáng kể |
| 38 | RR tháng→tháng của buyer Air? | % buyer tháng M có mua tháng M+1, grain monthly | RR trong-Air, không phải RR ZLP; chỉ chạy được trong giai đoạn liên tục T12/2025–T2/2026 |
| 39 | 1 khách Air mang về bao nhiêu trong mùa? (ARPPU) | TPV / unique paying user, **window = T12/2025–T2/2026** (khai báo rõ) | ARPPU theo life-cycle window, khác AOV |
| 40 | Phân tầng khách theo chi tiêu? | decile/tier theo TPV per userID, kèm AOV & số đơn mỗi tier | đầu vào CRM/priority segment |
| 41 | Khách mua lặp có hành vi khác khách mua 1 lần? | so booking_window, AOV, route mix giữa nhóm 1-lần vs ≥2-lần | cohort behavioral comparison |
| 42 | Buyer mới mỗi tuần (first-time trong data) trend ra sao? | COUNT userID có transaction đầu tiên trong tuần, theo week(`reqDate`) | "mới" = trong phạm vi data Air, KHÔNG phải NPU/FPU chuẩn |

### Bổ sung từ Manager View

| # | Câu hỏi | Spec | Note |
|---|---------|------|------|
| 60 | Khách VIP (top 10% spend) có repeat rate cao hơn trung bình bao nhiêu? (E68, E81) | repeat rate decile 1 vs overall, TPV per userID | tiering impact |
| 61 | Bao nhiêu % buyer mua từ ≥2 hãng? (E78) | % userID có ≥2 hãng distinct | ⚠ EnViet gom nhiều hãng → số bị méo, chốt grain trước |
| 62 | Bao nhiêu % buyer mua từ ≥2 kênh/provider? (E82) | % userID có ≥2 provider distinct | channel loyalty |
| 63 | Khách quay lại bao lâu mới mua lần 2? (E80) | median gap đơn 1 → đơn 2, per userID | coverage ~3 tháng → right-censored, khai báo rõ |
| 64 | Top tuyến: bao nhiêu % doanh số từ khách repeat? (E84) | % TPV từ buyer ≥2 đơn, by top route | route quality |
| 65 | Segment nào nên là target chính? (E99) | rank segment theo TPV/user × % MoM growth | data ra ranking; "chiến lược" đọc cùng biz |
| 66 | Scenario/sizing: thêm X khách repeat, top route giảm 10%, tối ưu last-minute, invest tuyến X? (E85, E88, E90, E93) | số học từ các view sẵn: AOV repeat × X; TPV share × 10%; size segment <7d; searcher pool × CR × AOV | ước lượng trần/thô, KHÔNG phải forecast |

---

## KHÔNG trả lời được với data hiện có — đừng nhận request

| Câu hỏi | Vì sao | Cần gì |
|---------|--------|--------|
| ATP — giá trung bình 1 vé | không có `ticket_num`/số pax per đơn | cột ticket_num trong payment |
| CR funnel chuẩn (step→step đồng-session) | không có `tracking_session_id` + event step | event log funnel (view→search→select→pay) |
| NPU/FPU đúng định nghĩa team | cần lịch sử pay toàn ZLP / category khác | bảng transaction cross-category |
| Doanh thu thực / sau refund | `amount` là TPV gross, không có refund/fee | data refund + take rate |
| Search không đăng nhập / drop trước search | data bắt đầu từ user_id đã định danh có search | traffic log phía trước |
| Giá vé thị trường / so giá hãng | amount là giá trị đơn đã mua, không phải giá niêm yết | data giá search/quote |
| Conversion search→mua theo kênh/provider | `search_air` không có cột provider → không có mẫu số theo kênh | provider/channel trong search log |
| Churn / inactive >90 ngày | coverage payment là 2 cụm Tết rời nhau, không có 90 ngày liên tục | payment liên tục ≥ 6 tháng |
| Forecast doanh thu 3–6 tháng | chỉ có ~3 tháng + seasonality Tết, không đủ train | ≥ 12 tháng data liên tục |
| Priority/ROI theo profitability (hãng/tuyến) | không có margin/take rate | data take rate / commission |
| Churn sang competitor / thị phần ngoài ZLP | không có data competitor | data thị trường ngoài ZLP |

---

## Cách dùng file này

1. Biz hỏi → tìm câu gần nhất trong bank → nếu ✅ thì chỉ thẳng view dashboard + filter, không query mới.
2. Chưa có ✅ → lấy spec làm request chuẩn 7-slot, vẫn phải chốt với biz các slot đánh dấu "hỏi biz".
3. View Level 2–4 nào bị hỏi lặp ≥3 lần → promote lên dashboard, update catalog A4 trong [[rules-effective-data-request]] và đánh ✅ tại đây.
