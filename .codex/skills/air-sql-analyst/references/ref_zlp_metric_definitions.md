---
name: zlp-ota-metric-definitions
description: "Chốt định nghĩa AOV, ARPPU, CR (tracking_session_id) theo chuẩn team Zalopay OTA"
metadata: 
  node_type: memory
  type: reference
  originSessionId: e3962c9a-a4a5-4ab1-97d8-ded53422ceff
---

Định nghĩa metric đã được Trang chốt cứng (override mọi định nghĩa generic):

**AOV (Average Order Value)** = TPV / số lượng transaction. Là giá trị trung bình **1 transaction**, phản ánh package mix. KHÔNG dùng AOV cho góc per-user.
- *Alias:* "giá trị đơn hàng trung bình", "giá trị trung bình mỗi đơn/mỗi giao dịch", "average order value", "basket size", "TPV per transaction", "TPV/txn".

**ARPPU** = TPV / số lượng paying user, định nghĩa **theo life-cycle** — tổng mức chi tiêu trung bình của 1 user trong toàn life-cycle. Luôn khai báo rõ window life-cycle đang xét. Đây là góc "1 user mang về bao nhiêu" (không phải AOV/user).
- *Alias:* "average revenue per paying user", "chi tiêu trung bình mỗi user", "spend per user", "1 user mang về bao nhiêu (tiền)", "doanh thu trung bình trên paying user", "TPV per user".

**ATP (Average Ticket Price / average ticket value)** = tổng TPV / tổng số lượng vé. Giá trị trung bình **1 vé máy bay** (đơn vị = ticket). Air-specific.
- *Alias:* "giá vé trung bình", "giá trung bình 1 vé", "average ticket price/value", "fare trung bình", "TPV per ticket".

**ticket_num** = số lượng vé trong **1 giao dịch** (pax/vé per booking). Roundtrip & booking đoàn → ticket_num cao.
- *Alias:* "số vé mỗi đơn/mỗi giao dịch", "pax", "số khách trong booking", "tickets per booking/transaction", "số lượng vé/đơn".

Quan hệ: **AOV = ATP × ticket_num trung bình/giao dịch**. AOV = TPV/transaction (đơn, có thể nhiều vé); ATP = TPV/ticket (1 vé). AOV tăng mà ATP flat → user mua nhiều vé/đơn hơn, không phải vé đắt hơn.

**booking_window** = departure_date − reqDate (theo ngày). `reqDate` = thời điểm phát sinh giao dịch; `departure_date` = thời điểm cất cánh. Chia nhóm chuẩn: Same day, 1–3D, 4–7D, 8–14D, 15–30D, >30D. (Đây là định nghĩa chốt của team, thay cho lead time generic.)
- *Alias:* "lead time", "đặt trước bao nhiêu ngày", "khoảng cách ngày đặt – ngày bay", "mua trước/book trước X ngày", "advance purchase window".

**route** = cặp điểm đi – điểm đến theo IATA airport code (3 ký tự, vd SGN–HAN). UX nuance: user tìm bằng code / tên sân bay / tên thành phố; **1 thành phố có thể có nhiều sân bay** → khi map city→route phải gom đủ airport của city đó, nên có bảng map `city → [airport codes]` để chuẩn hoá, tránh đếm lệch demand. IATA code ref: https://www.iata.org/en/publications/directories/code-search/
- *Alias:* "chặng", "chặng bay", "tuyến (bay)", "OD pair / origin–destination", "điểm đi – điểm đến", "cặp sân bay".

**CR (Conversion Rate)** = số user vào **step cuối** / số user vào **step đầu**, trong cùng **1 tracking_session_id**. Không tự assume Traffic→Paid; mỗi lần đưa số phải khai báo rõ đo từ step nào đến step nào.
- *Alias:* "conversion", "convert rate", "tỉ lệ chuyển đổi", "funnel CR", "tỉ lệ rớt funnel" (góc ngược = drop-off), "CR step X→Y".
- `tracking_session_id`: 1 user mở app rồi tắt = 1 tracking_session_id; mở nhiều lần → nhiều id.
- CR view này bắt buộc hành vi xảy ra trong cùng 1 lượt mở app (đồng-session) — phải nói rõ điều kiện này khi report.
- Hạn chế: user treo app 1–2 ngày không tắt vẫn tính cùng 1 tracking_session_id → session kéo dài, CR có thể méo.

**PU (Paying User)** = user có phát sinh giao dịch **thành công**.
- *Alias:* "paying user", "user trả tiền", "user có giao dịch (thành công)", "user phát sinh giao dịch".

**MPU (Monthly Paying User)** = user phát sinh giao dịch thành công **trong tháng**.
- *Alias:* "monthly paying user", "PU tháng", "user pay trong tháng", "số user giao dịch theo tháng".

**User segmentation N/F/R (mutually exclusive)** — naming chuẩn team:
- *Alias:* "phân loại user N/F/R", "user mới / new user" (→ hỏi lại: NPU hay FPU?), "khách mới toàn Zalopay" (NPU), "user lần đầu dùng dịch vụ X" (FPU), "user quay lại / returning / repeat user" (RPU), "user trung thành / pay đều" (Consecutive), "user hồi sinh / quay lại sau khi nghỉ / win-back" (Resurrected).
- **NPU** = New Paying User: user phát sinh giao dịch **chủ động** (chi tiền), trả cho dịch vụ **đầu tiên trên toàn Zalopay**.
- **FPU** (exclude NPU) = First Paying User: lần đầu chi tiền cho **1 category hoặc sub_category cụ thể**, nhưng đã từng pay ZLP trước đó.
- **RPU** = Remain Paying User: phát sinh giao dịch **từ lần thứ 2 trở lên** (trên grain đang xét).
  - **Consecutive**: RPU có pay M-1 **và** pay M0.
  - **Resurrected**: RPU **không** pay M-1, pay lại M0.

**Retention Rate (RR)** — period KHÔNG cố định, phải hỏi trước khi tính: tháng→tháng / quý→quý / tuần→tuần. RR30 thường ngầm định là **view monthly** (M→M+1), nhưng đừng tự assume — week/quarter ra số và cách đọc khác hẳn. Đọc theo segment (RR của N = chất lượng acquisition; RR của R = stickiness), không so cross-segment.
- *Alias:* "retention", "tỉ lệ giữ chân", "tỉ lệ quay lại", "RR30 / RR7", "user còn ở lại sau X tháng/tuần", "churn" (góc ngược = 1 − RR).

⚠ BẮT BUỘC hỏi lại user + check hệ thống: N/F/R định nghĩa theo **category** hay **sub_category**? Ra số khác hẳn nhau, đặc biệt FPU.
- Category = nhóm dịch vụ lớn: Telco, OTA, Billing (list đầy đủ feed sau).
- Sub_category = dịch vụ con trong category: OTA→Air/Bus/Train; Telco→topup/data package.
- VD: F theo category OTA → user từng đi Bus rồi mua Air KHÔNG tính FPU. F theo sub_category Air → cùng user đó mua Air lần đầu VẪN tính FPU.

Liên quan: [[project_ota_traffic_funnel]] (funnel Hub Bus & Air dùng intent split has_search/interact/no_interact).
