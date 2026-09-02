import { useMarketOverview, type IndexOverview, type VolumeLeader } from "@/data/query/use_market_overview";
import { DASH, fmtPrice, fmtVol } from "@/components/common/grid_table";

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

function Sparkline({ values, direction }: { values: number[]; direction: number | null }) {
  if (values.length < 2) return <div className="overview-spark-empty">NO INTRADAY SERIES</div>;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const points = values.map((v, i) => `${i / (values.length - 1) * 100},${30 - (v - min) / span * 25}`).join(" ");
  return <svg className="overview-spark" role="img" aria-label="Intraday index path" viewBox="0 0 100 32" preserveAspectRatio="none">
    <line x1="0" y1="16" x2="100" y2="16" stroke="var(--border-32)" strokeDasharray="2 2" />
    <polyline points={points} fill="none" stroke={tone(direction)} strokeWidth="1.3" vectorEffect="non-scaling-stroke" />
  </svg>;
}

function IndexCard({ item }: { item: IndexOverview }) {
  const prefix = item.change != null && item.change > 0 ? "+" : "";
  return <article className="index-card mono" aria-label={`${item.symbol} index overview`}>
    <Sparkline values={item.sparkline || []} direction={item.change} />
    <div className="index-card-main">
      <strong className="heading">{item.symbol}</strong>
      <span style={{ color: tone(item.change) }}>{number(item.value)} <small>{prefix}{number(item.change)} ({prefix}{item.change_percent == null ? DASH : `${item.change_percent.toFixed(2)}%`})</small></span>
    </div>
    <div className="index-card-line"><span>VOL {compact(item.volume)}</span><span>VAL {compact(item.trading_value)}</span></div>
    <div className="index-card-breadth">
      <span style={{ color: "var(--up)" }}><DirectionTriangle color="var(--up)" /> {number(item.advancing)} <small style={{ color: "var(--price-ceiling)" }}>({number(item.ceiling)})</small></span>
      <span style={{ color: "var(--flat)" }}>― {number(item.unchanged)}</span>
      <span style={{ color: "var(--down)" }}><DirectionTriangle down color="var(--down)" /> {number(item.declining)} <small style={{ color: "var(--price-floor)" }}>({number(item.floor)})</small></span>
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
        <span>{index + 1}. <b style={{ color: marketTone(row.market_state) }}>{row.symbol}</b></span><span>{fmtVol(row.volume)}</span><span style={{ color: marketTone(row.market_state) }}>{fmtPrice(row.price)}</span>
      </div>)}
    </div>
  </section>;
}

export function MarketOverviewStrip({ indicesOnly = false }: { indicesOnly?: boolean }) {
  const query = useMarketOverview();
  if (query.isLoading) return <div className="market-overview-state mono">LOADING MARKET OVERVIEW…</div>;
  if (!query.data) return <div className="market-overview-state mono">MARKET OVERVIEW UNAVAILABLE</div>;
  const data = query.data;
  const indices = ORDER.map(symbol => data.indices.find(x => x.symbol === symbol) ?? ({ symbol, value: null, change: null, change_percent: null, volume: null, trading_value: null, advancing: null, ceiling: null, unchanged: null, declining: null, floor: null, as_of: null, sparkline: [] }));
  return <div className={`market-overview-wrap${indicesOnly ? " indices-only" : ""}`}>
    <div className="index-viewer">{indices.map(item => <IndexCard item={item} key={item.symbol} />)}</div>
    {!indicesOnly && <div className="top-exchange-viewer">
      <LeaderTable title="Top Stock Trading Volume" rows={data.top_stock_volume} />
      <LeaderTable title="Top Covered Warrants Trading Volume" rows={data.top_cw_volume} />
    </div>}
  </div>;
}
