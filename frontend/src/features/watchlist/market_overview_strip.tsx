import { useMarketOverview, type IndexOverview, type VolumeLeader } from "@/data/query/use_market_overview";
import { DASH, fmtPrice, fmtVol } from "@/components/common/grid_table";
import { PolledRealtimeValue } from "@/components/common/realtime_value";

const ORDER = ["VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND"];
const number = (value: number | null | undefined) => value == null ? DASH : value.toLocaleString("en-US", { maximumFractionDigits: 2 });
const compact = (value: number | null | undefined) => {
  if (value == null) return DASH;
  if (Math.abs(value) >= 1e12) return `${(value / 1e12).toFixed(2)}T`;
  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  return fmtVol(value);
};
const tone = (n: number | null | undefined) => n == null ? "var(--t-50)" : n > 0 ? "var(--up)" : n < 0 ? "var(--down)" : "var(--flat)";
const marketTone = (state: VolumeLeader["market_state"]) => {
  if (state === "CEILING") return "var(--price-ceiling)";
  if (state === "FLOOR") return "var(--price-floor)";
  if (state === "REFERENCE") return "var(--flat)";
  if (state === "UP") return "var(--up)";
  if (state === "DOWN") return "var(--down)";
  return "var(--t-50)";
};

function DirectionTriangle({ down = false, color }: { down?: boolean; color: string }) {
  return <svg className="overview-direction-icon" aria-hidden="true" viewBox="0 0 12 12" fill={color}>
    <path d={down ? "M1 2h10L6 11Z" : "M1 10h10L6 1Z"} />
  </svg>;
}

/** HOSE continuous session runs 09:00–15:00 ICT; x maps onto that fixed window. */
const SESSION_OPEN_MIN = 9 * 60;
const SESSION_CLOSE_MIN = 15 * 60;
const SESSION_SPAN_MIN = SESSION_CLOSE_MIN - SESSION_OPEN_MIN;
const LUNCH_START_MIN = 11 * 60 + 30;
const LUNCH_END_MIN = 13 * 60;
const ICT_FMT = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit", hour12: false,
});

/** Minutes since 00:00 ICT for an ISO timestamp, or null. */
function ictMinutes(ts: string): number | null {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  const parts = ICT_FMT.formatToParts(d);
  const h = Number(parts.find(p => p.type === "hour")?.value);
  const m = Number(parts.find(p => p.type === "minute")?.value);
  return Number.isFinite(h) && Number.isFinite(m) ? h * 60 + m : null;
}

/**
 * Intraday index path on a **fixed 09:00–15:00 ICT axis**, drawn only up to the latest
 * observed 5-minute bar (the rest of the axis stays empty). A dashed line marks the
 * session reference so direction reads at a glance.
 */
export function Sparkline({ values, direction, reference }: { values: IndexOverview["sparkline"]; direction: number | null; reference?: number | null }) {
  const points = values.map((item, index) => {
    if (typeof item === "number") {
      // Legacy plain-number series: spread evenly across the session window.
      const frac = values.length <= 1 ? 0.5 : index / (values.length - 1);
      return { value: item, x: frac * 100, min: index, reference };
    }
    const mins = ictMinutes(item.timestamp);
    const x = mins == null ? null : ((mins - SESSION_OPEN_MIN) / SESSION_SPAN_MIN) * 100;
    return { value: item.value, x, min: mins, reference: item.reference ?? reference };
  })
    .filter((p): p is { value: number; x: number; min: number; reference: number | null | undefined } =>
      p.x != null && Number.isFinite(p.x) && Number.isFinite(p.value))
    .map(p => ({ ...p, x: Math.min(100, Math.max(0, p.x)) }))
    .sort((a, b) => a.min - b.min);
  if (!points.length) return <div className="overview-spark-empty">NO INTRADAY SERIES</div>;
  const seriesValues = points.map(p => p.value);
  const ref = points.find(p => p.reference != null)?.reference ?? reference ?? null;
  const domain = ref == null ? seriesValues : [...seriesValues, ref];
  const min = Math.min(...domain), max = Math.max(...domain), span = max - min || 1;
  const y = (v: number) => 30 - ((v - min) / span) * 25;
  const segments: string[][] = [[]];
  points.forEach((p, i) => {
    // A missing 5m bucket breaks the line — EXCEPT the 11:30–13:00 lunch break, which is
    // bridged (a near-flat connector) so the morning and afternoon paths read as one session.
    const prev = points[i - 1];
    const isLunchBridge = prev && prev.min <= LUNCH_START_MIN + 5 && p.min >= LUNCH_END_MIN - 5;
    if (i > 0 && p.min - prev.min > 7.5 && !isLunchBridge) segments.push([]);
    segments[segments.length - 1].push(`${points.length === 1 ? 50 : p.x},${y(p.value)}`);
  });
  const referenceY = ref == null ? null : y(ref);
  const hourTicks = [10, 11, 13, 14]
    .map(h => `M${((h * 60 - SESSION_OPEN_MIN) / SESSION_SPAN_MIN) * 100} 0V30`)
    .join("");
  return <svg className="overview-spark" role="img" aria-label="Intraday index path" viewBox="0 0 100 32" preserveAspectRatio="none">
    <path className="overview-spark-grid" d={hourTicks} stroke="var(--border-32)" strokeWidth="0.4" fill="none" />
    {referenceY != null && <line x1="0" y1={referenceY} x2="100" y2={referenceY} stroke="var(--border-32)" strokeDasharray="2 2" />}
    {segments.map((pts, i) => pts.length === 1
      ? <circle key={i} cx={pts[0].split(",")[0]} cy={pts[0].split(",")[1]} r="1" fill={tone(direction)} />
      : <polyline key={i} points={pts.join(" ")} fill="none" stroke={tone(direction)} strokeWidth="1.3" vectorEffect="non-scaling-stroke" />)}
  </svg>;
}

function IndexCard({ item }: { item: IndexOverview }) {
  const prefix = item.change != null && item.change > 0 ? "+" : "";
  const sessionKey = item.as_of?.slice(0, 10) ?? null;
  const reasons = item.partial_reasons?.map(reason => ({
    BREADTH_UNAVAILABLE: "Market breadth unavailable (advancing/declining counts)",
    INTRADAY_UNAVAILABLE: "No intraday observations for this session",
    PRICE_UNAVAILABLE: "Index price unavailable", REFERENCE_UNAVAILABLE: "Session reference unavailable",
  }[reason] ?? reason)).join("; ");
  const asOf = item.as_of
    ? new Date(item.as_of).toLocaleTimeString("en-GB", { timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit" })
    : null;
  const tag = item.stale ? "STALE" : asOf;
  const tagTitle = [
    "Index path — 5-minute bars, 09:00–15:00 ICT.",
    asOf ? `As of ${asOf} ICT.` : "",
    reasons,
    item.stale ? "Snapshot overdue for refresh." : "",
  ].filter(Boolean).join(" ");
  return <article className="index-card mono" aria-label={`${item.symbol} index overview`}>
    <div className="overview-spark-wrap">
      <Sparkline values={item.sparkline || []} direction={item.change} reference={item.reference} />
      {tag && <span className={`overview-spark-tag${item.stale ? " is-stale" : ""}`} title={tagTitle}>{tag}</span>}
    </div>
    <div className="index-card-main">
      <strong className="heading">{item.symbol}</strong>
      <span style={{ color: tone(item.change) }}>
        <PolledRealtimeValue value={item.value} resetKey={sessionKey}>{number(item.value)}</PolledRealtimeValue>{" "}
        <small>
          <PolledRealtimeValue value={item.change} resetKey={sessionKey}>{prefix}{number(item.change)}</PolledRealtimeValue>{" "}(
          <PolledRealtimeValue value={item.change_percent} resetKey={sessionKey}>{prefix}{item.change_percent == null ? DASH : `${item.change_percent.toFixed(2)}%`}</PolledRealtimeValue>)
        </small>
      </span>
    </div>
    <div className="index-card-line"><span>VOL <PolledRealtimeValue value={item.volume} resetKey={sessionKey}>{compact(item.volume)}</PolledRealtimeValue></span><span>VAL <PolledRealtimeValue value={item.trading_value} resetKey={sessionKey}>{compact(item.trading_value)}</PolledRealtimeValue></span></div>
    <div className="index-card-breadth">
      <span style={{ color: "var(--up)" }}><DirectionTriangle color="var(--up)" /> <PolledRealtimeValue value={item.advancing} resetKey={sessionKey}>{number(item.advancing)}</PolledRealtimeValue> <PolledRealtimeValue as="small" value={item.ceiling} resetKey={sessionKey} style={{ color: "var(--price-ceiling)" }}>({number(item.ceiling)})</PolledRealtimeValue></span>
      <span style={{ color: "var(--flat)" }}>― <PolledRealtimeValue value={item.unchanged} resetKey={sessionKey}>{number(item.unchanged)}</PolledRealtimeValue></span>
      <span style={{ color: "var(--down)" }}><DirectionTriangle down color="var(--down)" /> <PolledRealtimeValue value={item.declining} resetKey={sessionKey}>{number(item.declining)}</PolledRealtimeValue> <PolledRealtimeValue as="small" value={item.floor} resetKey={sessionKey} style={{ color: "var(--price-floor)" }}>({number(item.floor)})</PolledRealtimeValue></span>
    </div>
  </article>;
}

function LeaderTable({ title, rows }: { title: string; rows: VolumeLeader[] }) {
  const peak = Math.max(...rows.map(r => r.volume), 1);
  return <section className="leader-panel mono">
    <div className="leader-title"><span className="heading">{title}</span></div>
    <div className="leader-head"><span>SYMBOL</span><span>VOLUME</span><span>TRD_PRC</span></div>
    <div className="leader-rows">
      {rows.length === 0 ? <div className="overview-unavailable">DATA UNAVAILABLE</div> : rows.map((row, index) => <div className="leader-row" key={row.symbol}>
        <i style={{ width: `${Math.max(3, row.volume / peak * 100)}%` }} />
        <span>{index + 1}. <b style={{ color: marketTone(row.market_state) }}>{row.symbol}</b></span><span><PolledRealtimeValue value={row.volume} resetKey={row.as_of?.slice(0, 10)}>{fmtVol(row.volume)}</PolledRealtimeValue></span><span><PolledRealtimeValue value={row.price} resetKey={row.as_of?.slice(0, 10)} style={{ color: marketTone(row.market_state) }}>{fmtPrice(row.price)}</PolledRealtimeValue></span>
      </div>)}
    </div>
  </section>;
}

export function MarketOverviewStrip({ indicesOnly = false }: { indicesOnly?: boolean }) {
  const query = useMarketOverview();
  if (query.isLoading) return <div className="market-overview-state mono">LOADING MARKET OVERVIEW…</div>;
  if (!query.data) return <div className="market-overview-state mono">MARKET OVERVIEW UNAVAILABLE</div>;
  const data = query.data;
  if (data.availability === "UNAVAILABLE" && data.indices.length === 0) {
    return <div className="market-overview-state mono">{data.refreshing ? "MARKET OVERVIEW UPDATING…" : "MARKET OVERVIEW UNAVAILABLE"}</div>;
  }
  const indices = ORDER.map(symbol => data.indices.find(x => x.symbol === symbol) ?? ({ symbol, value: null, change: null, change_percent: null, volume: null, trading_value: null, advancing: null, ceiling: null, unchanged: null, declining: null, floor: null, as_of: null, sparkline: [] }));
  return <div className={`market-overview-wrap${indicesOnly ? " indices-only" : ""}`}>
    <div className="index-viewer">{indices.map(item => <IndexCard item={item} key={item.symbol} />)}</div>
    {!indicesOnly && <div className="top-exchange-viewer">
      <LeaderTable title="Top Stock Trading Volume" rows={data.top_stock_volume} />
      <LeaderTable title="Top Covered Warrants Trading Volume" rows={data.top_cw_volume} />
    </div>}
  </div>;
}
