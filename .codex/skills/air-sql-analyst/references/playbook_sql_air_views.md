---
name: playbook-sql-air-views
description: "Playbook 66 view Air: gặp câu hỏi → make clear gì với biz → SQL template tương ứng (Superset / Presto-Trino). Đi kèm catalog-question-bank-air. #43–66 merge từ Manager View (extended)."
metadata:
  type: reference
---

# Playbook: Make-clear + SQL — 66 view Air/OTA

> Dùng cặp với [[catalog-question-bank-air]] (số # giống nhau). Quy trình: biz hỏi → tra # → hỏi đúng các câu **Make clear** → điền param → **xuất câu SQL kèm header khai báo** (template cuối file). **Output chỉ là câu SQL — không chạy, không trả số liệu;** Trang tự chạy trên Superset.

## Quy ước chung (đọc trước khi dùng bất kỳ query nào)

**Bảng & khóa:** `search_air` (alias `s`), `payment_air` (alias `p`). Join user: `s.user_id = p.userID`.

**Param Superset (Jinja):** dùng `DATE '{{ from_date }}'`, `DATE '{{ to_date }}'` — hoặc hardcode. Coverage hợp lệ: search `2025-11-01 → 2026-02-28`; payment `2024-12-01 → 2025-01-31` + `2025-12-01 → 2026-02-28`. **Mọi query join 2 bảng chỉ chạy trên `2025-12-01 → 2026-02-28`.**

### ⚠ Dialect: Presto/Trino — QUY TẮC NGÀY THÁNG (bắt buộc, lỗi nhiều nhất)

Presto **không tự cast string → date/timestamp**. Mọi giá trị thời gian phải convert tường minh về đúng time format:

1. **Literal ngày:** luôn `DATE '2026-01-01'`, không bao giờ `'2026-01-01'` trần. Literal timestamp: `TIMESTAMP '2026-01-01 00:00:00'`. Quên `DATE` → lỗi `Cannot check if date is BETWEEN varchar(10) and varchar(10)`.
2. **Filter cột DATE** (`search_date`, `flight_date`, `departure_date`): `col BETWEEN DATE '...' AND DATE '...'`.
3. **Filter cột TIMESTAMP** (`reqDate`, `activity_time`) theo ngày: dùng nửa-mở `col >= DATE '{{ from_date }}' AND col < DATE '{{ to_date }}' + INTERVAL '1' DAY` — KHÔNG dùng BETWEEN 2 date (mất gần trọn ngày cuối).
4. **Interval:** số trong quote, đơn vị ngoài: `INTERVAL '7' DAY`, `INTERVAL '1' MONTH` (Postgres viết `INTERVAL '7 day'` — sẽ lỗi trên Presto).
5. **Hiệu 2 mốc thời gian:** `date_diff('day'|'hour'|'second', t_start, t_end)` — Presto KHÔNG hỗ trợ `date - date` trực tiếp.
6. **Cộng/trừ ngày trên literal:** `date_add('day', -30, DATE '...')` hoặc `DATE '...' + INTERVAL '30' DAY`.
7. **Lấy ngày từ timestamp:** `date(col)` hoặc `CAST(col AS DATE)`. Cắt grain: `date_trunc('month'|'week', col)`.
8. **Giờ / thứ:** `EXTRACT(HOUR FROM col)`; tên thứ: `format_datetime(col, 'EEEE')` (không có TO_CHAR).

**2 quy tắc Presto khác:**
- **Percentile:** `approx_percentile(col, 0.5)` — không có `PERCENTILE_CONT ... WITHIN GROUP`.
- **Chia số nguyên ra số nguyên** → metric tiền (AOV, ARPPU) phải `CAST(SUM(amount) AS DOUBLE) / ...`.

**4 quirk data bắt buộc nhớ:**
1. `round_type` lẫn case → luôn `UPPER(round_type)` khi group/filter/join với `trip_type`.
2. `search_air`: loại `user_search_group = 'Unknown'` (day_diff = −1, 75 dòng) khi phân tích booking intent.
3. `in_out_bound` 97% null → chỉ dùng trên subset INTERNATIONAL có giá trị, khai báo rõ.
4. `appUser` không còn map 1-1 `appID` (Vietjet/Bamboo/Gotadi dùng chung tên DOM & INTL) → cắt theo hãng thì group `appID`; và EnViet = third party gom Bamboo/Vietravel/Sun PQ.

**Snippet dùng lại — thứ tự weekday:**
```sql
CASE <col> WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
  WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6 WHEN 'Sunday' THEN 7 END
```

**Snippet — thứ tự bucket booking window:**
```sql
CASE <col> WHEN 'Same day' THEN 0 WHEN '1-3 days' THEN 1 WHEN '4-7 days' THEN 2
  WHEN '8-14 days' THEN 3 WHEN '15-30 days' THEN 4 WHEN '31-60 days' THEN 5 WHEN '>60 days' THEN 6 END
```

---

# LEVEL 1 — Lookup 1 bảng

**Make clear chung cho cả Level 1** (hỏi 1 lần, áp dụng mọi view): (a) time range nào, tính theo **cột thời gian nào** (ngày search / ngày mua / ngày bay); (b) đơn vị đếm — **unique user hay lượt/transaction**; (c) filter domestic/intl, hãng. Dưới đây chỉ ghi make-clear **riêng** của từng view.

### #1. Mỗi ngày bao nhiêu người tìm vé?
**Make clear:** unique searcher hay lượt search? (biz nói "bao nhiêu người" → unique, nhưng confirm).
```sql
SELECT search_date,
       COUNT(DISTINCT user_id) AS unique_searcher,
       COUNT(*)                AS search_cnt
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 1 ORDER BY 1;
```

### #2. Nhu cầu bay dồn vào ngày nào?
**Make clear:** đếm theo `departure_date` (ngày muốn bay) — KHÁC #1; có giới hạn search_date không (vd chỉ search trong tháng 2)?
```sql
SELECT departure_date, COUNT(DISTINCT user_id) AS unique_searcher
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 1 ORDER BY 1;
```
**Bẫy:** 1 user search nhiều departure_date → tổng unique theo ngày > tổng unique toàn kỳ. Nói rõ "unique trong từng ngày bay".

### #3. User search giờ nào trong ngày?
**Make clear:** lượt search hay unique searcher per giờ? Giờ theo `activity_time` (local).
```sql
SELECT EXTRACT(HOUR FROM activity_time) AS hr,
       COUNT(*) AS search_cnt
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 1 ORDER BY 1;
```

### #4 / #5. Search / muốn bay vào thứ nào?
**Make clear:** #4 dùng `search_day_in_week`, #5 dùng `departure_day_in_week` — biz hay lẫn 2 cái, hỏi rõ "thứ user bấm tìm" hay "thứ user muốn bay".
```sql
SELECT search_day_in_week AS dow,            -- #5: thay bằng departure_day_in_week
       COUNT(*) AS search_cnt
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 1
ORDER BY CASE search_day_in_week WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
  WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6 WHEN 'Sunday' THEN 7 END;
```

### #6. Top route được tìm nhiều nhất?
**Make clear:** Top N? Tách chiều hay gộp 2 chiều (→ #28)? Theo airport hay city (→ #27)? **Lượt search (frequency) hay unique searcher?** — đưa cả 2 cột đối chiếu, rank lệch nhau = route bị "soi giá" lặp.
```sql
SELECT route,
       COUNT(*)                AS search_cnt,
       COUNT(DISTINCT user_id) AS unique_searcher,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_share
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 1 ORDER BY 2 DESC
LIMIT {{ top_n }};
```
**Bẫy:** nếu rank theo unique searcher, pct_share tính trên tổng theo-route (user đếm lặp qua nhiều route) → khai báo cách tính.

### #7. Top điểm đến hot?
**Make clear:** dest gồm cả sân bay quốc tế (440 code) — chỉ domestic? Gom theo city?
```sql
SELECT dest, COUNT(DISTINCT user_id) AS unique_searcher
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 1 ORDER BY 2 DESC LIMIT {{ top_n }};
```

### #8. Tỷ lệ tìm 1 chiều vs khứ hồi?
**Make clear:** theo lượt search hay theo user (1 user có thể search cả 2 loại → user-level tổng >100%)?
```sql
SELECT trip_type,
       COUNT(*) AS search_cnt,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 1;
```

### #9. User định đặt sớm hay sát ngày?
**Make clear:** đây là intent lúc **search** (`user_search_group`), khác hành vi lúc **mua** (#18) — biz muốn cái nào?
```sql
SELECT user_search_group,
       COUNT(*) AS search_cnt,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
  AND user_search_group <> 'Unknown'
GROUP BY 1
ORDER BY CASE user_search_group WHEN 'Same day' THEN 0 WHEN '1-3 days' THEN 1 WHEN '4-7 days' THEN 2
  WHEN '8-14 days' THEN 3 WHEN '15-30 days' THEN 4 WHEN '31-60 days' THEN 5 WHEN '>60 days' THEN 6 END;
```

### #10. Mỗi ngày bao nhiêu đơn / khách mua?
**Make clear:** theo ngày mua `reqDate` (không phải ngày bay); có cắt theo provider không?
```sql
SELECT date(reqDate) AS pay_date,
       COUNT(transID)         AS txn,
       COUNT(DISTINCT userID) AS paying_user
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY 1;
```
**Bẫy:** `reqDate` là timestamp → filter nửa-mở `< to_date + 1 ngày` (quy tắc ngày tháng #3), đừng BETWEEN 2 date.

### #11. TPV theo ngày/tháng?
**Make clear:** TPV gross (chưa refund) — biz có đang kỳ vọng doanh thu thực không? Nói rõ ngay.
```sql
SELECT date_trunc('month', reqDate) AS ym,   -- daily: date(reqDate)
       SUM(amount) AS tpv
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY 1;
```

### #12. Đơn dồn vào ngày bay nào?
**Make clear:** trục thời gian là `flight_date`; vẫn nên giới hạn thêm range mua (`reqDate`) nếu biz hỏi "vé Tết đã bán".
```sql
SELECT flight_date, COUNT(transID) AS txn
FROM payment_air
WHERE flight_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 1 ORDER BY 1;
```

### #13. Mua vé giờ nào, thứ nào?
**Make clear:** giờ/thứ theo `reqDate`. Cắt provider?
```sql
SELECT EXTRACT(HOUR FROM reqDate) AS hr,     -- theo thứ: format_datetime(reqDate, 'EEEE') AS dow
       COUNT(transID) AS txn
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY 1;
```

### #14. Top route thực mua?
**Make clear:** như #6 (top N, chiều, airport/city) + rank theo **transaction hay paying user** — 2 bảng xếp hạng có thể khác nhau, đưa cả 2 cột.
```sql
SELECT route,
       COUNT(transID)         AS txn,
       COUNT(DISTINCT userID) AS paying_user,
       ROUND(100.0 * COUNT(transID) / SUM(COUNT(transID)) OVER (), 2) AS pct_txn
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY 2 DESC LIMIT {{ top_n }};
```

### #15. Thị phần các hãng/provider?
**Make clear:** "theo hãng" hay "theo provider/appID"? EnViet gom Bamboo/Vietravel/Sun PQ → nếu biz muốn theo hãng thật thì phần EnViet KHÔNG tách được, phải khai báo. Share theo transaction hay TPV?
```sql
SELECT appID, appUser,
       MAX(CASE WHEN flight_type = 'DOMESTIC' THEN 'DOM' ELSE 'INTL' END) AS dom_intl,
       COUNT(transID) AS txn,
       SUM(amount)    AS tpv,
       ROUND(100.0 * COUNT(transID) / SUM(COUNT(transID)) OVER (), 2) AS pct_txn,
       ROUND(100.0 * SUM(amount)    / SUM(SUM(amount))    OVER (), 2) AS pct_tpv
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1, 2 ORDER BY txn DESC;
```

### #16. Domestic vs International?
```sql
SELECT flight_type, COUNT(transID) AS txn, SUM(amount) AS tpv,
       ROUND(100.0 * COUNT(transID) / SUM(COUNT(transID)) OVER (), 2) AS pct_txn
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1;
```

### #17. Mua 1 chiều hay khứ hồi?
**Make clear:** không có gì phải hỏi thêm — nhưng **bắt buộc UPPER()**, nếu không sẽ ra 4 dòng thay vì 2.
```sql
SELECT CASE UPPER(round_type) WHEN 'ONEWAY' THEN 'OneWay' ELSE 'RoundTrip' END AS round_type_norm,
       COUNT(transID) AS txn,
       ROUND(100.0 * COUNT(transID) / SUM(COUNT(transID)) OVER (), 2) AS pct
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1;
```

### #18. Khách mua sớm hay sát ngày bay?
**Make clear:** behavior lúc mua (`booking_window_group`) — đối chiếu intent lúc search là #9/#33.
```sql
SELECT booking_window_group,
       COUNT(transID) AS txn,
       ROUND(100.0 * COUNT(transID) / SUM(COUNT(transID)) OVER (), 2) AS pct
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1
ORDER BY CASE booking_window_group WHEN 'Same day' THEN 0 WHEN '1-3 days' THEN 1 WHEN '4-7 days' THEN 2
  WHEN '8-14 days' THEN 3 WHEN '15-30 days' THEN 4 WHEN '31-60 days' THEN 5 WHEN '>60 days' THEN 6 END;
```

## Bổ sung Manager View — Level 1 (#43–48)

**Quy ước grain:** "hãng" = `appID`; "kênh/provider" = `appUser` (quirk 4 — EnViet gom Bamboo/Vietravel/Sun PQ, không tách được hãng thật).

### #43. Tăng giảm % so hôm qua / tháng trước (E4, E5, E10)
**Make clear:** grain daily (D vs D-1) hay monthly (M vs M-1)? So transaction, TPV hay cả 2?
```sql
WITH daily AS (
  SELECT date(reqDate) AS d,                  -- monthly: date_trunc('month', reqDate)
         COUNT(transID) AS txn, SUM(amount) AS tpv
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
)
SELECT d, txn, tpv,
       ROUND(100.0 * (txn - LAG(txn) OVER (ORDER BY d)) / LAG(txn) OVER (ORDER BY d), 2) AS txn_chg_pct,
       ROUND(100.0 * (tpv - LAG(tpv) OVER (ORDER BY d)) / LAG(tpv) OVER (ORDER BY d), 2) AS tpv_chg_pct
FROM daily ORDER BY d;
```
**Bẫy:** mùa Tết DoD/MoM dao động mạnh tự nhiên — đọc kèm days-to-Tết (#22), đừng kết luận trend từ 1 cặp ngày.

### #44. Rank hãng: top/bottom, hãng nguy cơ bị loại (E11–15, E18)
**Make clear:** rank theo transaction hay TPV? "Hãng" = appID, phần EnViet không tách được — khai báo.
```sql
SELECT appID,
       COUNT(transID) AS txn, SUM(amount) AS tpv,
       ROUND(100.0 * COUNT(transID) / SUM(COUNT(transID)) OVER (), 2) AS pct_txn,
       ROUND(100.0 * SUM(amount)    / SUM(SUM(amount))    OVER (), 2) AS pct_tpv
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY txn DESC;       -- top đọc từ đầu, bottom/at-risk đọc từ cuối
```

### #45. Khứ hồi chiếm bao nhiêu % TPV? (E22)
**Make clear:** #17 là % transaction — đây là % TPV, 2 số khác nhau (AOV RoundTrip ~2x).
```sql
SELECT CASE UPPER(round_type) WHEN 'ONEWAY' THEN 'OneWay' ELSE 'RoundTrip' END AS round_type_norm,
       SUM(amount) AS tpv,
       ROUND(100.0 * SUM(amount) / SUM(SUM(amount)) OVER (), 2) AS pct_tpv
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1;
```

### #46. DOM/INTL × 1 chiều/khứ hồi (E23–24)
**Make clear:** % tính trong từng flight_type hay trên tổng?
```sql
SELECT flight_type,
       CASE UPPER(round_type) WHEN 'ONEWAY' THEN 'OneWay' ELSE 'RoundTrip' END AS round_type_norm,
       COUNT(transID) AS txn,
       ROUND(100.0 * COUNT(transID) / SUM(COUNT(transID)) OVER (PARTITION BY flight_type), 2) AS pct_in_market
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1, 2 ORDER BY 1, 3 DESC;
```

### #47. Top điểm khởi hành (E42)
**Make clear:** theo airport hay city (→ #27)? Top N?
```sql
SELECT origin, COUNT(transID) AS txn, COUNT(DISTINCT userID) AS paying_user
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY 2 DESC LIMIT {{ top_n }};
```

### #48. Top khách chi tiêu (E35)
**Make clear:** top N? Output cho mục đích gì (CRM cần thêm cột gì)? Window = coverage, khai báo.
```sql
SELECT userID, SUM(amount) AS user_tpv, COUNT(transID) AS txn,
       CAST(SUM(amount) AS DOUBLE) / COUNT(transID) AS aov
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY 2 DESC LIMIT {{ top_n }};
```

---

# LEVEL 2 — Phân tích sâu 1 bảng

### #19. AOV theo tháng / hãng / route / DOM-INTL
**Make clear:** biz nói "giá vé trung bình" → hỏi ngay: per **đơn** (AOV) hay per **vé** (ATP)? **ATP không tính được** (thiếu ticket_num) — chốt AOV và nói rõ 1 đơn có thể nhiều vé. KHÔNG dùng AOV trả lời góc per-user (đó là ARPPU, #39).
```sql
SELECT date_trunc('month', reqDate) AS ym,   -- đổi grain: appID / route / flight_type
       CAST(SUM(amount) AS DOUBLE) / COUNT(transID) AS aov,   -- CAST tránh chia nguyên
       COUNT(transID) AS txn
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY 1;
```
**Bẫy:** AOV RoundTrip ~2x OneWay là chuyện ticket_num, không phải "vé đắt lên" → khi so AOV giữa nhóm, luôn cắt thêm UPPER(round_type).

### #20. Phân phối giá trị đơn / outlier
**Make clear:** biz cần percentile hay danh sách đơn to bất thường để check? Ngưỡng outlier bao nhiêu?
```sql
SELECT approx_percentile(amount, 0.5)  AS p50,
       approx_percentile(amount, 0.9)  AS p90,
       approx_percentile(amount, 0.99) AS p99,
       MIN(amount) AS min_amt, MAX(amount) AS max_amt
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY;
-- list outlier: SELECT * FROM payment_air WHERE amount > {{ threshold }} ORDER BY amount DESC;
```

### #21. Booking window theo route / hãng / loại vé
**Make clear:** so bằng **median** (mặc định, chống outlier) hay mean? Dimension nào trước?
```sql
SELECT route,                                 -- đổi: appID / UPPER(round_type) / flight_type
       COUNT(transID) AS txn,
       approx_percentile(booking_window, 0.5) AS median_bw,
       AVG(booking_window) AS avg_bw
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 HAVING COUNT(transID) >= 30        -- đủ mẫu mới so
ORDER BY 2 DESC;
```

### #22. Countdown Tết YoY
**Make clear:** mốc Tết = mùng 1 (Tết 2025: 2025-01-29; Tết 2026: 2026-02-17)? Window countdown ±bao nhiêu ngày? So transaction hay TPV?
```sql
SELECT season, days_to_tet, COUNT(transID) AS txn
FROM (
  SELECT transID,
         CASE WHEN reqDate < DATE '2025-06-01' THEN 'Tet 2025' ELSE 'Tet 2026' END AS season,
         CASE WHEN reqDate < DATE '2025-06-01'
              THEN date_diff('day', date(reqDate), DATE '2025-01-29')
              ELSE date_diff('day', date(reqDate), DATE '2026-02-17') END AS days_to_tet
  FROM payment_air
) t
WHERE days_to_tet BETWEEN -{{ n_after }} AND {{ n_before }}
GROUP BY 1, 2 ORDER BY 2 DESC;
```
**Bẫy:** 2 mùa có độ dài coverage khác nhau → chỉ so trên dải days_to_tet cả 2 mùa đều có data.

### #23. Ngày bay tương lai nào sắp "cháy"?
**Make clear:** "hot" = searcher tăng so baseline nào (7 ngày trước? cùng route?)? Đây là demand chưa chắc supply.
```sql
SELECT departure_date, route, COUNT(DISTINCT user_id) AS unique_searcher
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
  AND departure_date > DATE '{{ to_date }}'
GROUP BY 1, 2 HAVING COUNT(DISTINCT user_id) >= {{ min_searcher }}
ORDER BY 3 DESC LIMIT 50;
```

### #24. 1 user search bao nhiêu lần / bao nhiêu route?
**Make clear:** trong window nào (cả kỳ hay per tuần)? Trả phân phối, đừng chỉ mean (long tail nặng).
```sql
WITH per_user AS (
  SELECT user_id, COUNT(*) AS search_cnt, COUNT(DISTINCT route) AS route_cnt
  FROM search_air
  WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
  GROUP BY 1
)
SELECT CASE WHEN search_cnt = 1 THEN '1' WHEN search_cnt <= 5 THEN '2-5'
            WHEN search_cnt <= 20 THEN '6-20' WHEN search_cnt <= 50 THEN '21-50'
            ELSE '>50' END AS search_bucket,
       COUNT(*) AS users,
       AVG(route_cnt) AS avg_routes
FROM per_user
GROUP BY 1 ORDER BY MIN(search_cnt);
```

### #25. Gap khứ hồi: search 17% nhưng mua 6.5%?
**Make clear:** so trên **cùng range thời gian** (search_date vs ngày mua); % theo lượt search vs % theo transaction — 2 đơn vị khác nhau, khai báo rõ là so tỷ trọng, không phải conversion.
```sql
SELECT 'search' AS src, trip_type AS type_norm,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM search_air
WHERE search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 2
UNION ALL
SELECT 'payment', CASE UPPER(round_type) WHEN 'ONEWAY' THEN 'One-way' ELSE 'Round-trip' END,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 2;
```

### #26. Quốc tế: inbound hay outbound?
**Make clear:** cột 97% null → kết quả chỉ đại diện 598 dòng có giá trị, PHẢI nói trước với biz. Hỏi: cần đủ thì suy từ origin/dest (origin nước ngoài = inbound)?
```sql
SELECT in_out_bound, COUNT(transID) AS txn, SUM(amount) AS tpv
FROM payment_air
WHERE flight_type = 'INTERNATIONAL'
  AND in_out_bound IS NOT NULL AND in_out_bound <> ''
GROUP BY 1;
```

### #27. Demand/thực mua theo thành phố
**Make clear:** chốt bảng map city→airports với biz trước (SGN=TP.HCM, HAN=Hà Nội, DAD=Đà Nẵng, CXR=Nha Trang, PQC=Phú Quốc, VCA=Cần Thơ, HUI=Huế, VII=Vinh, UIH=Quy Nhơn...); city nào nhiều sân bay phải gom đủ.
```sql
WITH city_map AS (
  SELECT * FROM (VALUES
    ('SGN','TP.HCM'), ('HAN','Hà Nội'), ('DAD','Đà Nẵng'), ('CXR','Nha Trang'),
    ('PQC','Phú Quốc'), ('VCA','Cần Thơ'), ('HUI','Huế'), ('VII','Vinh'), ('UIH','Quy Nhơn')
    -- bổ sung đủ list trước khi chạy thật
  ) AS t(airport, city)
)
SELECT cd.city AS dest_city, COUNT(DISTINCT s.user_id) AS unique_searcher
FROM search_air s
JOIN city_map cd ON cd.airport = s.dest
WHERE s.search_date BETWEEN DATE '{{ from_date }}' AND DATE '{{ to_date }}'
GROUP BY 1 ORDER BY 2 DESC;
```
**Bẫy:** airport ngoài map sẽ rớt khỏi kết quả → đếm thêm % coverage của map trước khi trả số.

### #28. Route gộp 2 chiều
**Make clear:** confirm với biz là muốn "cặp thành phố" (SGN↔HAN) — vì view dashboard mặc định tách chiều, số sẽ khác hẳn.
```sql
SELECT least(origin, dest) || '-' || greatest(origin, dest) AS city_pair,
       COUNT(transID) AS txn, COUNT(DISTINCT userID) AS paying_user
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY 2 DESC LIMIT {{ top_n }};
```

## Bổ sung Manager View — Level 2 (#49–57)

### #49. MoM growth/decline theo hãng / route / kênh (E17, E50, E57–58, E87)
**Make clear:** dimension nào (appID / route / appUser)? Growth theo transaction hay TPV? Chỉ có 3 tháng liên tục (T12/2025–T2/2026) → tối đa 2 cặp MoM.
```sql
WITH m AS (
  SELECT appID AS dim,                        -- đổi: route / appUser
         date_trunc('month', reqDate) AS ym,
         COUNT(transID) AS txn, SUM(amount) AS tpv
  FROM payment_air
  WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01'
  GROUP BY 1, 2
)
SELECT dim, ym, txn, tpv,
       ROUND(100.0 * (tpv - LAG(tpv) OVER (PARTITION BY dim ORDER BY ym))
                   / LAG(tpv) OVER (PARTITION BY dim ORDER BY ym), 2) AS tpv_mom_pct
FROM m ORDER BY ym, tpv_mom_pct DESC NULLS LAST;
```
**Bẫy:** T1→T2/2026 dính Tết (17/02) → "giảm mạnh" có thể chỉ là hết mùa. Đối chiếu YoY (#22) trước khi gắn nhãn at-risk.

### #50. Tuyến bán chậm nhất (E43)
**Make clear:** bottom theo transaction tuyệt đối hay theo CR (→ #30)? Loại route quá ít data?
```sql
SELECT route, COUNT(transID) AS txn, SUM(amount) AS tpv
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 HAVING COUNT(transID) >= {{ min_txn }}     -- vd 10, tránh đuôi route 1-2 đơn
ORDER BY 2 ASC LIMIT {{ bottom_n }};
```

### #51. Concentration: % doanh số từ top N tuyến/kênh/hãng (E45, E60, E89)
**Make clear:** dimension + N (mặc định: top 10 route / top 3 appUser / top 5 appID)? Theo TPV hay transaction?
```sql
WITH agg AS (
  SELECT route AS dim, SUM(amount) AS tpv    -- đổi: appUser / appID
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
),
ranked AS (SELECT *, ROW_NUMBER() OVER (ORDER BY tpv DESC) AS rk FROM agg)
SELECT SUM(CASE WHEN rk <= {{ top_n }} THEN tpv END) AS tpv_top_n,
       SUM(tpv) AS tpv_total,
       ROUND(100.0 * SUM(CASE WHEN rk <= {{ top_n }} THEN tpv END) / SUM(tpv), 2) AS pct_top_n
FROM ranked;
```

### #52. Khách đặt sớm vs sát ngày — % TPV (E61–62)
**Make clear:** #18 là % transaction — đây là % TPV. Bucket chuẩn hay cắt 2 nhóm thô (>30d / <7d)?
```sql
SELECT booking_window_group,
       SUM(amount) AS tpv,
       ROUND(100.0 * SUM(amount) / SUM(SUM(amount)) OVER (), 2) AS pct_tpv
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1
ORDER BY CASE booking_window_group WHEN 'Same day' THEN 0 WHEN '1-3 days' THEN 1 WHEN '4-7 days' THEN 2
  WHEN '8-14 days' THEN 3 WHEN '15-30 days' THEN 4 WHEN '31-60 days' THEN 5 WHEN '>60 days' THEN 6 END;
```

### #53. Repeat rate theo nhóm booking window (E63)
**Make clear:** user có nhiều đơn nhiều bucket → gán theo bucket của **đơn đầu tiên** (chốt với biz).
```sql
WITH per_user AS (
  SELECT userID,
         MIN_BY(booking_window_group, reqDate) AS first_bucket,
         COUNT(transID) AS txn
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
)
SELECT first_bucket,
       COUNT(*) AS users,
       ROUND(100.0 * SUM(CASE WHEN txn >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS repeat_pct
FROM per_user GROUP BY 1
ORDER BY CASE first_bucket WHEN 'Same day' THEN 0 WHEN '1-3 days' THEN 1 WHEN '4-7 days' THEN 2
  WHEN '8-14 days' THEN 3 WHEN '15-30 days' THEN 4 WHEN '31-60 days' THEN 5 WHEN '>60 days' THEN 6 END;
```

### #54. Repeat rate theo kênh (E55)
**Make clear:** gán user theo kênh của đơn đầu (như #53). Repeat = ≥2 đơn bất kỳ kênh, hay ≥2 đơn cùng kênh?
```sql
WITH per_user AS (
  SELECT userID,
         MIN_BY(appUser, reqDate) AS first_channel,
         COUNT(transID) AS txn
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
)
SELECT first_channel, COUNT(*) AS users,
       ROUND(100.0 * SUM(CASE WHEN txn >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS repeat_pct
FROM per_user GROUP BY 1 ORDER BY users DESC;
```

### #55. Khách kênh nào chi tiêu nhiều nhất (E59)
**Make clear:** "CLV" ở đây = TPV trong coverage — khai báo window, không phải lifetime thật.
```sql
SELECT appUser,
       COUNT(DISTINCT userID) AS users, SUM(amount) AS tpv,
       CAST(SUM(amount) AS DOUBLE) / COUNT(DISTINCT userID) AS tpv_per_user
FROM payment_air
WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY tpv_per_user DESC;
```
**Bẫy:** user mua nhiều kênh bị đếm ở từng kênh → tổng users theo kênh > unique user toàn hệ.

### #56. DOM hay INTL tăng nhanh hơn (E75)
Dùng template #49 với `dim = flight_type`. **Bẫy:** INTL chỉ ~3% volume → % growth dao động mạnh, đưa kèm số tuyệt đối.

### #57. Trend 3 tháng T12/2025–T2/2026 (E71)
Dùng template #11 grain monthly (txn + TPV). **Bắt buộc nói:** 3 tháng này là trọn mùa Tết — trend tăng/giảm phản ánh seasonality, không phải trajectory business; muốn nói growth phải so YoY (#22).

---

# LEVEL 3 — Join 2 bảng (demand ↔ thực mua)

**Make clear chung cho cả Level 3 — 3 điều BẮT BUỘC chốt trước khi xuất query:**
1. **Match window**: mua trong vòng bao nhiêu ngày sau search thì tính là "converted"? (mặc định đề xuất 7 ngày — phải khai báo trong header).
2. **Match grain**: cùng user là đủ, hay phải **cùng user + cùng route**? Số khác nhau rất xa.
3. **Range**: chỉ chạy trên giai đoạn trùng coverage `2025-12-01 → 2026-02-28`. Payment T12/2024–T1/2025 KHÔNG có search → đưa vào là sai.

Và câu khai báo bắt buộc khi trả kết quả: *"Đây là conversion user-level qua join search↔payment, KHÔNG phải CR session chuẩn (không có tracking_session_id)."*

### #29. Bao nhiêu % người search rồi mua?
```sql
-- Conversion user-level: search → mua trong {{ window_days }} ngày (mặc định 7)
WITH searcher AS (
  SELECT user_id, MIN(activity_time) AS first_search
  FROM search_air
  WHERE search_date BETWEEN DATE '2025-12-01' AND DATE '2026-02-28'
  GROUP BY 1
),
buyer AS (
  SELECT DISTINCT s.user_id
  FROM searcher s
  JOIN payment_air p
    ON p.userID = s.user_id
   AND p.reqDate >= s.first_search
   AND p.reqDate <  s.first_search + INTERVAL '{{ window_days }}' DAY
)
SELECT COUNT(*)                                   AS searcher_cnt,
       (SELECT COUNT(*) FROM buyer)               AS buyer_cnt,
       ROUND(100.0 * (SELECT COUNT(*) FROM buyer) / COUNT(*), 2) AS conversion_pct
FROM searcher;
```
**Bẫy:** anchor là first_search hay *mỗi lần* search? Query trên dùng first_search per user (đơn giản, conservative). Nếu biz muốn "search nào cũng có cơ hội convert" → match theo từng search, số sẽ cao hơn — chốt 1 cách và ghi vào header.

### #30. Conversion theo route — route nào search nhiều mua ít?
```sql
WITH s AS (
  SELECT route, user_id, MIN(activity_time) AS first_search
  FROM search_air
  WHERE search_date BETWEEN DATE '2025-12-01' AND DATE '2026-02-28'
  GROUP BY 1, 2
),
b AS (
  SELECT s.route, s.user_id
  FROM s
  JOIN payment_air p
    ON p.userID = s.user_id AND p.route = s.route        -- match cùng user + cùng route
   AND p.reqDate >= s.first_search
   AND p.reqDate <  s.first_search + INTERVAL '{{ window_days }}' DAY
  GROUP BY 1, 2
)
SELECT s.route,
       COUNT(DISTINCT s.user_id) AS searcher,
       COUNT(DISTINCT b.user_id) AS buyer,
       ROUND(100.0 * COUNT(DISTINCT b.user_id) / COUNT(DISTINCT s.user_id), 2) AS cr_pct
FROM s LEFT JOIN b ON b.route = s.route AND b.user_id = s.user_id
GROUP BY 1 HAVING COUNT(DISTINCT s.user_id) >= {{ min_searcher }}   -- đủ mẫu, vd 100
ORDER BY cr_pct ASC;       -- sort tăng dần = route "search nhiều mua ít" lên đầu
```
**Bẫy:** route ít searcher có CR nhiễu → bắt buộc HAVING ngưỡng mẫu. Route intl supply hạn chế → CR thấp chưa chắc là vấn đề UX.

### #31. Từ search đầu đến lúc mua mất bao lâu?
**Make clear:** tính trên grain user×route (chuẩn) hay chỉ user? Đơn vị giờ hay ngày?
```sql
WITH first_search AS (
  SELECT user_id, route, MIN(activity_time) AS first_search
  FROM search_air
  WHERE search_date BETWEEN DATE '2025-12-01' AND DATE '2026-02-28'
  GROUP BY 1, 2
),
matched AS (
  SELECT fs.user_id, fs.route,
         date_diff('second', fs.first_search, MIN(p.reqDate)) / 86400.0 AS days_to_buy
  FROM first_search fs
  JOIN payment_air p
    ON p.userID = fs.user_id AND p.route = fs.route
   AND p.reqDate >= fs.first_search
  GROUP BY 1, 2, fs.first_search
)
SELECT approx_percentile(days_to_buy, 0.5)  AS median_days,
       approx_percentile(days_to_buy, 0.75) AS p75_days,
       approx_percentile(days_to_buy, 0.9)  AS p90_days,
       COUNT(*) AS matched_pairs
FROM matched;
```

### #32. Khách search xong mua route khác?
**Make clear:** "khác" = route mua không nằm trong BẤT KỲ route nào đã search trước đó (trong window)? Gồm cả chiều ngược (search SGN-HAN, mua HAN-SGN) — tính là khác hay giống? (đề xuất: chuẩn hóa gộp chiều trước khi so).
```sql
WITH buys AS (
  SELECT userID, transID, route, reqDate
  FROM payment_air
  WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01'
),
matched AS (
  SELECT b.transID,
         MAX(CASE WHEN s.route = b.route THEN 1 ELSE 0 END) AS same_route_searched
  FROM buys b
  JOIN search_air s
    ON s.user_id = b.userID
   AND s.activity_time <  b.reqDate
   AND s.activity_time >= b.reqDate - INTERVAL '{{ window_days }}' DAY
  GROUP BY 1
)
SELECT COUNT(*) AS buys_with_prior_search,
       SUM(1 - same_route_searched) AS bought_diff_route,
       ROUND(100.0 * SUM(1 - same_route_searched) / COUNT(*), 2) AS pct_diff_route
FROM matched;
```

### #33. Intent lúc search vs hành vi lúc mua (booking window)
**Make clear:** so phân phối 2 bucket trên **cùng tập user đã match** (không phải toàn bộ 2 bảng); loại Unknown bên search.
```sql
WITH matched_user AS (
  SELECT DISTINCT s.user_id
  FROM search_air s JOIN payment_air p ON p.userID = s.user_id
  WHERE s.search_date BETWEEN DATE '2025-12-01' AND DATE '2026-02-28'
    AND p.reqDate >= DATE '2025-12-01' AND p.reqDate < DATE '2026-03-01'
)
SELECT 'search_intent' AS src, s.user_search_group AS bucket,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM search_air s JOIN matched_user m ON m.user_id = s.user_id
WHERE s.search_date BETWEEN DATE '2025-12-01' AND DATE '2026-02-28'
  AND s.user_search_group <> 'Unknown'
GROUP BY 2
UNION ALL
SELECT 'pay_behavior', p.booking_window_group,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)
FROM payment_air p JOIN matched_user m ON m.user_id = p.userID
WHERE p.reqDate >= DATE '2025-12-01' AND p.reqDate < DATE '2026-03-01'
GROUP BY 2;
```

### #34. List remarketing: search nhiều chưa mua
**Make clear:** ngưỡng ≥N lượt search (đề xuất 5)? Lookback X ngày? "Chưa mua" = chưa mua route đó hay chưa mua bất kỳ vé nào? Output cần cột gì cho CRM?
```sql
WITH intent AS (
  SELECT user_id, route,
         COUNT(*) AS search_cnt,
         MAX(activity_time) AS last_search
  FROM search_air
  WHERE search_date >= date_add('day', -{{ lookback_days }}, DATE '{{ as_of_date }}')
    AND search_date <= DATE '{{ as_of_date }}'
  GROUP BY 1, 2 HAVING COUNT(*) >= {{ min_search }}
)
SELECT i.user_id, i.route, i.search_cnt, i.last_search
FROM intent i
LEFT JOIN payment_air p
  ON p.userID = i.user_id                      -- thêm: AND p.route = i.route nếu "chưa mua route đó"
 AND p.reqDate >= date_add('day', -{{ lookback_days }}, DATE '{{ as_of_date }}')
WHERE p.transID IS NULL
ORDER BY i.search_cnt DESC;
```

### #35. Mua sau bao nhiêu ngày-search? (proxy session)
**Make clear:** khai báo đây là **proxy** — đếm số ngày có search trước khi mua, KHÔNG phải số session (không có tracking_session_id).
```sql
WITH first_buy AS (
  SELECT userID, MIN(reqDate) AS first_buy
  FROM payment_air
  WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01'
  GROUP BY 1
)
SELECT search_days_before_buy, COUNT(*) AS users
FROM (
  SELECT fb.userID, COUNT(DISTINCT s.search_date) AS search_days_before_buy
  FROM first_buy fb
  JOIN search_air s ON s.user_id = fb.userID AND s.activity_time < fb.first_buy
  GROUP BY 1
) t
GROUP BY 1 ORDER BY 1;
```

## Bổ sung Manager View — Level 3 (#58–59)

### #58. Search nội địa có mua quốc tế không? (E79)
**Make clear:** search_air không có flight_type → phân loại search DOM bằng list sân bay VN (chốt list với biz, như city_map #27). Window match? Hay chỉ cần overlap trong kỳ?
```sql
WITH vn_airports AS (
  SELECT code FROM (VALUES ('SGN'),('HAN'),('DAD'),('CXR'),('PQC'),('VCA'),('HUI'),('VII'),('UIH')
    -- bổ sung đủ list sân bay VN trước khi chạy thật
  ) AS t(code)
),
dom_search AS (
  SELECT user_id, MIN(activity_time) AS first_dom_search
  FROM search_air
  WHERE search_date BETWEEN DATE '2025-12-01' AND DATE '2026-02-28'
    AND origin IN (SELECT code FROM vn_airports)
    AND dest   IN (SELECT code FROM vn_airports)
  GROUP BY 1
)
SELECT COUNT(*) AS dom_searchers,
       COUNT(DISTINCT p.userID) AS bought_intl,
       ROUND(100.0 * COUNT(DISTINCT p.userID) / COUNT(*), 2) AS pct_cross
FROM dom_search d
LEFT JOIN payment_air p
  ON p.userID = d.user_id
 AND p.flight_type = 'INTERNATIONAL'
 AND p.reqDate >= d.first_dom_search
 AND p.reqDate <  d.first_dom_search + INTERVAL '{{ window_days }}' DAY;
```
**Bẫy:** sân bay không nằm trong list VN sẽ làm search bị phân loại sai → check % coverage list trước.

### #59. Buyer 1 lần có search route khác sau khi mua? (cross-sell proxy) (E95)
**Make clear:** khai báo là **proxy intent**, không phải nhu cầu chắc chắn. Route "khác" có gộp chiều ngược không (như #32)?
```sql
WITH one_buyers AS (
  SELECT userID, MIN(route) AS bought_route, MIN(reqDate) AS buy_time
  FROM payment_air
  WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01'
  GROUP BY 1 HAVING COUNT(transID) = 1
)
SELECT (SELECT COUNT(*) FROM one_buyers) AS one_time_buyers,
       COUNT(DISTINCT b.userID)          AS searched_other_route,
       ROUND(100.0 * COUNT(DISTINCT b.userID) / (SELECT COUNT(*) FROM one_buyers), 2) AS pct_cross_sell
FROM one_buyers b
JOIN search_air s
  ON s.user_id = b.userID
 AND s.activity_time >  b.buy_time
 AND s.activity_time <  b.buy_time + INTERVAL '{{ window_days }}' DAY
 AND s.route <> b.bought_route;
```

---

# LEVEL 4 — Lifecycle / cohort / YoY

**Make clear chung Level 4:** mọi metric segment/retention ở đây là **trong-phạm-vi-Air và trong-window-data** — KHÔNG phải NPU/FPU/RR chuẩn toàn ZLP. Câu khai báo bắt buộc: *"User 'mới' = chưa từng xuất hiện trong data Air kỳ này, không nói được họ có pay ZLP/category khác hay không."* Với RR: hỏi period (M→M / W→W) trước, theo [[zlp-ota-metric-definitions]].

### #36. Khách Tết 2025 quay lại Tết 2026?
**Make clear:** định nghĩa window 2 mùa (đề xuất theo coverage: T12/2024–T1/2025 vs T12/2025–T2/2026)? "Quay lại" = có ≥1 transaction Air, không phân biệt route/hãng?
```sql
WITH tet25 AS (
  SELECT DISTINCT userID FROM payment_air
  WHERE reqDate >= DATE '2024-12-01' AND reqDate < DATE '2025-02-01'
),
tet26 AS (
  SELECT DISTINCT userID FROM payment_air
  WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01'
)
SELECT (SELECT COUNT(*) FROM tet25)            AS buyers_tet25,
       (SELECT COUNT(*) FROM tet26)            AS buyers_tet26,
       COUNT(*)                                AS retained,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM tet25), 2) AS retention_pct
FROM tet25 t25 JOIN tet26 t26 ON t26.userID = t25.userID;
```
**Bẫy:** 2 window không cùng độ dài (2 tháng vs 3 tháng) → nếu biz cần so chặt, cắt cùng số ngày quanh Tết.

### #37. Bao nhiêu khách mua ≥2 lần trong mùa?
```sql
SELECT CASE WHEN txn = 1 THEN '1 lần' WHEN txn = 2 THEN '2 lần' ELSE '3+ lần' END AS buy_freq,
       COUNT(*) AS users,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM (
  SELECT userID, COUNT(transID) AS txn
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
) t
GROUP BY 1 ORDER BY MIN(txn);
```
**Bẫy:** khứ hồi = 1 transaction, không phải 2 — đừng để biz hiểu nhầm "mua 2 lần" gồm vé chiều về.

### #38. RR tháng→tháng của buyer Air
**Make clear:** RR period đã chốt là M→M? Chỉ chạy được trên giai đoạn liên tục T12/2025–T2/2026 (2 cặp tháng). Đọc trong-Air only.
```sql
WITH monthly AS (
  SELECT DISTINCT date_trunc('month', reqDate) AS ym, userID
  FROM payment_air
  WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01'
)
SELECT m0.ym,
       COUNT(DISTINCT m0.userID) AS buyers_m0,
       COUNT(DISTINCT m1.userID) AS retained_m1,
       ROUND(100.0 * COUNT(DISTINCT m1.userID) / COUNT(DISTINCT m0.userID), 2) AS rr_pct
FROM monthly m0
LEFT JOIN monthly m1
  ON m1.userID = m0.userID AND m1.ym = m0.ym + INTERVAL '1' MONTH
GROUP BY 1 ORDER BY 1;
```
**Bẫy:** tháng cuối (T2/2026) không có M+1 → loại khỏi kết luận. Mùa Tết RR cao tự nhiên (mua vé đi + vé về 2 tháng khác nhau) — đừng đọc thành stickiness.

### #39. ARPPU mùa này
**Make clear:** window life-cycle = gì? (đề xuất: trọn mùa T12/2025–T2/2026). PHẢI ghi window vào header — ARPPU không có window là số vô nghĩa. Phân biệt với AOV (#19).
```sql
SELECT CAST(SUM(amount) AS DOUBLE) / COUNT(DISTINCT userID) AS arppu,
       SUM(amount)                          AS tpv,
       COUNT(DISTINCT userID)               AS paying_user
FROM payment_air
WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01';
```

### #40. Phân tầng khách theo chi tiêu
**Make clear:** chia decile (10 tầng) hay tier nghiệp vụ (vd <2M / 2-5M / >5M)? Window nào?
```sql
WITH per_user AS (
  SELECT userID, SUM(amount) AS user_tpv, COUNT(transID) AS txn
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
),
ranked AS (SELECT *, NTILE(10) OVER (ORDER BY user_tpv) AS decile FROM per_user)
SELECT decile,
       COUNT(*)            AS users,
       SUM(user_tpv)       AS tpv,
       ROUND(100.0 * SUM(user_tpv) / SUM(SUM(user_tpv)) OVER (), 2) AS pct_tpv,
       CAST(SUM(user_tpv) AS DOUBLE) / SUM(txn) AS aov_in_tier
FROM ranked GROUP BY 1 ORDER BY 1 DESC;
```

### #41. Khách mua lặp vs mua 1 lần khác nhau gì?
**Make clear:** so những chiều nào (đề xuất: AOV, median booking_window, % RoundTrip, % INTL)? Cùng window.
```sql
WITH per_user AS (
  SELECT userID, COUNT(transID) AS txn
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
)
SELECT CASE WHEN u.txn = 1 THEN 'one-time' ELSE 'repeat' END AS segment,
       COUNT(DISTINCT p.userID)            AS users,
       COUNT(p.transID)                    AS txn,
       CAST(SUM(p.amount) AS DOUBLE) / COUNT(p.transID) AS aov,
       approx_percentile(p.booking_window, 0.5) AS median_bw,
       ROUND(100.0 * SUM(CASE WHEN UPPER(p.round_type) = 'ROUNDTRIP' THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_roundtrip,
       ROUND(100.0 * SUM(CASE WHEN p.flight_type = 'INTERNATIONAL' THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_intl
FROM payment_air p
JOIN per_user u ON u.userID = p.userID
WHERE p.reqDate >= DATE '{{ from_date }}' AND p.reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1;
```

### #42. Buyer mới mỗi tuần
**Make clear:** "mới" = transaction đầu tiên **trong data Air kỳ này** (caveat Level 4). Tuần bắt đầu thứ 2?
```sql
WITH first_buy AS (
  SELECT userID, MIN(reqDate) AS first_buy
  FROM payment_air
  GROUP BY 1
)
SELECT date_trunc('week', first_buy) AS wk,
       COUNT(*) AS new_buyers
FROM first_buy
WHERE first_buy >= DATE '2025-12-01' AND first_buy < DATE '2026-03-01'
GROUP BY 1 ORDER BY 1;
```
**Bẫy:** MIN(reqDate) lấy trên TOÀN BỘ data (gồm T12/2024–T1/2025) rồi mới filter window — nếu chỉ scan window thì khách cũ mùa trước sẽ bị đếm nhầm thành "mới".

## Bổ sung Manager View — Level 4 (#60–66)

### #60. VIP (top 10% spend) repeat cao hơn trung bình bao nhiêu? (E68, E81)
**Make clear:** VIP = decile 1 theo TPV trong window? So repeat rate (≥2 đơn) VIP vs phần còn lại.
```sql
WITH per_user AS (
  SELECT userID, SUM(amount) AS user_tpv, COUNT(transID) AS txn
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
),
ranked AS (SELECT *, NTILE(10) OVER (ORDER BY user_tpv DESC) AS decile FROM per_user)
SELECT CASE WHEN decile = 1 THEN 'VIP top 10%' ELSE 'Others' END AS segment,
       COUNT(*) AS users,
       ROUND(100.0 * SUM(CASE WHEN txn >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS repeat_pct
FROM ranked GROUP BY 1;
```
**Bẫy:** VIP repeat cao một phần là tautology (mua nhiều đơn → TPV cao) → đối chiếu thêm decile theo AOV.

### #61. Bao nhiêu % buyer mua từ ≥2 hãng? (E78)
**Make clear:** ⚠ EnViet gom nhiều hãng → "multi-airline" bị méo (1 appID nhưng nhiều hãng thật). Khai báo grain = appID.
```sql
SELECT COUNT(*) AS buyers,
       SUM(CASE WHEN n_app >= 2 THEN 1 ELSE 0 END) AS multi_airline,
       ROUND(100.0 * SUM(CASE WHEN n_app >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_multi
FROM (
  SELECT userID, COUNT(DISTINCT appID) AS n_app
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
) t;
```

### #62. Bao nhiêu % buyer mua từ ≥2 kênh? (E82)
Template #61, thay `appID` → `appUser`.

### #63. Khách quay lại bao lâu mới mua lần 2? (E80)
**Make clear:** coverage ~3 tháng → gap bị **right-censored** (khách sẽ mua lần 2 sau khi hết data không thấy được) — median là cận dưới, phải khai báo.
```sql
WITH ordered AS (
  SELECT userID, reqDate,
         ROW_NUMBER() OVER (PARTITION BY userID ORDER BY reqDate) AS rn
  FROM payment_air
  WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01'
)
SELECT COUNT(*) AS repeat_users,
       approx_percentile(gap_days, 0.5)  AS median_gap_days,
       approx_percentile(gap_days, 0.75) AS p75_gap_days
FROM (
  SELECT o1.userID, date_diff('day', o1.reqDate, o2.reqDate) AS gap_days
  FROM ordered o1
  JOIN ordered o2 ON o2.userID = o1.userID AND o1.rn = 1 AND o2.rn = 2
) t;
```
**Bẫy:** gap nhỏ có thể là mua vé chiều về / mua cho người thân ngay sau đó, không phải "quay lại".

### #64. Top tuyến: % doanh số từ khách repeat (E84)
**Make clear:** repeat = ≥2 đơn toàn Air (mặc định) hay ≥2 đơn cùng route?
```sql
WITH per_user AS (
  SELECT userID, COUNT(transID) AS txn
  FROM payment_air
  WHERE reqDate >= DATE '{{ from_date }}' AND reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
  GROUP BY 1
)
SELECT p.route,
       SUM(p.amount) AS tpv,
       ROUND(100.0 * SUM(CASE WHEN u.txn >= 2 THEN p.amount ELSE 0 END) / SUM(p.amount), 2) AS pct_tpv_repeat
FROM payment_air p
JOIN per_user u ON u.userID = p.userID
WHERE p.reqDate >= DATE '{{ from_date }}' AND p.reqDate < DATE '{{ to_date }}' + INTERVAL '1' DAY
GROUP BY 1 ORDER BY tpv DESC LIMIT {{ top_n }};
```

### #65. Segment nào nên là target chính? (E99)
**Make clear:** segment theo chiều nào (booking_window_group / flight_type / route / appUser)? Ranking = TPV/user × avg MoM growth là công thức **thô** — kết quả là bảng xếp hạng để đọc cùng biz, không phải câu trả lời chiến lược.
```sql
WITH base AS (
  SELECT booking_window_group AS seg,         -- đổi dimension theo chốt với biz
         date_trunc('month', reqDate) AS ym,
         SUM(amount) AS tpv
  FROM payment_air
  WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01'
  GROUP BY 1, 2
),
growth AS (
  SELECT seg, AVG(mom_pct) AS avg_mom_pct
  FROM (
    SELECT seg, ym,
           100.0 * (tpv - LAG(tpv) OVER (PARTITION BY seg ORDER BY ym))
                 / LAG(tpv) OVER (PARTITION BY seg ORDER BY ym) AS mom_pct
    FROM base
  ) t GROUP BY 1
),
val AS (
  SELECT booking_window_group AS seg,
         CAST(SUM(amount) AS DOUBLE) / COUNT(DISTINCT userID) AS tpv_per_user
  FROM payment_air
  WHERE reqDate >= DATE '2025-12-01' AND reqDate < DATE '2026-03-01'
  GROUP BY 1
)
SELECT v.seg, v.tpv_per_user, g.avg_mom_pct
FROM val v LEFT JOIN growth g ON g.seg = v.seg
ORDER BY v.tpv_per_user DESC;
```

### #66. Scenario / sizing (E85, E88, E90, E93) — KHÔNG phải query mới
Số học từ view sẵn, ghi rõ là **ước lượng trần/thô, không phải forecast**:
- **E85** thêm X khách repeat → doanh số tăng ≈ `X × AOV nhóm repeat` (lấy AOV repeat từ #41).
- **E88** sizing last-minute: `SELECT COUNT(transID), SUM(amount) FROM payment_air WHERE booking_window < 7 AND <range reqDate>;` — "tối ưu được bao nhiêu" là giả định biz, data chỉ size segment.
- **E90** top route giảm 10% → tác động ≈ `10% × pct_share route` (share từ #14).
- **E93** invest tuyến X → trần ≈ `(searcher − buyer của route) × CR hiện tại × AOV route` (lấy từ #30 + #19).

---

## Header khai báo — đính kèm mọi câu SQL xuất ra (dạng comment đầu query)

```
Metric: <tên + định nghĩa ngắn, theo ref_zlp_metric_definitions>
Đơn vị đếm: <transaction / unique user / TPV / lượt search>
Thời gian: <range> theo cột <reqDate / search_date / flight_date / departure_date>
Grain: <route tách chiều / city-pair / user / ...>
Filter: <domestic only, provider, ...>
Match rule (nếu join): <window X ngày, cùng user / cùng user+route, anchor first_search>
Assumption: <những gì chưa hỏi được biz và đã tự chọn>
```

**Rule cuối:** khi Trang chạy SQL mà số/lỗi "bất thường" → soát lại query theo thứ tự: (1) literal ngày thiếu `DATE '...'` (lỗi varchar), (2) đơn vị đếm, (3) cột thời gian, (4) quên UPPER(round_type), (5) lẫn giai đoạn T12/2024–T1/2025 vào query join, (6) quên loại Unknown, (7) chia nguyên thiếu CAST AS DOUBLE.
