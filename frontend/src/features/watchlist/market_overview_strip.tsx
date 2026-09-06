import { useLayoutEffect, useRef } from "react";
import { useMarketOverview, type IndexOverview, type VolumeLeader } from "@/data/query/use_market_overview";
import { DASH, fmtPrice, fmtVol } from "@/components/common/grid_table";
import { PolledRealtimeValue, RollingNumber } from "@/components/common/realtime_value";
import { introChart, prefersReducedMotion, spring } from "@/design/motion";

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

function DirectionTriangle({ down = false, color, pulseKey }: { down?: boolean; color: string; pulseKey?: number | null }) {
  const ref = useRef<SVGSVGElement>(null);
  const prev = useRef(pulseKey);
  useLayoutEffect(() => {
    const had = prev.current;
    prev.current = pulseKey;
    const el = ref.current;
    if (had == null || pulseKey == null || had === pulseKey) return;
    if (!el || prefersReducedMotion() || typeof el.animate !== "function") return;
    el.animate([{ transform: "scale(1.4)" }, { transform: "scale(1)" }], spring("snap"));
  }, [pulseKey]);
  return <svg ref={ref} className="overview-direction-icon" aria-hidden="true" viewBox="0 0 12 12" fill={color}>
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
 * observed 5-minute bar (the rest of the axis stays empty). The Y domain is centered on
 * the session reference so its dashed line sits in the vertical middle of the chart; the
 * path itself is colored per-point against that reference — green while above it, red
 * at/below it — with the color flipping exactly where the line crosses (interpolated, not
 * just at the nearest sample).
 */
export function Sparkline({ values, reference }: { values: IndexOverview["sparkline"]; reference?: number | null }) {
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
  // Symmetric around the reference (not a plain min/max fit) so its line always lands
  // exactly in the middle, regardless of which way the session has been trending.
  let min: number, max: number;
  if (ref != null) {
    const spread = Math.max(...seriesValues.map(v => Math.abs(v - ref)), 1e-6);
    min = ref - spread;
    max = ref + spread;
  } else {
    min = Math.min(...seriesValues);
    max = Math.max(...seriesValues);
  }
  const span = max - min || 1;
  const y = (v: number) => 30 - ((v - min) / span) * 25;
  const colorFor = (v: number) => ref == null ? "var(--t-60)" : v >= ref ? "var(--up)" : "var(--down)";

  // First split on time gaps (a missing 5m bucket breaks the line, except the lunch break,
  // which is bridged), then split each of those further at every reference crossing.
  const timeSegments: (typeof points)[] = [[]];
  points.forEach((p, i) => {
    const prev = points[i - 1];
    const isLunchBridge = prev && prev.min <= LUNCH_START_MIN + 5 && p.min >= LUNCH_END_MIN - 5;
    if (i > 0 && p.min - prev.min > 7.5 && !isLunchBridge) timeSegments.push([]);
    timeSegments[timeSegments.length - 1].push(p);
  });
  const colorSegments: { pts: string; color: string; isPoint?: boolean }[] = [];
  for (const seg of timeSegments) {
    if (seg.length === 1) {
      const p = seg[0];
      colorSegments.push({
        pts: `${points.length === 1 ? 50 : p.x},${y(p.value)}`,
        color: colorFor(p.value), isPoint: true,
      });
      continue;
    }
    let run: string[] = [`${seg[0].x},${y(seg[0].value)}`];
    let runColor = colorFor(seg[0].value);
    for (let i = 1; i < seg.length; i++) {
      const prev = seg[i - 1], p = seg[i];
      const curColor = colorFor(p.value);
      if (curColor !== runColor && ref != null) {
        const t = (ref - prev.value) / (p.value - prev.value);
        const crossing = `${prev.x + t * (p.x - prev.x)},${y(ref)}`;
        run.push(crossing);
        colorSegments.push({ pts: run.join(" "), color: runColor });
        run = [crossing];
        runColor = curColor;
      }
      run.push(`${p.x},${y(p.value)}`);
    }
    colorSegments.push({ pts: run.join(" "), color: runColor });
  }
  const referenceY = ref == null ? null : y(ref);
  const hourTicks = [10, 11, 13, 14]
    .map(h => `M${((h * 60 - SESSION_OPEN_MIN) / SESSION_SPAN_MIN) * 100} 0V30`)
    .join("");
  return <>
    <svg className="overview-spark" role="img" aria-label="Intraday index path" viewBox="0 0 100 32" preserveAspectRatio="none">
      <path className="overview-spark-grid" d={hourTicks} stroke="var(--border-32)" strokeWidth="0.4" fill="none" />
      {referenceY != null && <line x1="0" y1={referenceY} x2="100" y2={referenceY} stroke="var(--t-46)" strokeDasharray="2 2" />}
      {colorSegments.map((seg, i) => seg.isPoint
        ? <circle key={i} cx={seg.pts.split(",")[0]} cy={seg.pts.split(",")[1]} r="1" fill={seg.color} />
        : <polyline key={i} points={seg.pts} fill="none" stroke={seg.color} strokeWidth="1.3" vectorEffect="non-scaling-stroke" />)}
    </svg>
    {ref != null && referenceY != null && (
      <span className="overview-spark-ref" style={{ top: `${(referenceY / 32) * 100}%` }}>
        REF {number(ref)}
      </span>
    )}
  </>;
}

/** Nominal width of one 5-minute bucket on the 0–100 session axis. */
const VOL_SLOT_W = (5 / SESSION_SPAN_MIN) * 100;

/** Traded volume as one bar per realized 5-minute bar — the same points the index line is
 *  drawn from — on the sparkline's fixed 09:00–15:00 ICT x-axis, so each bar sits directly
 *  under its point on the line. Bars are scaled to the busiest bar of the session; the axis
 *  stays empty past the latest bar, matching the line. */
export function IntradayVolume({ values }: { values: IndexOverview["sparkline"] }) {
  const bars = values
    .map(item => {
      if (typeof item === "number") return null;
      const mins = ictMinutes(item.timestamp);
      if (mins == null) return null;
      const x = ((mins - SESSION_OPEN_MIN) / SESSION_SPAN_MIN) * 100;
      if (!Number.isFinite(x)) return null;
      return { mins, x: Math.min(100, Math.max(0, x)), volume: Math.max(0, item.volume ?? 0) };
    })
    .filter((b): b is { mins: number; x: number; volume: number } => b !== null)
    .sort((a, b) => a.mins - b.mins);

  if (!bars.length || !bars.some(b => b.volume > 0)) {
    return <div className="index-hourvol is-empty" aria-hidden="true" />;
  }
  const peak = Math.max(...bars.map(b => b.volume), 1);
  const w = VOL_SLOT_W * 0.82;
  return (
    <svg className="index-hourvol" role="img" viewBox="0 0 100 32" preserveAspectRatio="none"
      aria-label="Traded volume per 5-minute bar, 09:00–15:00 ICT">
      {bars.map((b, i) => {
        const h = b.volume > 0 ? Math.max(1.4, (b.volume / peak) * 30) : 0;
        return <rect key={i} x={Math.max(0, b.x - w / 2)} y={32 - h} width={w} height={h} />;
      })}
    </svg>
  );
}

function IndexCard({ item }: { item: IndexOverview }) {
  const prefix = item.change != null && item.change > 0 ? "+" : "";
  const sessionKey = item.as_of?.slice(0, 10) ?? null;

  // Chart intro on first paint and on session rollover only — never on the 15s poll.
  const cardRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    cardRef.current
      ?.querySelectorAll(".overview-spark, .index-hourvol")
      .forEach(introChart);
  }, [sessionKey]);
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
  return <article ref={cardRef} className="index-card mono" aria-label={`${item.symbol} index overview`}>
    <div className="overview-spark-wrap">
      <Sparkline values={item.sparkline || []} reference={item.reference} />
      {tag && <span className={`overview-spark-tag${item.stale ? " is-stale" : ""}`} title={tagTitle}>{tag}</span>}
    </div>
    <IntradayVolume values={item.sparkline || []} />
    <div className="index-card-main">
      <strong className="heading">{item.symbol}</strong>
      <span style={{ color: tone(item.change) }}>
        <RollingNumber value={item.value} display={number(item.value)} resetKey={sessionKey} />{" "}
        <small>
          <PolledRealtimeValue value={item.change} resetKey={sessionKey}>{prefix}{number(item.change)}</PolledRealtimeValue>{" "}(
          <PolledRealtimeValue value={item.change_percent} resetKey={sessionKey}>{prefix}{item.change_percent == null ? DASH : `${item.change_percent.toFixed(2)}%`}</PolledRealtimeValue>)
        </small>
      </span>
    </div>
    <div className="index-card-line"><span>VOL <PolledRealtimeValue value={item.volume} resetKey={sessionKey}>{compact(item.volume)}</PolledRealtimeValue></span><span>VAL <PolledRealtimeValue value={item.trading_value} resetKey={sessionKey}>{compact(item.trading_value)}</PolledRealtimeValue></span></div>
    <div className="index-card-breadth">
      <span style={{ color: "var(--up)" }}><DirectionTriangle color="var(--up)" pulseKey={item.advancing} /> <PolledRealtimeValue value={item.advancing} resetKey={sessionKey}>{number(item.advancing)}</PolledRealtimeValue> <PolledRealtimeValue as="small" value={item.ceiling} resetKey={sessionKey} style={{ color: "var(--price-ceiling)" }}>({number(item.ceiling)})</PolledRealtimeValue></span>
      <span style={{ color: "var(--flat)" }}>― <PolledRealtimeValue value={item.unchanged} resetKey={sessionKey}>{number(item.unchanged)}</PolledRealtimeValue></span>
      <span style={{ color: "var(--down)" }}><DirectionTriangle down color="var(--down)" pulseKey={item.declining} /> <PolledRealtimeValue value={item.declining} resetKey={sessionKey}>{number(item.declining)}</PolledRealtimeValue> <PolledRealtimeValue as="small" value={item.floor} resetKey={sessionKey} style={{ color: "var(--price-floor)" }}>({number(item.floor)})</PolledRealtimeValue></span>
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
