# Audit Watchlist → STATS → chart — 2026-09-04 ICT

> Đây là kết quả audit lúc 08:54 ICT, trước bản sửa tiếp theo. Các thay đổi và kết quả
> kiểm chứng mới được theo dõi trong `DISPLAY_SESSION_RELEASE_20260904.md`; findings
> dưới đây được giữ nguyên như bằng chứng tại thời điểm audit.

## Kết luận

**Chưa đạt tính nhất quán dữ liệu giữa các màn hình.** Reload/cache đã hoạt động, nhưng
không đồng nghĩa dữ liệu được hòa giải giữa snapshot, history và quote WebSocket.
Có hai lỗi ưu tiên P1, hai lỗi/thiếu sót P2 và một giới hạn entitlement bên provider.
Không cần đợi vào phiên để xử lý các P1 này.

Phạm vi lượt này: audit read-only production và sửa riêng việc bỏ nhãn `READY`.
Không sửa database, không chạy crawl, không gọi LLM trả phí, không thay logic market data,
không push hoặc deploy thay đổi mới trong lượt audit.

## Bằng chứng browser/API

Story: người dùng chọn HPG trên Watchlist → panel lấy quote/STATS và daily history →
người dùng kỳ vọng các số có cùng session và provenance, dữ liệu có sẵn không bị mất ở panel.

Chạy Chrome tại `https://cw-research-terminal.vercel.app/?symbol=HPG` lúc
`2026-09-04T08:54:17+07:00`, phase `PRE_OPEN`. Không có JavaScript page error.

| Nơi hiển thị/nguồn | Giá HPG | Volume | Session / nguồn |
|---|---:|---:|---|
| Watchlist / dashboard REST | 21.650 | 9.472.000 | 2026-09-03, `SNAPSHOT_FINAL`, không có `asOf` của trade |
| STATS / WebSocket snapshot | unavailable | unavailable | 2026-09-04, chỉ có reference group |
| Chart / daily history RAW | 21.600 | 27.036.617 | 2026-09-03, `FIINQUANT`, `adjusted=false` |
| REF hiển thị trên Watchlist/STATS | 21.600 | không áp dụng | 2026-09-04, `SESSION_REFERENCE` |

Dashboard trace: `SNAPSHOT_FAST`, `B:SNAPSHOT(FINAL)`, `A:SESSION_REFERENCE_STATIC`.
Daily history cùng ngày có OHLC 22.000 / 22.000 / 21.550 / 21.600.
WebSocket gửi HPG với `Traded=null`, `Total_Vol=null`, bid/ask null, nhưng REF/CEIL/FLOOR
có giá trị. REST dashboard và history đều HTTP 200.

Screenshot audit: `/private/tmp/cw-audit-instrument-flow.png`.

## Findings theo mức ưu tiên

### P1 — Quote WebSocket thiếu trường che mất snapshot ở STATS và context phía frontend

**Vị trí:** `frontend/src/features/warrant_info/instrument_panel.tsx:192`,
`frontend/src/features/market_overview/market_explorer.tsx:68` và `:91`.

Panel dùng `instrument?.quote ?? cw?.quote ?? dashRow?.quote`. Toán tử này chọn cả object,
không đánh giá availability của từng nhóm. Object WebSocket chứa reference nhưng trade/book
trống vẫn được chọn, khiến `dashRow.quote` đã có last price/volume không bao giờ được dùng.
Đây là nguyên nhân trực tiếp của STATS trống trong ảnh, không phải API history chưa tải.

Context được frontend chuẩn bị cho AI cũng đọc `selected.quote`/`cw.quote` thay vì resolved
dashboard row; có cùng nguy cơ thiếu giá/volume dù bảng đã có số. Audit chưa gọi LLM và
không kết luận về prompt cuối cùng sau mọi bước xử lý ở backend.

**Hướng sửa:** dùng một resolved instrument view chung cho Watchlist, STATS, quant và AI;
merge theo nhóm quote/book/reference/analytics với session/as-of, không đơn giản lấy
giá trị non-null bất kỳ. Symbol chọn từ Research nhưng chưa nằm trong Watchlist cũng phải
được đưa vào tập symbol cần resolve. Thêm regression cho reference-only WS + LAST_SESSION
dashboard, book-only ATO và snapshot sau reload.

### P1 — Snapshot nhanh được giữ nguyên dù không khớp daily history cùng phiên

**Vị trí:** `backend/app/market_data/market_snapshot_resolver.py:384`.

Nhánh dashboard trả ngay khi snapshot có `last_price`; không có đối chiếu trong nhánh này.
HPG được gắn `SNAPSHOT_FINAL` của 2026-09-03 với 21.650 / 9.472.000, trong khi history RAW
cùng phiên trả 21.600 / 27.036.617. Giá và volume đều lệch nên không thể kết luận chỉ là
khác price basis; history đang được yêu cầu `adjusted=false`. Trade `asOf` của snapshot
không được trả, làm giảm khả năng xác minh đây có thực sự là số cuối phiên.

Chưa truy vấn bản ghi gốc/captured_at trong PostgreSQL, nên **chưa khẳng định nguồn nào
sai hoặc thời điểm snapshot được ghi**. Đây là finding về việc chưa reconcile và thiếu
bằng chứng freshness, không phải kết luận provider sai.

**Hướng sửa:** giữ fast hydration nhưng thực hiện EOD reconciliation riêng ở background;
xác minh session, timestamp, quality và phạm vi volume/value trước khi promote snapshot
thành final. Với dữ liệu legacy không đủ timestamp, giữ trạng thái/confidence rõ ràng.
Không ép hai nguồn bằng cách nhân volume hoặc thay giá tùy ý.

### P2 — REF và +/- không cùng phiên; STATS còn bỏ mất trường change có sẵn

**Vị trí:** `backend/app/market_data/market_snapshot_resolver.py:380` và `:473`,
`frontend/src/features/warrant_info/instrument_panel.tsx:259`,
`frontend/src/components/common/quote_columns.ts:101`.

Dashboard đang có REF 21.600 của 04/09 nhưng trade/change của 03/09:
trade 21.650, change −450, percent −2,04%. Backend có provenance theo nhóm, tuy nhiên UI
đặt các số cạnh nhau và tô màu giá theo REF mới mà không làm rõ hai phiên ở vùng hiển thị.
Vì vậy giá màu xanh có thể đứng cạnh change âm; không được tự sửa change thành +50 mà
không quyết định và công bố reference/session dùng để so sánh.

Ngoài ra `stats` không truyền `q.priceChange` vào thuộc tính `change`. Khi quote được
hydrate, `quoteCell` có thể tự tính `last - ref` trong STATS trong khi Watchlist dùng
change quan sát được. Chỉ sửa thứ tự quote ở P1 sẽ chưa giải quyết hết sự lệch này.

**Hướng sửa:** quyết định một temporal contract rõ cho display; dùng chung change và
reference provenance, hiển thị session/as-of và unavailable khi không thể so sánh hợp lệ.

### P2 — TRADED LOGS chưa được nối dữ liệu kể cả trong phiên

**Vị trí:** `frontend/src/features/warrant_info/instrument_panel.tsx:116`.

`TimeSalesPanel` chỉ render header và chuỗi thông báo. Khi `live=true`, nội dung vẫn là
`Live trade feed not yet wired — pending backend support.` Không có danh sách trade để
render. Vì vậy đợi vào phiên không tự làm tính năng này hoạt động.

**Hướng sửa:** nếu tiếp tục triển khai, dùng event giao dịch thực tế từ stream owner hiện có,
bounded buffer/dedup và timestamp rõ ràng; không thêm SignalR stream và không dựng traded
logs từ daily volume hoặc quote snapshot.

## Entitlement và những phần không coi là bug trong audit này

- Log production ghi `You do not have permission to access MarketBreadth` và HTTP 403 cho
  API stock profile `GetOrganizationsByGroupCodeAndIcbCode`. Đây là lỗi quyền của lần gọi
  hiện tại; chưa thể khẳng định nâng gói là cách duy nhất nếu chưa kiểm tra entitlement/API.
- `PARTIAL`/`STALE`, dấu `—` cho dữ liệu thiếu và không có TRD_AMT legacy là các trạng thái
  hợp lệ. Không nên thay chúng bằng 0 hoặc số suy đoán để UI trông đầy đủ.
- Audit chưa nghiệm thu ATO, khớp lệnh thật, ATC, reconnect hoặc tính đúng của mọi analytics.

## Thay đổi đã thực hiện: bỏ READY

- `frontend/src/components/common/app_header.tsx`: bỏ nhãn và chấm trạng thái feed khi
  upstream đã kết nối nhưng thị trường không active. Giữ `CLOSED` và các trạng thái
  `LIVE`, `STALE`, `OFFLINE`, `CONNECTING`, `RECONNECTING` có ý nghĩa.
- Giữ nguyên mã `READY` ở protocol/backend client; chỉ thay trình bày UI.
- Thêm bốn regression cases trong `frontend/src/__tests__/live_status_semantics.test.ts`.
- Full frontend: **286 tests pass / 36 files**; typecheck và production build pass.
- Chưa commit/push/deploy thay đổi READY trong lượt này. Screenshot audit là production
  trước thay đổi, không phải bằng chứng READY đã bị bỏ trên production.

Checklist full-story verification đã giúp xác định điểm đứt ở response → selected view;
audit dừng ở các nguyên nhân có bằng chứng, không tiếp tục thay cấu hình hoặc dữ liệu prod.
Browser audit dùng Chrome/Playwright sẵn có vì CLI agent-browser không được cài.
