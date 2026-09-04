# Index intraday / full-cell flash — 2026-09-04 ICT

## Nguyên nhân được xác minh

- `Fetch_Trading_Data(realtime=False, by="5m", period=48, lasted=True)` đi qua
  SDK `GetBarData`, tự đặt `to_date=datetime.now()` theo timezone của host. Railway
  chạy UTC: 09:37 ICT là 02:37 của host. Truy vấn period kết thúc trước giờ mở cửa
  tại Việt Nam; lọc đúng session khiến sparkline rỗng. Không phải frontend vẽ lỗi.
- Kiểm chứng bằng endpoint history production đang có, không đăng nhập FiinQuant thêm:
  VNINDEX 5m `2026-09-04` → cùng date trả `[]`; khoảng `2026-09-04 09:00` → `09:40`
  trả các nến 09:15, 09:20, 09:25, 09:30, 09:35; close lần lượt 1844.51, 1842.96,
  1855.19, 1860.67, 1858.36. Đơn vị index points, giá trị giao dịch VND.
- Frontend poll overview mỗi 5 phút nhưng backend TTL phiên chỉ 60 giây. Đây là
  nguyên nhân refresh bị trễ thường xuyên; STALE không đồng nghĩa mất websocket.
- Log provider báo không có quyền MarketBreadth. Vì vậy số mã tăng/giảm vẫn unavailable;
  không lấy số từ SSI để vá vào dữ liệu FiinQuant, không ép availability thành đầy đủ.

## Thay đổi

- Overview truy vấn 5m bằng khoảng giờ ICT rõ ràng của phiên quan sát được, 09:00 đến
  thời điểm hiện tại (tối đa 15:00). Sau giờ/ngày nghỉ lấy đúng phiên cuối có dữ liệu.
  Không còn period mode cho sparkline, không mở SignalR stream hay tăng universe.
- Giá index chọn observation mới nhất giữa daily snapshot và intraday; không để nến
  5m cũ ghi đè snapshot mới hơn. Totals vẫn là tổng daily, không cộng volume tích lũy
  vào từng nến. Sparkline có provenance/as_of/timeframe riêng.
- Frontend kiểm tra mỗi 15 giây trong phiên, 60 giây ngoài phiên, 2 giây khi shared
  refresh đang chạy. Upstream vẫn bị giới hạn bởi cache/single-flight 60s/300s hiện có.
- Nhãn POLLED và tooltip lý do PARTIAL; STALE vẫn thể hiện cache quá hạn. Một điểm
  thật được vẽ thành dot; thiếu bucket/lunch giữ gap, không tự seed đường từ giá REF.
- Flash nằm trên chính `td`, phủ padding và cả chiều cao ô; 600ms → 1200ms, giữ nền
  đậm trong 35% đầu rồi fade. Timer cleanup, baseline không flash, tick liên tiếp
  restart animation; hỗ trợ reduced-motion.

## Kiểm thử

- Frontend: 311 tests pass; TypeScript (`tsc` trong build) và production build pass.
- Focused backend overview/provider/cache: 18 tests pass. Full backend: **1222 passed,
  21 skipped**, một Starlette deprecation warning. Lượt sandbox đầu không khởi tạo được
  PostgreSQL fixture; chạy lại với quyền local test server đã pass, không dùng DB production.
- Chrome local assets + production REST/WS: tick thật cho `TD`, display table-cell,
  animation 1.2s, cell 94×26px, row 26px; không có span lồng tạo flash chữ. Reduced
  motion animation=none; zero page error/HTTP 5xx. Screenshot `/private/tmp/cw-flash-index-local.png`.
- Theo checklist investigation, xác minh SDK + API trước khi sửa, không suy đoán lỗi
  chart là thiếu entitlement. Checklist React giữ timer cleanup và component ổn định;
  checklist deployment/verification yêu cầu cả API lẫn browser trên production sau merge.
- Không thay secret, database schema, workflow crawl hoặc gọi LLM trong bản này.

## Production

Kết quả deployment và xác minh bốn chart sẽ được ghi sau khi bản bổ sung hoàn tất.
