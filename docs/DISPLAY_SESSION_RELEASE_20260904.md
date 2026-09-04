# Display session / symbol colors — 2026-09-04 ICT

## Phạm vi được yêu cầu

Deploy phần bỏ READY, xử lý vòng đời phiên và đổi màu stock/CW theo giá khớp.
Không đổi secret, không bật crawl, không mở thêm SignalR stream, không gọi LLM trả phí.

## Quy tắc

- 15:00 → trước 08:00 ngày giao dịch kế tiếp: giữ quote/book của phiên gần nhất,
  gắn LAST_SESSION; không gắn live. Cuối tuần/ngày lễ giữ phiên giao dịch gần nhất.
- Từ 08:00 ICT: chuyển display session, xóa intraday state phiên cũ trong canonical
  memory/Redis, fetch REF/CEIL/FLOOR mới. Không xóa snapshot lịch sử trong database.
- Chưa có giao dịch: giá khớp/khối lượng khớp để null, không lấy giá đóng cửa làm
  giao dịch hôm nay và không đổi null thành 0. Book được cập nhật độc lập trong ATO.
- Đồng hồ backend hoạt động độc lập với tick và số client; phát patch rollover và
  status khi phase đổi. Reference refresh dùng single-flight/cooldown đã có.
- Header: PRE-OPEN, ATO, OPEN, LUNCH BREAK, ATC, NEGOTIATED, CLOSED. Trong lúc chưa
  nhận status hiển thị SYNCING thay vì đoán CLOSED. LIVE/STALE/OFFLINE giữ riêng.
- Giữ các ranh giới 09:00, 09:15, 11:30, 13:00, 14:30, 14:45, 15:00 và holiday calendar.

## Frontend

- Watchlist và STATS dùng chung resolved quote; selection ngoài Watchlist cũng được
  resolve. Frontend AI context đọc cùng quote, không lấp null bằng CW quote khác phiên.
- Merge trade/book/reference theo session và timestamp; book không làm trade cũ live,
  event đến muộn không ghi đè REST observation mới hơn. Nghỉ trưa/đóng cửa giữ quan sát
  mới nhất thay vì quay về REST snapshot lúc mở trang.
- Tab mở qua 08:00 tự invalidate REST data; phase change cũng invalidate. REST active
  refresh 30 giây hỗ trợ symbol không có WS slot; không tạo thêm upstream subscription.
- SYMBOL và TRD_PRC cùng classifier: tăng xanh, giảm đỏ, tham chiếu vàng, trần tím,
  sàn cyan; chưa có giá/reference thì neutral. Trần/sàn chỉ từ bands thật, không suy diễn
  ±7% cho CW. STATS giữ change của resolved quote, không tự tính lại từ REF khác phiên.

## Kiểm thử trước deploy

- Backend full suite: **1220 passed, 21 skipped**; một Starlette deprecation warning.
- Frontend full suite: **308 passed**; typecheck/build pass sau thay đổi header cuối cùng.
- Browser kiểm tra stock HPG và CW CHPG2617, hai tab + reload, dùng local build với REST/
  WebSocket production thật. Lúc 09:16 ICT: HPG 21.700, volume 192.600, +100/+0,46%,
  TRD_AMT 100; Watchlist/STATS cùng số. CHPG2617 có book 420/430, chưa có trade thì null.
- Browser lượt cuối lúc 09:18 ICT xác nhận hai tab sau reload đều OPEN/LIVE, READY biến mất,
  Watchlist/STATS cùng số, màu SYMBOL/TRD_PRC trùng nhau. Thời gian từ navigation đến
  REST + WS/UI sẵn sàng: 0,50–1,39 giây; không page error hoặc HTTP 5xx. Không coi tốc độ
  một lượt đo là cam kết latency. Screenshot: `/private/tmp/cw-session-local.png`.
- Đồng hồ 08:00, cuối tuần/ngày lễ, overnight restore và book-only ATO được kiểm tra bằng
  injected time; chưa trải qua mốc 08:00/15:00 thật sau deployment trong ngày này.
- Theo checklist verification, tách REST hydration khỏi WebSocket readiness và kiểm tra
  cả hai trước nghiệm thu. agent-browser CLI không có sẵn; dùng Chrome/Playwright thay thế.
- Checklist React: effect/timer có cleanup, hook không conditional, giữ một WS owner,
  không tạo subscription upstream theo tab hoặc theo symbol selection.

## Giới hạn còn lại

- Legacy HPG snapshot 2026-09-03 không khớp daily RAW history vẫn cần EOD reconciliation;
  bản này không sửa lại dữ liệu cũ hoặc ép snapshot khớp history.
- TRADED LOGS chưa được nối dữ liệu. Không thuộc thay đổi vòng đời phiên/màu lần này.
- CEIL/FLOOR CW và MarketBreadth có thể unavailable do dữ liệu/entitlement; không suy diễn.
- Chưa kiểm chứng LLM response/prompt cuối cùng; chỉ sửa nguồn quote của context frontend.

## Production

- PR #27 đã merge thành `21a3b7f`, backend Railway `feca8e66-beaa-47a2-9286-5141efe5ae09`
  SUCCESS và frontend Vercel `dpl_FPwGNY2aK8sgGb7DJuuzLNjZBT7B` Ready.
- Domain production được kiểm tra lúc 09:31 ICT bằng hai tab HPG/CHPG2617 và reload:
  READY không còn; OPEN/LIVE; Watchlist/STATS cùng giá, volume và change; SYMBOL cùng màu
  TRD_PRC; không page error/HTTP 5xx. HPG 21.700, volume 1.028.600, TRD_AMT 300, +100/+0,46%.
- Health: Redis connected, 288 writes/84 restores, zero write/restore errors; feed LIVE,
  30/30 subscriptions, decode/reconnect/quant failure counters bằng 0 tại thời điểm kiểm tra.
