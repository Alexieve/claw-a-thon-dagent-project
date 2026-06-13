---
name: rules-effective-data-request
description: "Quy tắc viết request/prompt hiệu quả khi hỏi data Air/OTA — cho người đặt câu hỏi (Trang + biz). Kèm catalog view chuẩn trên 2 dashboard."
metadata:
  type: reference
---

# Rules: Viết request hiệu quả — Air/OTA

> Vai: file này cho **người đặt câu hỏi**. Phía trả lời (Claude/analyst) dùng [[rules-biz-request-to-view-query]]. Định nghĩa metric theo [[zlp-ota-metric-definitions]] — override mọi định nghĩa generic.

Mục tiêu: request tự khai báo đủ thông tin ngay lần đầu → 0 vòng hỏi-lại, 0 assume sai.

---

## PHẦN A — Cho Trang (bản kỹ thuật)

### A1. Quy trình 3 bước trước khi gửi prompt

1. **Check catalog view chuẩn (mục A4) trước.** Câu hỏi trả lời được bằng view có sẵn → không request query mới, chỉ ghi: `View <tên view>, dashboard <traffic/payment>, filter <...>`. Số sẽ khớp dashboard, không lệch nguồn.
2. **Không có view sẵn → viết request theo template 7 slot (A2).** Request mới phải mô tả theo đúng cấu trúc của view chuẩn: **metric × dimension × filter (+ cột thời gian)** — để sau này promote thành view dashboard được ngay.
3. **Yêu cầu Claude khai báo lại header** (metric, đơn vị đếm, time column, grain, filter, assumption) **trước khi chạy**. Header lệch ý → sửa trước, không đợi ra số.

### A2. Template request chuẩn — 7 slot

```
[Metric + đơn vị đếm] theo [dimension/grain]
nguồn [search_air / payment_air / join]
thời gian [range] tính theo cột [ymd / search_date / flight_date / departure_date]
route [tách chiều / gộp 2 chiều / city-pair]
filter [domestic/intl, OneWay/RoundTrip, hãng, ...]
output [bảng top N / chart / 1 con số / % share]
(tham chiếu view chuẩn nếu format giống: "giống view X trên dash Y")
```

Ví dụ chuẩn (đã chốt):
> "Top **10** route theo **số transaction** (kèm paying user đối chiếu), bảng **payment_air**, theo **ngày mua** (`ymd`) 01/12/2025–28/02/2026, route **tách chiều**, **domestic only**, output: bảng + % share — giống view 'Route' trên dash payment."

### A3. Ba khóa an toàn — 3 lỗi đau nhất, bắt buộc khai báo trong mọi request

| # | Khóa | Phải ghi rõ | Nếu bỏ trống sẽ sai kiểu gì |
|---|------|-------------|------------------------------|
| 1 | **Đơn vị đếm** | transaction / paying user (unique) / lượt search / unique searcher / TPV / ticket | 12.887 giao dịch nhưng chỉ 8.623 user — top theo transaction ≠ top theo user |
| 2 | **Cột thời gian** | ngày mua `ymd` / ngày search `search_date` / ngày bay `flight_date`·`departure_date` | "Tháng 2" theo ngày mua khác hẳn theo ngày bay (booking_window có thể >60 ngày) |
| 3 | **Định nghĩa metric** | CR: step đầu→step cuối; RR: period nào; AOV/ATP/ARPPU: per đơn/vé/user + window; N/F/R: category hay sub_category | Claude dùng định nghĩa generic thay vì bản chốt của team → số đúng công thức nhưng sai nghĩa |

Từ cấm dùng trần (không kèm đơn vị): *phổ biến, bán chạy, nhiều, tốt, tăng trưởng, khách*. Luôn quy về 1 trong các đơn vị ở khóa 1.

### A4. Catalog view chuẩn (baseline — 2 dashboard đang dùng)

**Dashboard 1 — OTA Search Traffic** (nguồn `search_air`; filter chung: product_line, search_time, flight_type):

| View | Metric | Dimension / time column |
|------|--------|--------------------------|
| User Search by Search Date | unique searcher | `search_date` |
| User Search by Departure Date | unique searcher | `departure_date` |
| Search Hour in Day | lượt search | hour(`activity_time`) |
| Search Day in Week | lượt search | `search_day_in_week` |
| Departure Day in Week | lượt search | `departure_day_in_week` |
| Route | unique searcher | `route` (tách chiều) |
| Destination | unique searcher | `dest` |
| Route Percentage | % share searcher | `route` |

**Dashboard 2 — Payment** (nguồn `payment_air`; filter chung: flight_type, round_type, in_out_bound; click line/value để filter nhanh theo hãng):

| View | Metric | Dimension / time column |
|------|--------|--------------------------|
| Overview Countdown (Tết YoY) | transaction | days-to-Tết, so Tết 2026 vs Tết 2025 |
| Countdown theo hãng (Vietjet / VNA) | transaction | days-to-Tết × provider |
| Transaction / Paying User by Payment Date | transaction; unique paying user | `ymd` × provider |
| Transaction / Paying User by Departure Date | transaction; unique paying user | `flight_date` × provider |
| Transaction by Weekday (bảng) | transaction + paying user | day_in_week |
| Transaction by Day in Week / by Hour | transaction | day_in_week / hour × provider |
| Route / Destination (bảng) | transaction + paying user | `route` / `dest` (tách chiều) |
| Route Percentage | % share transaction | `route` |

Quy ước: **demand = traffic dash (search), thực mua = payment dash**. Request phải nói rõ đang hỏi phía nào; so sánh demand↔thực mua = join 2 bảng, là request mới (không có view sẵn).

---

## PHẦN B — Form cho biz (không thuật ngữ)

Biz điền 5 câu, gửi nguyên form. Thiếu câu nào, người chạy số sẽ hỏi lại đúng câu đó.

```
1. Muốn biết con số gì?
   ☐ Số đơn đặt vé   ☐ Số khách mua (mỗi khách đếm 1 lần)
   ☐ Số tiền         ☐ Lượt tìm kiếm (chưa chắc đã mua)

2. Khoảng thời gian nào? Từ ___ đến ___
   Tính theo:  ☐ ngày khách ĐẶT/MUA vé   ☐ ngày khách BAY   ☐ ngày khách TÌM KIẾM

3. Xem chặng bay kiểu nào?
   ☐ Có hướng (SGN→HAN khác HAN→SGN)   ☐ Gộp 2 chiều thành 1 cặp
   ☐ Theo thành phố (1 thành phố có thể nhiều sân bay)

4. Lọc gì không?
   ☐ Chỉ nội địa  ☐ Cả quốc tế | ☐ Vé 1 chiều  ☐ Khứ hồi  ☐ Cả hai | Hãng: ___

5. Nhận kết quả dạng gì?
   ☐ Bảng top ___ (ghi rõ top bao nhiêu)  ☐ Biểu đồ theo thời gian  ☐ 1 con số tổng
```

Ví dụ điền: *"Số đơn đặt vé, 01/12/2025–28/02/2026 theo ngày khách MUA, chặng có hướng, chỉ nội địa cả 1 chiều lẫn khứ hồi, bảng top 10."*

---

## C. Ví dụ dịch: câu hỏi mơ hồ → request chuẩn

| Biz hỏi | Request chuẩn |
|---------|----------------|
| "Top chặng bay phổ biến nhất?" | Top 10 route theo transaction (kèm paying user), payment_air, theo `ymd` <range>, tách chiều, domestic — *hoặc nếu hỏi nhu cầu:* theo unique searcher, search_air |
| "Tết này bán chạy không?" | Transaction theo `ymd`, payment_air, so countdown days-to-Tết 2026 vs 2025 — có sẵn: view Overview Countdown |
| "Khách hay đặt vé lúc nào?" | Hỏi lại: giờ trong ngày / thứ trong tuần / sát ngày bay bao nhiêu (booking_window)? Mỗi cách là 1 view khác nhau |
| "Giá vé trung bình bao nhiêu?" | ATP (TPV/ticket) hay AOV (TPV/transaction)? + range theo `ym`, + domestic/intl |
| "Tỷ lệ chuyển đổi search→mua?" | Không phải CR session chuẩn — đây là join search↔payment theo user: khai báo window match (search trước mua bao nhiêu ngày), match cùng route hay chỉ cùng user |
| "Dạo này khách quay lại không?" | RR period nào (M→M / W→W)? Segment N/F/R theo category hay sub_category? Window nào? |

---

## D. Quy tắc chốt

1. Request không đủ 3 khóa an toàn (A3) → coi như chưa request, đừng chạy.
2. Số đưa ra ngoài luôn kèm header khai báo (metric, đơn vị, time column, grain, filter, assumption).
3. View nào bị hỏi lặp ≥3 lần → đề xuất promote lên dashboard, thêm vào catalog A4.
4. Catalog A4 là living doc — dashboard đổi thì update file này trước, hỏi số sau.
