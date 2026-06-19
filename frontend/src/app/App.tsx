import { useState, useMemo, useEffect, useRef } from "react";
import { Topbar } from "./Topbar";
import { PanelTitle } from "./PanelTitle";
import { TableView } from "@/tables/core/TableView";
import { stockTable } from "@/tables/stock/StockTable";
import { posMasterTable } from "@/tables/info/PosMasterTable";
import { type PosColumnGroup, POS_GROUP_META } from "@/tables/info/PosMasterTable";
import { rtTradesTable } from "@/tables/info/RtTradesTable";
import { holidayTable } from "@/tables/info/HolidayTable";
import { dividendTable } from "@/tables/info/DividendTable";
import { useEquityData } from "@/data/useEquityData";
import { colors } from "@/design/tokens";
import { DisplayOptionContent } from "@/tables/core/DisplayOptionContent";
import { TableFilterContent } from "@/tables/core/TableFilterContent";

const getUnderlying = (symbol: string): string => {
  const sym = symbol.toUpperCase();
  if (sym.length === 3) return sym;
  if (sym.startsWith("C") && sym.length >= 8) {
    return sym.substring(1, 4);
  }
  return sym;
};

const VN30_SYMBOLS = [
  "ACB", "BCM", "BID", "CTG", "DGC", "FPT", "GAS", "GVR", "HDB", "HPG", "LPB", "MBB", "MSN", "MWG", "PLX", "SAB", "SHB", "SSB", "SSI", "STB", "TCB", "TPB", "VCB", "VHM", "VIC", "VIB", "VJC", "VNM", "VPB", "VRE", "VPL"
];

type ViewMode = "equity" | "info";

export function App() {
  const { rows, lastChanges, serverTimeOffset, getRow, lastUpdateTs } = useEquityData();
  const [viewMode, setViewMode] = useState<ViewMode>("equity");
  const [hiddenColumns, setHiddenColumns] = useState<string[]>([]);
  const [infoHiddenColumns, setInfoHiddenColumns] = useState<string[]>([]);
  const [tradesHiddenColumns, setTradesHiddenColumns] = useState<string[]>([]);

  const [posRowsMM, setPosRowsMM] = useState<any[]>([]);
  const [posRowsHedge, setPosRowsHedge] = useState<any[]>([]);
  const [loadingPos, setLoadingPos] = useState(false);
  const [posError, setPosError] = useState<string | null>(null);
  const [posColumnGroup, setPosColumnGroup] = useState<PosColumnGroup>("overview");

  const [tradesRows, setTradesRows] = useState<any[]>([]);
  const [loadingTrades, setLoadingTrades] = useState(false);
  const [tradesError, setTradesError] = useState<string | null>(null);

  const [holidayRows, setHolidayRows] = useState<any[]>([]);
  const [loadingHolidays, setLoadingHolidays] = useState(false);
  const [holidaysError, setHolidaysError] = useState<string | null>(null);

  const [dividendRows, setDividendRows] = useState<any[]>([]);
  const [loadingDividends, setLoadingDividends] = useState(false);
  const [dividendsError, setDividendsError] = useState<string | null>(null);

  // ── Info Tab Table Filters States ──────────────────────────────────
  const [posFilter, setPosFilter] = useState<{ underlyings: string[]; fromDate: string; toDate: string }>({ underlyings: ["All"], fromDate: "", toDate: "" });
  const [tradesFilter, setTradesFilter] = useState<{ underlyings: string[]; fromDate: string; toDate: string }>({ underlyings: ["All"], fromDate: "", toDate: "" });
  const [holidayFilter, setHolidayFilter] = useState<{ underlyings: string[]; fromDate: string; toDate: string }>({ underlyings: ["All"], fromDate: "", toDate: "" });
  const [dividendFilter, setDividendFilter] = useState<{ underlyings: string[]; fromDate: string; toDate: string }>({ underlyings: ["All"], fromDate: "", toDate: "" });

  const toggleColumn = (key: string) => {
    setHiddenColumns((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };
  const resetColumns = () => setHiddenColumns([]);
  const unselectAllColumns = () => setHiddenColumns(stockTable.getColumns().map(c => c.key));

  const toggleInfoColumn = (key: string) => {
    setInfoHiddenColumns((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };
  const resetInfoColumns = () => setInfoHiddenColumns([]);
  const unselectAllInfoColumns = () => setInfoHiddenColumns(posMasterTable.getColumns().map(c => c.key));

  const toggleTradesColumn = (key: string) => {
    setTradesHiddenColumns((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };
  const resetTradesColumns = () => setTradesHiddenColumns([]);
  const unselectAllTradesColumns = () => setTradesHiddenColumns(rtTradesTable.getColumns().map(c => c.key));



  useEffect(() => {
    if (viewMode !== "info") return;

    let isMounted = true;
    let initialLoadPos = true;
    let initialLoadTrades = true;

    const fetchPosMaster = () => {
      if (initialLoadPos) {
        setLoadingPos(true);
        setPosError(null);
      }
      Promise.all([
        fetch('/api/pos-master?subAccountNo=0001922095').then((res) => {
          if (!res.ok) throw new Error("Failed to fetch MM position master data.");
          return res.json();
        }),
        fetch('/api/pos-master?subAccountNo=0001115688').then((res) => {
          if (!res.ok) throw new Error("Failed to fetch Hedging position master data.");
          return res.json();
        })
      ])
        .then(([dataMM, dataHedge]) => {
          if (!isMounted) return;
          const mappedMM = dataMM.map((r: any) => ({ ...r, Symbol: r.ticker }));
          const mappedHedge = dataHedge.map((r: any) => ({ ...r, Symbol: r.ticker }));
          setPosRowsMM(mappedMM);
          setPosRowsHedge(mappedHedge);
          if (initialLoadPos) {
            setLoadingPos(false);
            initialLoadPos = false;
          }
        })
        .catch((err) => {
          if (!isMounted) return;
          console.error("Error fetching pos_master:", err);
          setPosError(err.message || "Could not load positions from database.");
          setLoadingPos(false);
        });
    };

    const fetchRtTrades = () => {
      if (initialLoadTrades) {
        setLoadingTrades(true);
        setTradesError(null);
      }
      fetch("/api/rt-trades")
        .then((res) => {
          if (!res.ok) throw new Error("Failed to fetch realtime trades.");
          return res.json();
        })
        .then((data) => {
          if (!isMounted) return;
          const mappedData = data.map((r: any) => ({ ...r, Symbol: r.symbol }));
          setTradesRows(mappedData);
          if (initialLoadTrades) {
            setLoadingTrades(false);
            initialLoadTrades = false;
          }
        })
        .catch((err) => {
          if (!isMounted) return;
          console.error("Error fetching rt_trades:", err);
          setTradesError(err.message || "Could not load trades from database.");
          setLoadingTrades(false);
        });
    };

    // Initial fetches
    setLoadingHolidays(true);
    setHolidaysError(null);
    setLoadingDividends(true);
    setDividendsError(null);

    fetchPosMaster();
    fetchRtTrades();

    fetch("/api/holidays")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch holiday data.");
        return res.json();
      })
      .then((data: any[]) => {
        if (!isMounted) return;
        setHolidayRows(data);
        setLoadingHolidays(false);
      })
      .catch((err) => {
        if (!isMounted) return;
        console.error("Error fetching holidays:", err);
        setHolidaysError(err.message || "Could not load holidays.");
        setLoadingHolidays(false);
      });

    fetch("/api/dividends")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch dividend data.");
        return res.json();
      })
      .then((data: any[]) => {
        if (!isMounted) return;
        setDividendRows(data);
        setLoadingDividends(false);
      })
      .catch((err) => {
        if (!isMounted) return;
        console.error("Error fetching dividends:", err);
        setDividendsError(err.message || "Could not load dividends.");
        setLoadingDividends(false);
      });

    // Start silent 2-second background polling for database data updates
    const pollInterval = setInterval(() => {
      fetchPosMaster();
      fetchRtTrades();
    }, 2000);

    return () => {
      isMounted = false;
      clearInterval(pollInterval);
    };
  }, [viewMode]);

  const filteredTableData = useMemo(() => {
    return rows.filter(r => VN30_SYMBOLS.includes(r.Symbol));
  }, [rows]);

  // Standard normal cumulative distribution function (cnd)
  function cnd(x: number): number {
    const a1 = 0.319381530;
    const a2 = -0.356563782;
    const a3 = 1.781477937;
    const a4 = -1.821255978;
    const a5 = 1.330274429;
    const L = Math.abs(x);
    const K = 1.0 / (1.0 + 0.2316419 * L);
    let w = 1.0 - 1.0 / Math.sqrt(2.0 * Math.PI) * Math.exp(-L * L / 2.0) * (a1 * K + a2 * K * K + a3 * Math.pow(K, 3) + a4 * Math.pow(K, 4) + a5 * Math.pow(K, 5));
    if (x < 0) {
      w = 1.0 - w;
    }
    return w;
  }

  // Probability Density Function of standard normal distribution (nd_pdf)
  function nd_pdf(x: number): number {
    return (1.0 / Math.sqrt(2.0 * Math.PI)) * Math.exp(-x * x / 2.0);
  }

  // Black-Scholes Call Option Price
  function bsCallPrice(S: number, K: number, t: number, r: number, sigma: number): number {
    if (t <= 0) return Math.max(0, S - K);
    const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * t) / (sigma * Math.sqrt(t));
    const d2 = d1 - sigma * Math.sqrt(t);
    return S * cnd(d1) - K * Math.exp(-r * t) * cnd(d2);
  }

  // Black-Scholes Call Option Vega
  function bsCallVega(S: number, K: number, t: number, r: number, sigma: number): number {
    if (t <= 0) return 0.0;
    const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * t) / (sigma * Math.sqrt(t));
    return S * Math.sqrt(t) * nd_pdf(d1);
  }

  // Black-Scholes Call Option Delta
  function bsCallDelta(S: number, K: number, t: number, r: number, sigma: number): number {
    if (t <= 0) return S >= K ? 1.0 : 0.0;
    const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * t) / (sigma * Math.sqrt(t));
    return cnd(d1);
  }



  const calculateLivePosRows = (rowsList: any[], isHedging: boolean = false) => {
    return rowsList.map((row) => {
      // ── CW Warrant live price ──────────────────────────────────────────────
      // getRow() reads from rowsMapRef directly (always latest tick, never stale).
      // Guard: only apply if Ref > 0 (skip zero-filled initial snapshots before first KB tick).
      const liveWarrant = getRow(row.ticker.toUpperCase());

      let lastPrcT = row.last_prc_t !== null ? parseFloat(row.last_prc_t) : null;
      let lastPrcT1 = row.last_prc_t_1 !== null ? parseFloat(row.last_prc_t_1) : null;
      let netChgPct = row.net_chg_pct !== null ? parseFloat(row.net_chg_pct) : null;

      if (liveWarrant && liveWarrant.Ref && liveWarrant.Ref > 0) {
        // LastPrc(T)  = Traded price when matched; otherwise Ref (yesterday's close from KB)
        // LastPrc(T-1)= Ref (yesterday's reference price from KB — e.g. CACB2606 = 660)
        lastPrcT = liveWarrant.Traded && liveWarrant.Traded > 0 ? liveWarrant.Traded : liveWarrant.Ref;
        lastPrcT1 = liveWarrant.Ref;
        if (lastPrcT1 > 0) {
          netChgPct = (lastPrcT / lastPrcT1) - 1;
        }
      }

      // ── Spot_Prc(S) — per-account logic ───────────────────────────────────
      // MM account (isHedging=false): CW-focused. Spot_Prc(S) = CW's own LastPrc(T),
      //   i.e. the same live warrant price already computed above.
      // Hedging account (isHedging=true): Stock-focused. Spot_Prc(S) = the stock
      //   ticker's own live price (via getRow(ticker)), not the underlying of a CW.
      let spotPrcS = row.spot_prc_s !== null ? parseFloat(row.spot_prc_s) : null;
      if (!isHedging) {
        // MM: Spot_Prc(S) mirrors LastPrc(T) (CW live price)
        if (lastPrcT !== null) {
          spotPrcS = lastPrcT;
        }
      } else {
        // Hedging: Spot_Prc(S) = direct stock live price from WebSocket
        const liveStock = getRow(row.ticker.toUpperCase());
        if (liveStock && liveStock.Ref && liveStock.Ref > 0) {
          spotPrcS = liveStock.Traded && liveStock.Traded > 0
            ? liveStock.Traded
            : liveStock.Ref;
        }
      }

      // 1. Get Live Inputs from row (with safe fallbacks)
      const balance = row.balance !== null ? parseInt(row.balance, 10) : 0;
      const balanceT1 = row.balance_t_1 !== null ? parseInt(row.balance_t_1, 10) : 0;
      const soldQty = row.sold_qty !== null ? parseInt(row.sold_qty, 10) : 0;
      const soldAmt = row.sold_amt !== null ? parseFloat(row.sold_amt) : 0;
      const boughtQty = row.bought_qty !== null ? parseInt(row.bought_qty, 10) : 0;
      const boughtAmt = row.bought_amt !== null ? parseFloat(row.bought_amt) : 0;

      // 2. Derived trade averages
      const soldAvg = soldQty > 0 ? soldAmt / soldQty : 0;
      const boughtAvg = boughtQty > 0 ? boughtAmt / boughtQty : 0;

      // Parse options parameters
      const strikeK = row.strike_k !== null ? parseFloat(row.strike_k) : null;
      const tteT = row.tte_t !== null ? parseFloat(row.tte_t) : null;
      const tteT1 = row.tte_t_1 !== null ? parseFloat(row.tte_t_1) : null;
      const rate = row.rate !== null ? parseFloat(row.rate) : 0.0725;
      const sigma = row.hedge_v_t !== null ? parseFloat(row.hedge_v_t) : 0.3250;

      // Conversion Ratio (CVR) parsing
      let ratioNum = 1;
      if (row.cvr) {
        const parts = row.cvr.split(":");
        const num = parseFloat(parts[0]);
        if (!isNaN(num) && num > 0) {
          ratioNum = num;
        }
      }

      // Compute spot prices
      const spotS_t = spotPrcS !== null ? spotPrcS : (strikeK || 0);
      let spotS_t_1 = spotS_t;
      if (row.und_ticker) {
        const liveUnderlying = getRow(row.und_ticker.toUpperCase());
        if (liveUnderlying && liveUnderlying.Ref && liveUnderlying.Ref > 0) {
          spotS_t_1 = liveUnderlying.Ref;
        }
      }

      // Compute theoretical warrant prices & sensitivities
      let theoPrcT = 0;
      let theoPrcT1 = 0;
      let vegaPctT = 0;
      let thetaT = 0;

      if (strikeK && tteT !== null && tteT1 !== null) {
        theoPrcT = bsCallPrice(spotS_t, strikeK, tteT, rate, sigma) / ratioNum;
        theoPrcT1 = bsCallPrice(spotS_t_1, strikeK, tteT1, rate, sigma) / ratioNum;
        vegaPctT = bsCallVega(spotS_t, strikeK, tteT, rate, sigma) / ratioNum;
        // Daily Theta decay using finite difference: bsCallPrice(newT) - bsCallPrice(T)
        const newT = Math.max(tteT - 1 / 365, 0.0001);
        thetaT = (bsCallPrice(spotS_t, strikeK, newT, rate, sigma) - bsCallPrice(spotS_t, strikeK, tteT, rate, sigma)) / ratioNum;
      }

      // 3. Option sensitivities
      const deltaT = row.delta_t !== null ? parseFloat(row.delta_t) : 0;
      const deltaLotsT = deltaT * balance;
      const deltaCashT = spotS_t * deltaLotsT;
      const deltaCashT1 = deltaT * balanceT1 * spotS_t_1;

      const trdDeltaLotsT = deltaT * (boughtQty - soldQty);
      const trdDeltaCashT = trdDeltaLotsT * spotS_t;

      const cashVegaT = vegaPctT * balance;
      const cashThetaT = thetaT * balance;

      // 4. MTM Position & Trading PnL
      const positionPnlMtm = (lastPrcT !== null && lastPrcT1 !== null)
        ? balanceT1 * (lastPrcT - lastPrcT1)
        : 0;

      const absSoldAvg = Math.abs(soldAvg);
      const absBoughtAvg = boughtAvg;

      let tradingPnlMtm = 0;
      if (lastPrcT !== null) {
        if (soldQty > 0 && boughtQty > 0) {
          const minQty = Math.min(soldQty, boughtQty);
          const matchedPnl = minQty * (absSoldAvg - absBoughtAvg);

          let unmatchedPnl = 0;
          if (soldQty >= boughtQty) {
            unmatchedPnl = (soldQty - boughtQty) * (absSoldAvg - lastPrcT);
          } else {
            unmatchedPnl = (boughtQty - soldQty) * (lastPrcT - absBoughtAvg);
          }
          tradingPnlMtm = matchedPnl + unmatchedPnl;
        } else if (soldQty > 0) {
          tradingPnlMtm = soldQty * (absSoldAvg - lastPrcT);
        } else if (boughtQty > 0) {
          tradingPnlMtm = boughtQty * (lastPrcT - absBoughtAvg);
        }
      }
      const totalPnlMtm = positionPnlMtm + tradingPnlMtm;

      // 5. Theoretical Position & Trading PnL
      const positionPnlTheo = balanceT1 * (theoPrcT - theoPrcT1);

      let tradingPnlTheo = 0;
      if (soldQty > 0 && boughtQty > 0) {
        const minQty = Math.min(soldQty, boughtQty);
        const matchedPnl = minQty * (absSoldAvg - absBoughtAvg);

        let unmatchedPnl = 0;
        if (soldQty >= boughtQty) {
          unmatchedPnl = (soldQty - boughtQty) * (absSoldAvg - theoPrcT);
        } else {
          unmatchedPnl = (boughtQty - soldQty) * (theoPrcT - absBoughtAvg);
        }
        tradingPnlTheo = matchedPnl + unmatchedPnl;
      } else if (soldQty > 0) {
        tradingPnlTheo = soldQty * (absSoldAvg - theoPrcT);
      } else if (boughtQty > 0) {
        tradingPnlTheo = boughtQty * (theoPrcT - absBoughtAvg);
      }
      const totalPnlTheo = positionPnlTheo + tradingPnlTheo;

      // 6. Taylor Series PnL attributions
      // Calculate yesterday's and today's Greeks for attributions
      let gammaAmtPctT1 = 0;
      let thetaT1 = 0;
      const sigmaT1 = row.hedge_v_t_1 !== null ? parseFloat(row.hedge_v_t_1) : 0.3250;

      if (strikeK && tteT1 !== null) {
        // Gamma yesterday
        const delta_up_1 = bsCallDelta(spotS_t_1 * 1.0001, strikeK, tteT1, rate, sigmaT1);
        const delta_down_1 = bsCallDelta(spotS_t_1 * 0.9999, strikeK, tteT1, rate, sigmaT1);
        const gammaOption_1 = (delta_up_1 - delta_down_1) / 0.0002;
        gammaAmtPctT1 = gammaOption_1 / ratioNum;

        // Theta yesterday
        const newT1 = Math.max(tteT1 - 1 / 365, 0.0001);
        thetaT1 = (bsCallPrice(spotS_t_1, strikeK, newT1, rate, sigmaT1) - bsCallPrice(spotS_t_1, strikeK, tteT1, rate, sigmaT1)) / ratioNum;
      }

      // Calculate m-decay fraction for thetapnl
      const now = new Date();
      const ictTime = now.getTime() + (7 * 60 * 60 * 1000);
      const ictDate = new Date(ictTime);
      const hours = ictDate.getUTCHours();
      const minutes = ictDate.getUTCMinutes();
      const seconds = ictDate.getUTCSeconds();
      const nowFraction = (hours * 3600 + minutes * 60 + seconds) / 86400;
      const timeStart = 34200 / 86400; // 9:30 AM
      const timeEnd = 53400 / 86400;   // 2:50 PM
      const m = Math.max(0, Math.min(1, (nowFraction - timeStart) / (timeEnd - timeStart)));

      const stockReturn = spotS_t_1 > 0 ? (spotS_t - spotS_t_1) / spotS_t_1 : 0;
      const deltaPnl = deltaCashT1 * stockReturn;
      const gammaPnl = 0.5 * Math.pow(stockReturn, 2) * Math.pow(spotS_t, 2) * gammaAmtPctT1 * balanceT1;

      // thetapnl = average(Theta(T-1), Theta(T)) * DailyDecay
      const thetaPnl = 0.5 * (thetaT1 + thetaT) * balanceT1 * m;

      // vegapnl is pre-calculated using dynamic vol traded and saved in the database
      const vegaPnl = row.vega_pnl !== null ? parseFloat(row.vega_pnl) : 0;

      const unexplainedPnl = 0.00;

      // Cumulative session PnLs
      const totalPnlTheoCum = totalPnlTheo;
      const totalPnlMtmCum = totalPnlMtm;

      return {
        ...row,
        last_prc_t: lastPrcT !== null ? String(lastPrcT) : null,
        last_prc_t_1: lastPrcT1 !== null ? String(lastPrcT1) : null,
        net_chg_pct: netChgPct !== null ? String(netChgPct) : null,
        spot_prc_s: spotPrcS !== null ? String(spotPrcS) : null,

        balance_t_1: balanceT1,
        balance: balance,
        sold_qty: soldQty,
        sold_amt: soldAmt,
        sold_avg: soldAvg,
        bought_qty: boughtQty,
        bought_amt: boughtAmt,
        bought_avg: boughtAvg,

        theo_prc_t: theoPrcT,
        theo_prc_t_1: theoPrcT1,
        delta_lots_t: deltaLotsT,
        delta_cash_t: deltaCashT,
        delta_cash_t_1: deltaCashT1,
        trd_delta_lots_t: trdDeltaLotsT,
        trd_delta_cash_t: trdDeltaCashT,
        vega_pct_t: vegaPctT,
        cash_vega_t: cashVegaT,
        theta_t: thetaT,
        cash_theta_t: cashThetaT,

        position_pnl_mtm: positionPnlMtm,
        trading_pnl_mtm: tradingPnlMtm,
        total_pnl_mtm: totalPnlMtm,

        position_pnl_theo: positionPnlTheo,
        trading_pnl_theo: tradingPnlTheo,
        total_pnl_theo: totalPnlTheo,

        delta_pnl: deltaPnl,
        gamma_pnl: gammaPnl,
        theta_pnl: thetaPnl,
        vega_pnl: vegaPnl,
        unexplained_pnl: unexplainedPnl,

        total_pnl_theo_cum: totalPnlTheoCum,
        total_pnl_mtm_cum: totalPnlMtmCum,
      };
    });
  };

  // MM account: Spot_Prc(S) = CW's own LastPrc(T)
  const livePosRowsMM = useMemo(() => calculateLivePosRows(posRowsMM, false), [posRowsMM, getRow, lastUpdateTs]);
  // Hedging account: Spot_Prc(S) = stock ticker's own live price
  const livePosRowsHedge = useMemo(() => calculateLivePosRows(posRowsHedge, true), [posRowsHedge, getRow, lastUpdateTs]);

  const livePosRows = useMemo(() => {
    return [...livePosRowsMM, ...livePosRowsHedge];
  }, [livePosRowsMM, livePosRowsHedge]);

  // ── PosMaster flash tracking ───────────────────────────────────────────────
  // Tracks previous last_prc_t and spot_prc_s per CW ticker to determine flash
  // direction (up/down) on each realtime tick, using the "ticker:colKey" format
  // expected by TableView's currentFlashes map.
  const posMasterPrevPricesRef = useRef<Map<string, { lastPrcT: number | null; spotPrc: number | null }>>(new Map());

  const mmContainerRef = useRef<HTMLDivElement>(null);
  const hedgeContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mmEl = mmContainerRef.current;
    const hedgeEl = hedgeContainerRef.current;
    if (!mmEl || !hedgeEl) return;

    let isSyncingMM = false;
    let isSyncingHedge = false;

    const handleScrollMM = () => {
      if (isSyncingMM) {
        isSyncingMM = false;
        return;
      }
      isSyncingHedge = true;
      hedgeEl.scrollLeft = mmEl.scrollLeft;
    };

    const handleScrollHedge = () => {
      if (isSyncingHedge) {
        isSyncingHedge = false;
        return;
      }
      isSyncingMM = true;
      mmEl.scrollLeft = hedgeEl.scrollLeft;
    };

    mmEl.addEventListener("scroll", handleScrollMM, { passive: true });
    hedgeEl.addEventListener("scroll", handleScrollHedge, { passive: true });

    return () => {
      mmEl.removeEventListener("scroll", handleScrollMM);
      hedgeEl.removeEventListener("scroll", handleScrollHedge);
    };
  }, [viewMode, posRowsMM, posRowsHedge, loadingPos]);

  const posMasterChanges = useMemo(() => {
    const changes = new Map<string, "up" | "down">();
    for (const row of livePosRows) {
      const ticker: string = row.ticker;
      const newLastPrcT = row.last_prc_t !== null && row.last_prc_t !== undefined
        ? parseFloat(String(row.last_prc_t)) : null;
      const newSpotPrc = row.spot_prc_s !== null && row.spot_prc_s !== undefined
        ? parseFloat(String(row.spot_prc_s)) : null;

      const prev = posMasterPrevPricesRef.current.get(ticker);

      if (prev) {
        if (newLastPrcT !== null && prev.lastPrcT !== null && newLastPrcT !== prev.lastPrcT) {
          changes.set(`${ticker}:last_prc_t`, newLastPrcT > prev.lastPrcT ? "up" : "down");
        }
        if (newSpotPrc !== null && prev.spotPrc !== null && newSpotPrc !== prev.spotPrc) {
          changes.set(`${ticker}:spot_prc_s`, newSpotPrc > prev.spotPrc ? "up" : "down");
        }
      }
    }
    return changes;
  }, [livePosRows]);

  // Safely update the ref only during the commit phase (useEffect) to prevent React double-render/Strict-mode race conditions from wiping out detected price changes.
  useEffect(() => {
    for (const row of livePosRows) {
      const ticker: string = row.ticker;
      const newLastPrcT = row.last_prc_t !== null && row.last_prc_t !== undefined
        ? parseFloat(String(row.last_prc_t)) : null;
      const newSpotPrc = row.spot_prc_s !== null && row.spot_prc_s !== undefined
        ? parseFloat(String(row.spot_prc_s)) : null;

      posMasterPrevPricesRef.current.set(ticker, { lastPrcT: newLastPrcT, spotPrc: newSpotPrc });
    }
  }, [livePosRows]);

  // ── Unique Options for Position Master Filters ──
  const posUnderlyings = useMemo(() => {
    const set = new Set<string>();
    livePosRows.forEach((row) => {
      if (row.und_ticker) set.add(row.und_ticker.toUpperCase());
    });
    return Array.from(set).sort();
  }, [livePosRows]);

  // ── Unique Options for Realtime Trades Filters ──
  const tradesUnderlyings = useMemo(() => {
    const set = new Set<string>();
    tradesRows.forEach((row) => {
      if (row.symbol) set.add(getUnderlying(row.symbol).toUpperCase());
    });
    return Array.from(set).sort();
  }, [tradesRows]);

  // ── Unique Options for Dividend Calendar Filters ──
  const dividendUnderlyings = useMemo(() => {
    const set = new Set<string>();
    dividendRows.forEach((row) => {
      if (row.symbol) set.add(row.symbol.toUpperCase());
    });
    return Array.from(set).sort();
  }, [dividendRows]);

  // ── Filtered Position Master Data ──
  const filteredPosRowsMM = useMemo(() => {
    return livePosRowsMM.filter((row) => {
      const matchUnd = posFilter.underlyings.includes("All") || (row.und_ticker && posFilter.underlyings.map(u => u.toUpperCase()).includes(row.und_ticker.toUpperCase()));
      const matchFrom = !posFilter.fromDate || (row.expiry && row.expiry >= posFilter.fromDate);
      const matchTo = !posFilter.toDate || (row.expiry && row.expiry <= posFilter.toDate);
      return matchUnd && matchFrom && matchTo;
    });
  }, [livePosRowsMM, posFilter]);

  const filteredPosRowsHedge = useMemo(() => {
    return livePosRowsHedge.filter((row) => {
      const matchUnd = posFilter.underlyings.includes("All") || (row.und_ticker && posFilter.underlyings.map(u => u.toUpperCase()).includes(row.und_ticker.toUpperCase()));
      const matchFrom = !posFilter.fromDate || (row.expiry && row.expiry >= posFilter.fromDate);
      const matchTo = !posFilter.toDate || (row.expiry && row.expiry <= posFilter.toDate);
      return matchUnd && matchFrom && matchTo;
    });
  }, [livePosRowsHedge, posFilter]);

  // ── Filtered Realtime Trades Data ──
  const filteredTradesRows = useMemo(() => {
    return tradesRows.filter((row) => {
      const rowUnd = getUnderlying(row.symbol);
      const matchUnd = tradesFilter.underlyings.includes("All") || (rowUnd && tradesFilter.underlyings.map(u => u.toUpperCase()).includes(rowUnd.toUpperCase()));

      const livePos = livePosRows.find((pos) => pos.ticker.toUpperCase() === row.symbol.toUpperCase());
      const rowExpiry = livePos ? livePos.expiry : null;

      const matchFrom = !tradesFilter.fromDate || (rowExpiry && rowExpiry >= tradesFilter.fromDate);
      const matchTo = !tradesFilter.toDate || (rowExpiry && rowExpiry <= tradesFilter.toDate);

      return matchUnd && matchFrom && matchTo;
    });
  }, [tradesRows, tradesFilter, livePosRows]);

  // ── Filtered Holiday Calendar Data ──
  const filteredHolidayRows = useMemo(() => {
    return holidayRows.filter((row) => {
      const matchFrom = !holidayFilter.fromDate || (row.date && row.date >= holidayFilter.fromDate);
      const matchTo = !holidayFilter.toDate || (row.date && row.date <= holidayFilter.toDate);
      return matchFrom && matchTo;
    });
  }, [holidayRows, holidayFilter]);

  // ── Filtered Dividend Calendar Data ──
  const filteredDividendRows = useMemo(() => {
    return dividendRows.filter((row) => {
      const matchUnd = dividendFilter.underlyings.includes("All") || (row.symbol && dividendFilter.underlyings.map(u => u.toUpperCase()).includes(row.symbol.toUpperCase()));
      const matchFrom = !dividendFilter.fromDate || (row.exDate && row.exDate >= dividendFilter.fromDate);
      const matchTo = !dividendFilter.toDate || (row.exDate && row.exDate <= dividendFilter.toDate);
      return matchUnd && matchFrom && matchTo;
    });
  }, [dividendRows, dividendFilter]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        backgroundColor: colors.background,
      }}
    >
      <Topbar currentView={viewMode} onViewChange={setViewMode} serverTimeOffset={serverTimeOffset} />

      <div
        style={{
          flex: 1,
          display: "flex",
          padding: "6px 18px 6px 18px",
          overflow: "auto",
        }}
      >
        {/* VN30 Equity Table Tab */}
        <div
          style={{
            flex: 1,
            display: viewMode === "equity" ? "flex" : "none",
            flexDirection: "column",
            minWidth: 0
          }}
        >
          <PanelTitle
            title="Equity"
            displayOptionContent={
              <DisplayOptionContent
                columns={stockTable.getColumns().map((c) => ({ key: c.key, header: c.header }))}
                hiddenColumns={hiddenColumns}
                onToggleColumn={toggleColumn}
                onReset={resetColumns}
                onUnselectAll={unselectAllColumns}
              />
            }
          />
          <TableView
            table={stockTable}
            data={filteredTableData}
            hiddenColumns={hiddenColumns}
            lastChanges={lastChanges}
          />
        </div>

        {/* Info Tab */}
        <div
          style={{
            flex: 1,
            display: viewMode === "info" ? "flex" : "none",
            flexDirection: "column",
            minWidth: 0,
            gap: "16px",
          }}
        >
          {/* Section 1: Position Master */}
          <div style={{ flex: 1.2, display: "flex", flexDirection: "column", minHeight: 0 }}>
            <PanelTitle
              title="Position Master"
              filterContent={
                <TableFilterContent
                  underlyings={posUnderlyings}
                  selectedUnderlyings={posFilter.underlyings}
                  onSelectUnderlyings={(vals) => setPosFilter(prev => ({ ...prev, underlyings: vals }))}
                  fromDate={posFilter.fromDate}
                  toDate={posFilter.toDate}
                  onChangeFromDate={(val) => setPosFilter(prev => ({ ...prev, fromDate: val }))}
                  onChangeToDate={(val) => setPosFilter(prev => ({ ...prev, toDate: val }))}
                  onReset={() => setPosFilter({ underlyings: ["All"], fromDate: "", toDate: "" })}
                />
              }
              displayOptionContent={
                <DisplayOptionContent
                  columns={posMasterTable.getColumns().map((c) => ({ key: c.key, header: c.header }))}
                  hiddenColumns={infoHiddenColumns}
                  onToggleColumn={toggleInfoColumn}
                  onReset={resetInfoColumns}
                  onUnselectAll={unselectAllInfoColumns}
                />
              }
            />

            {/* ── Column-group tab bar ─────────────────────────────────────── */}
            <div
              style={{
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
                paddingBottom: 10,
                marginBottom: 4,
                flexShrink: 0,
              }}
            >
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
                {(Object.entries(POS_GROUP_META) as [Exclude<PosColumnGroup, "all">, { label: string; color: string; count: number }][]).map(
                  ([group, meta]) => {
                    const isActive = posColumnGroup === group;
                    return (
                      <button
                        key={group}
                        onClick={() => setPosColumnGroup(group)}
                        style={{
                          padding: "5px 14px",
                          borderRadius: "6px",
                          border: `1px solid ${isActive ? meta.color : "rgba(255,255,255,0.10)"
                            }`,
                          background: isActive ? `${meta.color}40` : "transparent",
                          boxShadow: isActive
                            ? `0 0 0 1px ${meta.color}55, 0 2px 8px ${meta.color}22`
                            : "none",
                          color: isActive ? meta.color : "rgba(255,255,255,0.40)",
                          fontSize: 12,
                          fontWeight: isActive ? 700 : 400,
                          cursor: "pointer",
                          transition: "all 0.18s ease",
                          letterSpacing: "0.03em",
                          lineHeight: "1.6",
                          whiteSpace: "nowrap",
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          userSelect: "none",
                        }}
                      >
                        {meta.label}
                        <span
                          style={{
                            fontSize: 10,
                            fontWeight: 400,
                            opacity: isActive ? 0.75 : 0.40,
                            background: isActive ? `${meta.color}30` : "rgba(255,255,255,0.06)",
                            color: isActive ? meta.color : "rgba(255,255,255,0.45)",
                            borderRadius: 10,
                            padding: "0px 6px",
                            lineHeight: "1.8",
                          }}
                        >
                          {posMasterTable.getColumnsByGroup(group).length}
                        </span>
                      </button>
                    );
                  }
                )}
              </div>
            </div>
            {/* ─────────────────────────────────────────────────────────────── */}
            {loadingPos ? (
              <div
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  border: `1px solid ${colors.border}`,
                  backgroundColor: colors.panelBg,
                  borderRadius: "8px",
                  marginTop: "8px",
                  padding: "24px",
                  color: colors.textSecondary,
                  fontSize: "14px",
                }}
              >
                Loading position data from database...
              </div>
            ) : posError ? (
              <div
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  border: `1px solid ${colors.border}`,
                  backgroundColor: colors.panelBg,
                  borderRadius: "8px",
                  marginTop: "8px",
                  padding: "24px",
                  color: colors.decrease,
                  fontSize: "14px",
                }}
              >
                {posError}
              </div>
            ) : (
              (() => {
                posMasterTable.activeGroup = posColumnGroup;
                const hiddenColsList = [
                  // hide every column NOT in the active group (computed from group keys),
                  // PLUS any manually hidden columns from the DisplayOption panel
                  ...posMasterTable
                    .getColumns()
                    .filter(
                      (c) =>
                        !posMasterTable
                          .getColumnsByGroup(posColumnGroup)
                          .some((gc) => gc.key === c.key)
                    )
                    .map((c) => c.key),
                  ...infoHiddenColumns,
                ];
                return (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px", flex: 1, minHeight: 0 }}>
                    {/* MM Account Table */}
                    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                      <div style={{ fontSize: "12px", fontWeight: 700, color: colors.textSecondary, marginBottom: "6px", paddingLeft: "4px" }}>
                        Account: 0001922095
                      </div>
                      <TableView
                        scrollContainerRef={mmContainerRef}
                        hideHorizontalScrollbar={true}
                        table={posMasterTable}
                        data={filteredPosRowsMM}
                        hiddenColumns={hiddenColsList}
                        lastChanges={posMasterChanges}
                      />
                    </div>

                    {/* Hedging Account Table */}
                    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                      <div style={{ fontSize: "12px", fontWeight: 700, color: colors.textSecondary, marginBottom: "6px", paddingLeft: "4px" }}>
                        Account: 0001115688
                      </div>
                      <TableView
                        scrollContainerRef={hedgeContainerRef}
                        hideHorizontalScrollbar={false}
                        table={posMasterTable}
                        data={filteredPosRowsHedge}
                        hiddenColumns={hiddenColsList}
                        lastChanges={posMasterChanges}
                      />
                    </div>
                  </div>
                );
              })()
            )}
          </div>

          {/* Section 2: Bottom row — Realtime Trades | Holiday Calendar | Dividend Calendar */}
          <div style={{ flex: 0.8, display: "flex", flexDirection: "row", minHeight: 0, gap: "16px", paddingBottom: "24px" }}>

            {/* 2a. Realtime Trades */}
            <div style={{ flex: 7, display: "flex", flexDirection: "column", minWidth: 0 }}>
              <PanelTitle
                title="Realtime Trades"
                filterContent={
                  <TableFilterContent
                    underlyings={tradesUnderlyings}
                    selectedUnderlyings={tradesFilter.underlyings}
                    onSelectUnderlyings={(vals) => setTradesFilter(prev => ({ ...prev, underlyings: vals }))}
                    fromDate={tradesFilter.fromDate}
                    toDate={tradesFilter.toDate}
                    onChangeFromDate={(val) => setTradesFilter(prev => ({ ...prev, fromDate: val }))}
                    onChangeToDate={(val) => setTradesFilter(prev => ({ ...prev, toDate: val }))}
                    onReset={() => setTradesFilter({ underlyings: ["All"], fromDate: "", toDate: "" })}
                  />
                }
                displayOptionContent={
                  <DisplayOptionContent
                    columns={rtTradesTable.getColumns().map((c) => ({ key: c.key, header: c.header }))}
                    hiddenColumns={tradesHiddenColumns}
                    onToggleColumn={toggleTradesColumn}
                    onReset={resetTradesColumns}
                    onUnselectAll={unselectAllTradesColumns}
                  />
                }
              />
              {loadingTrades ? (
                <div
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    border: `1px solid ${colors.border}`,
                    backgroundColor: colors.panelBg,
                    borderRadius: "8px",
                    marginTop: "8px",
                    padding: "24px",
                    color: colors.textSecondary,
                    fontSize: "14px",
                  }}
                >
                  Loading trades from database...
                </div>
              ) : tradesError ? (
                <div
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    border: `1px solid ${colors.border}`,
                    backgroundColor: colors.panelBg,
                    borderRadius: "8px",
                    marginTop: "8px",
                    padding: "24px",
                    color: colors.decrease,
                    fontSize: "14px",
                  }}
                >
                  {tradesError}
                </div>
              ) : (
                <TableView
                  table={rtTradesTable}
                  data={filteredTradesRows}
                  hiddenColumns={tradesHiddenColumns}
                />
              )}
            </div>

            {/* Calendars Stack Container */}
            <div style={{ flex: 3.5, display: "flex", flexDirection: "column", gap: "16px", minWidth: 0 }}>
              {/* 2b. Holiday Calendar */}
              <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                <PanelTitle
                  title="Holiday Calendar"
                  filterContent={
                    <TableFilterContent
                      isDateOnly={true}
                      underlyings={[]}
                      selectedUnderlyings={holidayFilter.underlyings}
                      onSelectUnderlyings={(vals) => setHolidayFilter(prev => ({ ...prev, underlyings: vals }))}
                      fromDate={holidayFilter.fromDate}
                      toDate={holidayFilter.toDate}
                      onChangeFromDate={(val) => setHolidayFilter(prev => ({ ...prev, fromDate: val }))}
                      onChangeToDate={(val) => setHolidayFilter(prev => ({ ...prev, toDate: val }))}
                      onReset={() => setHolidayFilter({ underlyings: ["All"], fromDate: "", toDate: "" })}
                    />
                  }
                />
                {loadingHolidays ? (
                  <div
                    style={{
                      flex: 1,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      border: `1px solid ${colors.border}`,
                      backgroundColor: colors.panelBg,
                      borderRadius: "8px",
                      marginTop: "8px",
                      padding: "24px",
                      color: colors.textSecondary,
                      fontSize: "14px",
                    }}
                  >
                    Loading holidays...
                  </div>
                ) : holidaysError ? (
                  <div
                    style={{
                      flex: 1,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      border: `1px solid ${colors.border}`,
                      backgroundColor: colors.panelBg,
                      borderRadius: "8px",
                      marginTop: "8px",
                      padding: "24px",
                      color: colors.decrease,
                      fontSize: "14px",
                    }}
                  >
                    {holidaysError}
                  </div>
                ) : (
                  <TableView
                    table={holidayTable}
                    data={filteredHolidayRows}
                    emptyStateMessage="No holiday data available"
                  />
                )}
              </div>

              {/* 2c. Dividend Calendar */}
              <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                <PanelTitle
                  title="Dividend Calendar"
                  filterContent={
                    <TableFilterContent
                      isDateOnly={true}
                      underlyings={dividendUnderlyings}
                      selectedUnderlyings={dividendFilter.underlyings}
                      onSelectUnderlyings={(vals) => setDividendFilter(prev => ({ ...prev, underlyings: vals }))}
                      fromDate={dividendFilter.fromDate}
                      toDate={dividendFilter.toDate}
                      onChangeFromDate={(val) => setDividendFilter(prev => ({ ...prev, fromDate: val }))}
                      onChangeToDate={(val) => setDividendFilter(prev => ({ ...prev, toDate: val }))}
                      onReset={() => setDividendFilter({ underlyings: ["All"], fromDate: "", toDate: "" })}
                    />
                  }
                />
                {loadingDividends ? (
                  <div
                    style={{
                      flex: 1,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      border: `1px solid ${colors.border}`,
                      backgroundColor: colors.panelBg,
                      borderRadius: "8px",
                      marginTop: "8px",
                      padding: "24px",
                      color: colors.textSecondary,
                      fontSize: "14px",
                    }}
                  >
                    Loading dividends (T−400 → T+400, showing GDKHQDate today→+7)...
                  </div>
                ) : dividendsError ? (
                  <div
                    style={{
                      flex: 1,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      border: `1px solid ${colors.border}`,
                      backgroundColor: colors.panelBg,
                      borderRadius: "8px",
                      marginTop: "8px",
                      padding: "24px",
                      color: colors.decrease,
                      fontSize: "14px",
                    }}
                  >
                    {dividendsError}
                  </div>
                ) : (
                  <TableView
                    table={dividendTable}
                    data={filteredDividendRows}
                    emptyStateMessage="No new dividend events"
                  />
                )}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}
