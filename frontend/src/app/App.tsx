import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { Topbar } from "./Topbar";
import { Login } from "../components/Login";
import { PanelTitle } from "./PanelTitle";
import { TableView } from "@/tables/core/TableView";
import { stockTable } from "@/tables/stock/StockTable";
import { posMasterTable } from "@/tables/info/PosMasterTable";
import { type PosColumnGroup, POS_GROUP_META, DEFAULT_HIDDEN_POS_COLUMNS } from "@/tables/info/PosMasterTable";
import { rtTradesTable } from "@/tables/info/RtTradesTable";
import { PosMasterTreeView } from "@/tables/info/PosMasterTreeView";
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
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    if (typeof window !== "undefined") {
      const lastUser = localStorage.getItem("lastActiveUser");
      const key = lastUser ? `${lastUser}:viewMode` : "viewMode";
      const saved = localStorage.getItem(key);
      if (saved === "equity" || saved === "info") {
        return saved as ViewMode;
      }
    }
    return "equity";
  });
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loggedOut, setLoggedOut] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);

  const [hiddenColumns, setHiddenColumns] = useState<string[]>(() => {
    if (typeof window !== "undefined") {
      const lastUser = localStorage.getItem("lastActiveUser");
      const key = lastUser ? `${lastUser}:hiddenColumns` : "hiddenColumns";
      const saved = localStorage.getItem(key);
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          return Array.from(new Set([...parsed, ...DEFAULT_HIDDEN_POS_COLUMNS]));
        } catch (e) { }
      }
    }
    return DEFAULT_HIDDEN_POS_COLUMNS;
  });
  const [infoHiddenColumns, setInfoHiddenColumns] = useState<string[]>(() => {
    if (typeof window !== "undefined") {
      const lastUser = localStorage.getItem("lastActiveUser");
      const key = lastUser ? `${lastUser}:infoHiddenColumns` : "infoHiddenColumns";
      const saved = localStorage.getItem(key);
      if (saved) {
        try {
          return JSON.parse(saved);
        } catch (e) { }
      }
    }
    return [];
  });
  const [tradesHiddenColumns, setTradesHiddenColumns] = useState<string[]>(() => {
    if (typeof window !== "undefined") {
      const lastUser = localStorage.getItem("lastActiveUser");
      const key = lastUser ? `${lastUser}:tradesHiddenColumns` : "tradesHiddenColumns";
      const saved = localStorage.getItem(key);
      if (saved) {
        try {
          return JSON.parse(saved);
        } catch (e) { }
      }
    }
    return [];
  });
  const [posColumnGroup, setPosColumnGroup] = useState<PosColumnGroup>(() => {
    if (typeof window !== "undefined") {
      const lastUser = localStorage.getItem("lastActiveUser");
      const key = lastUser ? `${lastUser}:posColumnGroup` : "posColumnGroup";
      const saved = localStorage.getItem(key);
      if (saved) {
        return saved as PosColumnGroup;
      }
    }
    return "overview";
  });

  // Decode user email from Access Token
  const userEmail = useMemo(() => {
    if (!accessToken) return "";
    try {
      const payload = accessToken.split(".")[1];
      const decoded = JSON.parse(atob(payload));
      return decoded.email || "";
    } catch (e) {
      return "";
    }
  }, [accessToken]);

  // Keep track of the last active user
  useEffect(() => {
    if (userEmail) {
      localStorage.setItem("lastActiveUser", userEmail);
    }
  }, [userEmail]);

  // Load user settings when userEmail resolves
  useEffect(() => {
    if (userEmail) {
      const savedViewMode = localStorage.getItem(`${userEmail}:viewMode`);
      if (savedViewMode === "equity" || savedViewMode === "info") {
        setViewMode(savedViewMode as ViewMode);
      }

      const savedHidden = localStorage.getItem(`${userEmail}:hiddenColumns`);
      if (savedHidden) {
        try { setHiddenColumns(JSON.parse(savedHidden)); } catch (e) { }
      } else {
        setHiddenColumns([]);
      }

      const savedInfoHidden = localStorage.getItem(`${userEmail}:infoHiddenColumns`);
      if (savedInfoHidden) {
        try { setInfoHiddenColumns(JSON.parse(savedInfoHidden)); } catch (e) { }
      } else {
        setInfoHiddenColumns([]);
      }

      const savedTradesHidden = localStorage.getItem(`${userEmail}:tradesHiddenColumns`);
      if (savedTradesHidden) {
        try { setTradesHiddenColumns(JSON.parse(savedTradesHidden)); } catch (e) { }
      } else {
        setTradesHiddenColumns([]);
      }

      const savedGroup = localStorage.getItem(`${userEmail}:posColumnGroup`);
      if (savedGroup) {
        setPosColumnGroup(savedGroup as PosColumnGroup);
      } else {
        setPosColumnGroup("overview");
      }
    }
  }, [userEmail]);

  // Persist user settings when they change
  useEffect(() => {
    if (userEmail) {
      localStorage.setItem(`${userEmail}:viewMode`, viewMode);
    }
  }, [viewMode, userEmail]);

  useEffect(() => {
    if (userEmail) {
      localStorage.setItem(`${userEmail}:hiddenColumns`, JSON.stringify(hiddenColumns));
    }
  }, [hiddenColumns, userEmail]);

  useEffect(() => {
    if (userEmail) {
      localStorage.setItem(`${userEmail}:infoHiddenColumns`, JSON.stringify(infoHiddenColumns));
    }
  }, [infoHiddenColumns, userEmail]);

  useEffect(() => {
    if (userEmail) {
      localStorage.setItem(`${userEmail}:tradesHiddenColumns`, JSON.stringify(tradesHiddenColumns));
    }
  }, [tradesHiddenColumns, userEmail]);

  useEffect(() => {
    if (userEmail) {
      localStorage.setItem(`${userEmail}:posColumnGroup`, posColumnGroup);
    }
  }, [posColumnGroup, userEmail]);

  // Silent refresh on startup
  useEffect(() => {
    fetch("/api/auth/refresh", { method: "POST" })
      .then((res) => {
        if (res.ok) return res.json();
        throw new Error("No session");
      })
      .then((data) => {
        if (data.success && data.accessToken) {
          setAccessToken(data.accessToken);
        }
      })
      .catch(() => { })
      .finally(() => {
        setIsInitialized(true);
      });
  }, []);

  // Background token refresh loop
  useEffect(() => {
    if (!accessToken) return;

    const interval = setInterval(() => {
      fetch("/api/auth/refresh", { method: "POST" })
        .then((res) => {
          if (res.ok) return res.json();
          throw new Error("Session expired");
        })
        .then((data) => {
          if (data.success && data.accessToken) {
            setAccessToken(data.accessToken);
          }
        })
        .catch((err) => {
          console.error("Token refresh failed:", err);
          setAccessToken(null);
        });
    }, 14 * 60 * 1000); // 14 minutes (token expires in 15m)

    return () => clearInterval(interval);
  }, [accessToken]);

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch (err) {
      console.error("Failed to call logout API:", err);
    } finally {
      setAccessToken(null);
      setLoggedOut(true);
    }
  };
  // Hidden columns and column groups are declared at the top of the component

  const [posRowsMM, setPosRowsMM] = useState<any[]>([]);
  const [posRowsHedge, setPosRowsHedge] = useState<any[]>([]);
  const [loadingPos, setLoadingPos] = useState(false);
  const [posError, setPosError] = useState<string | null>(null);
  // posColumnGroup is declared at the top of the component

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
  const [posFilter, setPosFilter] = useState<{ underlyings: string[] }>({ underlyings: ["All"] });
  const [tradesFilter, setTradesFilter] = useState<{ underlyings: string[]; statuses: string[] }>({ underlyings: ["All"], statuses: ["All"] });
  const [dividendFilter, setDividendFilter] = useState<{ underlyings: string[] }>({ underlyings: ["All"] });

  // Keep refs of states so the background polling effect doesn't capture stale closures
  const posRowsMMRef = useRef<any[]>([]);
  const posRowsHedgeRef = useRef<any[]>([]);
  const tradesRowsRef = useRef<any[]>([]);
  const holidayRowsRef = useRef<any[]>([]);
  const dividendRowsRef = useRef<any[]>([]);
  const viewModeRef = useRef<ViewMode>(viewMode);
  const initialPosFetchedRef = useRef(false);
  const initialTradesFetchedRef = useRef(false);

  useEffect(() => {
    posRowsMMRef.current = posRowsMM;
  }, [posRowsMM]);

  useEffect(() => {
    posRowsHedgeRef.current = posRowsHedge;
  }, [posRowsHedge]);

  useEffect(() => {
    tradesRowsRef.current = tradesRows;
  }, [tradesRows]);

  useEffect(() => {
    holidayRowsRef.current = holidayRows;
  }, [holidayRows]);

  useEffect(() => {
    dividendRowsRef.current = dividendRows;
  }, [dividendRows]);

  useEffect(() => {
    viewModeRef.current = viewMode;
  }, [viewMode]);

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
    if (!accessToken) {
      initialPosFetchedRef.current = false;
      initialTradesFetchedRef.current = false;
      return;
    }

    let isMounted = true;

    const fetchPosMaster = () => {
      // Only set loading state if we haven't successfully fetched it yet
      if (!initialPosFetchedRef.current) {
        setLoadingPos(true);
        setPosError(null);
      }
      Promise.all([
        fetch('/api/pos-master?type=MM', {
          headers: { 'Authorization': `Bearer ${accessToken}` }
        }).then((res) => {
          if (res.status === 401) {
            setAccessToken(null);
            throw new Error("Unauthorized");
          }
          if (!res.ok) throw new Error("Failed to fetch MM position master data.");
          return res.json();
        }),
        fetch('/api/pos-master?type=HEDGING', {
          headers: { 'Authorization': `Bearer ${accessToken}` }
        }).then((res) => {
          if (res.status === 401) {
            setAccessToken(null);
            throw new Error("Unauthorized");
          }
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
          setLoadingPos(false);
          initialPosFetchedRef.current = true;
        })
        .catch((err) => {
          if (!isMounted) return;
          console.error("Error fetching pos_master:", err);
          if (!err.message.includes("Unauthorized")) {
            setPosError(err.message || "Could not load positions from database.");
          }
          setLoadingPos(false);
        });
    };

    const fetchRtTrades = () => {
      // Only set loading state if we haven't successfully fetched it yet
      if (!initialTradesFetchedRef.current) {
        setLoadingTrades(true);
        setTradesError(null);
      }
      fetch("/api/rt-trades", {
        headers: { 'Authorization': `Bearer ${accessToken}` }
      })
        .then((res) => {
          if (res.status === 401) {
            setAccessToken(null);
            throw new Error("Unauthorized");
          }
          if (!res.ok) throw new Error("Failed to fetch realtime trades.");
          return res.json();
        })
        .then((data) => {
          if (!isMounted) return;
          const mappedData = data.map((r: any) => ({ ...r, Symbol: r.symbol }));
          setTradesRows(mappedData);
          setLoadingTrades(false);
          initialTradesFetchedRef.current = true;
        })
        .catch((err) => {
          if (!isMounted) return;
          console.error("Error fetching rt_trades:", err);
          if (!err.message.includes("Unauthorized")) {
            setTradesError(err.message || "Could not load trades from database.");
          }
          setLoadingTrades(false);
        });
    };

    // Initial fetches
    fetchPosMaster();
    fetchRtTrades();

    if (holidayRowsRef.current.length === 0) {
      setLoadingHolidays(true);
      setHolidaysError(null);
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
    }

    if (dividendRowsRef.current.length === 0) {
      setLoadingDividends(true);
      setDividendsError(null);
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
    }

    // Dynamic background polling based on tab activity (2s active vs 10s background)
    let tickCount = 0;
    const pollInterval = setInterval(() => {
      if (document.hidden) return;

      const isInfoActive = viewModeRef.current === "info";
      tickCount++;
      if (isInfoActive || tickCount >= 5) {
        tickCount = 0;
        fetchPosMaster();
        fetchRtTrades();
      }
    }, 2000);

    return () => {
      isMounted = false;
      clearInterval(pollInterval);
    };
  }, [accessToken]);

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



  // Black-Scholes Call Option Price
  function bsCallPrice(
    S: number,
    K: number,
    t: number,
    r: number,
    sigma: number,
    cr: number
  ): number {
    if (t <= 0) {
      return Math.max(0, S - K) / cr;
    }

    const sqrtT = Math.sqrt(t);

    const d1 =
      (Math.log(S / K) +
        (r + (sigma * sigma) / 2) * t) /
      (sigma * sqrtT);

    const d2 = d1 - sigma * sqrtT;

    const optionPrice =
      S * cnd(d1) -
      K * Math.exp(-r * t) * cnd(d2);

    return optionPrice / cr;
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
        if (liveWarrant.ChangePercent !== null && liveWarrant.ChangePercent !== undefined) {
          netChgPct = liveWarrant.ChangePercent / 100;
        } else if (lastPrcT1 > 0) {
          netChgPct = (lastPrcT / lastPrcT1) - 1;
        }
      }

      // ── Spot_Prc(S) — per-account logic ───────────────────────────────────
      // MM account (isHedging=false): CW-focused. Spot_Prc(S) = underlying stock's live price.
      // Hedging account (isHedging=true): Stock-focused. Spot_Prc(S) = the stock
      //   ticker's own live price (via getRow(ticker)), not the underlying of a CW.
      let spotPrcS = row.spot_prc_s !== null ? parseFloat(row.spot_prc_s) : null;
      const dteVal = row.dte !== null && row.dte !== undefined ? parseFloat(String(row.dte)) : null;

      if (!isHedging) {
        // MM: Spot_Prc(S) should be the underlying stock's live price from WebSocket
        const liveUnderlying = row.und_ticker ? getRow(row.und_ticker.toUpperCase()) : null;
        if (liveUnderlying && liveUnderlying.Ref && liveUnderlying.Ref > 0) {
          const tradedPrc = liveUnderlying.Traded && liveUnderlying.Traded > 0
            ? liveUnderlying.Traded
            : liveUnderlying.Ref;
          const bid1 = liveUnderlying.Bid1_Prc;
          const ask1 = liveUnderlying.Ask1_Prc;

          if (dteVal !== null && dteVal < 1 && tradedPrc !== null && bid1 !== null && bid1 !== undefined && ask1 !== null && ask1 !== undefined) {
            if (tradedPrc >= bid1 && tradedPrc <= ask1) {
              spotPrcS = tradedPrc;
            } else {
              spotPrcS = (bid1 + ask1) / 2;
            }
          } else {
            spotPrcS = tradedPrc;
          }
        }
      } else {
        // Hedging: Spot_Prc(S) = direct stock live price from WebSocket
        const liveStock = getRow(row.ticker.toUpperCase());
        if (liveStock && liveStock.Ref && liveStock.Ref > 0) {
          const tradedPrc = liveStock.Traded && liveStock.Traded > 0
            ? liveStock.Traded
            : liveStock.Ref;
          const bid1 = liveStock.Bid1_Prc;
          const ask1 = liveStock.Ask1_Prc;

          if (dteVal !== null && dteVal < 1 && tradedPrc !== null && bid1 !== null && bid1 !== undefined && ask1 !== null && ask1 !== undefined) {
            if (tradedPrc >= bid1 && tradedPrc <= ask1) {
              spotPrcS = tradedPrc;
            } else {
              spotPrcS = (bid1 + ask1) / 2;
            }
          } else {
            spotPrcS = tradedPrc;
          }
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
      const sigmaT1 = row.hedge_v_t_1 !== null ? parseFloat(row.hedge_v_t_1) : 0.3250;

      // Conversion Ratio (CVR) parsing
      let ratioNum = 1;
      let cvrVal = row.cvr;
      if (liveWarrant && liveWarrant.Exercise_Ratio !== null && liveWarrant.Exercise_Ratio !== undefined) {
        cvrVal = `${liveWarrant.Exercise_Ratio}:1`;
      }
      if (cvrVal) {
        const parts = cvrVal.split(":");
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
      let deltaT = 1.0; // Default delta = 1 for stocks/indexes
      let deltaT1 = 1.0; // Default delta = 1 for stocks/indexes

      if (strikeK && tteT !== null && tteT1 !== null) {
        if (lastPrcT && lastPrcT > 0) {
          theoPrcT = bsCallPrice(spotS_t, strikeK, tteT, rate, sigma, ratioNum);
          theoPrcT1 = bsCallPrice(spotS_t_1, strikeK, tteT1, rate, sigma, ratioNum);
          const priceVolUp = bsCallPrice(spotS_t, strikeK, tteT, rate, sigma + 0.0001, ratioNum);
          const priceVolDown = bsCallPrice(spotS_t, strikeK, tteT, rate, sigma - 0.0001, ratioNum);
          vegaPctT = (priceVolUp - priceVolDown) / 0.02;
          const newT = Math.max(tteT - 1 / 365, 0.0001);
          const priceNewT = bsCallPrice(spotS_t, strikeK, newT, rate, sigma, ratioNum);
          thetaT = priceNewT - theoPrcT;

          // Calculate Delta using analytical formula:
          deltaT = bsCallDelta(spotS_t, strikeK, tteT, rate, sigma) / ratioNum;

          // Calculate Yesterday's Delta using analytical formula:
          deltaT1 = bsCallDelta(spotS_t_1, strikeK, tteT1, rate, sigmaT1) / ratioNum;
        } else {
          theoPrcT = 0;
          theoPrcT1 = 0;
          vegaPctT = 0;
          thetaT = 0;
          deltaT = 0;
          deltaT1 = 0;
        }
      }
      const deltaLotsT = deltaT * balance;
      const deltaCashT = spotS_t * deltaLotsT;
      const deltaCashT1 = deltaT1 * balanceT1 * spotS_t_1;

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

      if (strikeK && tteT1 !== null) {
        // Gamma yesterday
        const delta_up_1 = bsCallDelta(spotS_t_1 * 1.0001, strikeK, tteT1, rate, sigmaT1);
        const delta_down_1 = bsCallDelta(spotS_t_1 * 0.9999, strikeK, tteT1, rate, sigmaT1);
        const gammaOption_1 = (delta_up_1 - delta_down_1) / (spotS_t_1 * 0.0002);
        gammaAmtPctT1 = gammaOption_1 / ratioNum;

        // Theta yesterday
        const newT1 = Math.max(tteT1 - 1 / 365, 0.0001);
        const priceNewT1 = bsCallPrice(spotS_t_1, strikeK, newT1, rate, sigmaT1, ratioNum);
        thetaT1 = priceNewT1 - theoPrcT1;
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
      const gammaPnl = 0.5 * Math.pow(stockReturn, 2) * Math.pow(spotS_t_1, 2) * gammaAmtPctT1 * balanceT1;

      // Gamma(T) = (Delta(S * 1.0001) - Delta(S * 0.9999)) / (S * 0.0002)
      // %GammaAmt(T) = Gamma(T) * 0.01 * S^2 * Balance
      let gammaT: number | null = null;
      let gammaAmtPctT = 0;
      if (strikeK && tteT !== null && spotS_t > 0) {
        const delta_up = bsCallDelta(spotS_t * 1.0001, strikeK, tteT, rate, sigma) / ratioNum;
        const delta_down = bsCallDelta(spotS_t * 0.9999, strikeK, tteT, rate, sigma) / ratioNum;
        gammaT = (delta_up - delta_down) / (spotS_t * 0.0002);
        gammaAmtPctT = gammaT * 0.01 * Math.pow(spotS_t, 2) * balance;
      }

      // thetapnl = 0.5 * (Theta(T-1) + Theta(T)) * DailyDecay(X)
      const thetaPnl = 0.5 * (thetaT1 + thetaT) * m;

      // vegapnl is pre-calculated using dynamic vol traded and saved in the database
      const vegaPnl = row.vega_pnl !== null ? parseFloat(row.vega_pnl) : 0;

      const unexplainedPnl = 0.00;

      // Cumulative session PnLs
      const totalPnlTheoCum = totalPnlTheo;
      const totalPnlMtmCum = totalPnlMtm;

      return {
        ...row,
        cvr: cvrVal,
        last_prc_t: lastPrcT !== null ? String(lastPrcT) : null,
        last_prc_t_1: lastPrcT1 !== null ? String(lastPrcT1) : null,
        net_chg_pct: netChgPct !== null ? String(netChgPct) : null,
        spot_prc_s: spotPrcS !== null ? String(spotPrcS) : null,
        delta_t: deltaT !== null ? String(deltaT) : null,
        gamma_t: gammaT,

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
        gamma_amt_pct_t: gammaAmtPctT,
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
  // Track value changes for all formula-applied & API-driven columns.
  // Static / mocked columns (rate, multiplier_m, div_d, fund, vega_pnl, unexplained_pnl, capital_cost, ticker, expiry, strike_k, cvr) are excluded.
  const FLASHING_POS_KEYS = useMemo(() => new Set([
    "last_prc_t",
    "net_chg_pct",
    "spot_prc_s",
    "theo_prc_t",
    "theo_prc_t_1",
    "delta_t",
    "gamma_t",
    "delta_lots_t",
    "delta_cash_t",
    "delta_cash_t_1",
    "trd_delta_lots_t",
    "trd_delta_cash_t",
    "gamma_amt_pct_t",
    "vega_pct_t",
    "cash_vega_t",
    "theta_t",
    "cash_theta_t",
    "balance",
    "bought_qty",
    "bought_amt",
    "bought_avg",
    "sold_qty",
    "sold_amt",
    "sold_avg",
    "position_pnl_mtm",
    "trading_pnl_mtm",
    "total_pnl_mtm",
    "position_pnl_theo",
    "trading_pnl_theo",
    "total_pnl_theo",
    "delta_pnl",
    "gamma_pnl",
    "theta_pnl",
    "total_pnl_theo_cum",
    "total_pnl_mtm_cum",
    "dte",
    "tte_t",
    "tte_t_1",
  ]), []);

  const posMasterPrevValuesRef = useRef<Map<string, Record<string, number | null>>>(new Map());

  const posMasterChanges = useMemo(() => {
    const changes = new Map<string, "up" | "down">();
    for (const row of livePosRows) {
      const ticker: string = row.ticker;
      const isCW = Boolean(row.und_ticker && row.ticker.toUpperCase() !== row.und_ticker.toUpperCase());
      const prevRecord = posMasterPrevValuesRef.current.get(ticker);

      if (prevRecord) {
        FLASHING_POS_KEYS.forEach((colKey) => {
          // Rule: spot_prc_s only flashes for CW symbols (ticker !== und_ticker)
          if (colKey === "spot_prc_s" && !isCW) return;

          const rawVal = (row as Record<string, unknown>)[colKey];
          const newNum = rawVal !== null && rawVal !== undefined ? parseFloat(String(rawVal)) : null;
          const prevNum = prevRecord[colKey] !== undefined ? prevRecord[colKey] : null;

          if (newNum !== null && prevNum !== null && !isNaN(newNum) && !isNaN(prevNum) && Math.abs(newNum - prevNum) > 1e-9) {
            changes.set(`${ticker}:${colKey}`, newNum > prevNum ? "up" : "down");
          }
        });
      }
    }
    return changes;
  }, [livePosRows, FLASHING_POS_KEYS]);

  // Safely update the ref only during the commit phase (useEffect) to prevent React double-render/Strict-mode race conditions from wiping out detected price changes.
  useEffect(() => {
    for (const row of livePosRows) {
      const ticker: string = row.ticker;
      const currentRecord: Record<string, number | null> = {};
      FLASHING_POS_KEYS.forEach((colKey) => {
        const rawVal = (row as Record<string, unknown>)[colKey];
        currentRecord[colKey] = rawVal !== null && rawVal !== undefined ? parseFloat(String(rawVal)) : null;
      });
      posMasterPrevValuesRef.current.set(ticker, currentRecord);
    }
  }, [livePosRows, FLASHING_POS_KEYS]);

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

  const tradesStatuses = useMemo(() => {
    const set = new Set<string>();
    const statusCol = rtTradesTable.getColumns().find((c) => c.key === "status");
    for (const r of tradesRows) {
      const val = statusCol ? statusCol.format(r.orStatusValue, r) : (r.orStatusValue || "");
      if (val) set.add(String(val));
    }
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

  // ── Filtered Position Master Data (merged across both accounts) ──
  const filteredPosRows = useMemo(() => {
    return livePosRows.filter((row) => {
      // For CW rows, filter by und_ticker; for stock rows, filter by ticker itself
      const rowUnd = String(row.und_ticker ?? row.ticker ?? "").toUpperCase();
      const matchUnd =
        posFilter.underlyings.includes("All") ||
        posFilter.underlyings.map((u) => u.toUpperCase()).includes(rowUnd);
      return matchUnd;
    });
  }, [livePosRows, posFilter]);

  // ── Export Position Master → CSV (Overview tab: all 48 columns + Div(D)) ──
  const handleExportPosMasterCsv = useCallback(() => {
    // Overview columns: all columns minus default-hidden ones
    const overviewCols = posMasterTable.getColumnsByGroup("overview");
    // Build header row — include Div(D) as an extra column right after Ticker
    const extraDivHeader = "Div(D)";
    const tickerIdx = overviewCols.findIndex((c) => c.key === "ticker");
    const colsBefore = overviewCols.slice(0, tickerIdx + 1);
    const colsAfter = overviewCols.slice(tickerIdx + 1);

    const headers = [
      ...colsBefore.map((c) => c.header),
      extraDivHeader,
      ...colsAfter.map((c) => c.header),
    ];

    const escapeCell = (val: string): string => {
      if (val.includes(",") || val.includes('"') || val.includes("\n")) {
        return `"${val.replace(/"/g, '""')}"`;
      }
      return val;
    };

    const rows = filteredPosRows.map((row) => {
      const divVal = row.div_d !== null && row.div_d !== undefined ? String(row.div_d) : "";
      const cellsBefore = colsBefore.map((c) => escapeCell(c.getDisplayValue(row as any)));
      const cellsAfter = colsAfter.map((c) => escapeCell(c.getDisplayValue(row as any)));
      return [...cellsBefore, escapeCell(divVal), ...cellsAfter].join(",");
    });

    const csvContent = [headers.map(escapeCell).join(","), ...rows].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const now = new Date();
    const dateStamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
    const timeStamp = `${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}${String(now.getSeconds()).padStart(2, "0")}`;
    link.href = url;
    link.setAttribute("download", `pos_master_overview_${dateStamp}_${timeStamp}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [filteredPosRows]);

  // ── Filtered Realtime Trades Data ──
  const filteredTradesRows = useMemo(() => {
    const statusCol = rtTradesTable.getColumns().find((c) => c.key === "status");
    const filtered = tradesRows.filter((row) => {
      const rowUnd = getUnderlying(row.symbol);
      const matchUnd = tradesFilter.underlyings.includes("All") || (rowUnd && tradesFilter.underlyings.map(u => u.toUpperCase()).includes(rowUnd.toUpperCase()));

      const rowStatusText = statusCol ? statusCol.format(row.orStatusValue, row) : (row.orStatusValue || "");
      const matchStatus = tradesFilter.statuses.includes("All") || tradesFilter.statuses.includes(rowStatusText);

      return matchUnd && matchStatus;
    });

    const parseTimestamp = (str: string): number => {
      if (!str) return 0;
      try {
        const parts = str.trim().split(" ");
        if (parts.length === 2) {
          const [day, month, year] = parts[0].split("/").map(Number);
          const [h, m, s] = parts[1].split(":").map(Number);
          if (!isNaN(day) && !isNaN(month) && !isNaN(year) && !isNaN(h) && !isNaN(m) && !isNaN(s)) {
            return new Date(year, month - 1, day, h, m, s).getTime();
          }
        }
      } catch (e) { }
      const ts = Date.parse(str);
      return isNaN(ts) ? 0 : ts;
    };

    // Default sort from latest to oldest based on column Timestamp (lastChange)
    return filtered.sort((a, b) => {
      const timeA = parseTimestamp(a.lastChange);
      const timeB = parseTimestamp(b.lastChange);
      return timeB - timeA;
    });
  }, [tradesRows, tradesFilter, livePosRows]);

  // ── Active Holdings & Trades Symbols for Dividend Filtering ──
  const activeHoldingsAndTradesSymbols = useMemo(() => {
    const symbols = new Set<string>();

    // From Position Master
    posRowsMM.forEach((row) => {
      if (row.ticker) symbols.add(row.ticker.toUpperCase());
      if (row.und_ticker) symbols.add(row.und_ticker.toUpperCase());
    });
    posRowsHedge.forEach((row) => {
      if (row.ticker) symbols.add(row.ticker.toUpperCase());
      if (row.und_ticker) symbols.add(row.und_ticker.toUpperCase());
    });

    // From Realtime Trades
    tradesRows.forEach((row) => {
      if (row.symbol) {
        symbols.add(row.symbol.toUpperCase());
        symbols.add(getUnderlying(row.symbol).toUpperCase());
      }
    });

    return symbols;
  }, [posRowsMM, posRowsHedge, tradesRows]);

  // ── Filtered Holiday Calendar Data ──
  const filteredHolidayRows = useMemo(() => {
    const todayStr = new Date(Date.now() + 7 * 60 * 60 * 1000).toISOString().split("T")[0];
    return holidayRows.filter((row) => {
      if (row.date && row.date < todayStr) return false;
      return true;
    });
  }, [holidayRows]);

  // ── Filtered Dividend Calendar Data ──
  const filteredDividendRows = useMemo(() => {
    return dividendRows.filter((row) => {
      if (!row.symbol || !activeHoldingsAndTradesSymbols.has(row.symbol.toUpperCase())) {
        return false;
      }
      const matchUnd = dividendFilter.underlyings.includes("All") || (row.symbol && dividendFilter.underlyings.map(u => u.toUpperCase()).includes(row.symbol.toUpperCase()));
      return matchUnd;
    });
  }, [dividendRows, dividendFilter, activeHoldingsAndTradesSymbols]);

  if (!isInitialized) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          backgroundColor: colors.background,
          color: colors.textSecondary,
          fontSize: 16,
          fontWeight: 500,
          fontFamily: "Inter, sans-serif",
        }}
      >
        Initializing system...
      </div>
    );
  }

  if (!accessToken) {
    return (
      <Login
        onLoginSuccess={(token) => {
          setAccessToken(token);
          setLoggedOut(false);
        }}
        loggedOut={loggedOut}
        onClearLoggedOut={() => setLoggedOut(false)}
      />
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        backgroundColor: colors.background,
      }}
    >
      <Topbar
        currentView={viewMode}
        onViewChange={setViewMode}
        serverTimeOffset={serverTimeOffset}
        userEmail={userEmail}
        onLogout={handleLogout}
        accessToken={accessToken}
      />

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
            userEmail={userEmail}
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
                  onReset={() => setPosFilter({ underlyings: ["All"] })}
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
              onExportCsv={handleExportPosMasterCsv}
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
                  // Hide columns NOT in the active group, plus manually hidden ones and default hidden columns
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
                  ...DEFAULT_HIDDEN_POS_COLUMNS,
                ];
                return (
                  <PosMasterTreeView
                    data={filteredPosRows}
                    hiddenColumns={hiddenColsList}
                    lastChanges={posMasterChanges}
                    posColumnGroup={posColumnGroup}
                    userEmail={userEmail}
                  />
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
                    onReset={() => setTradesFilter({ underlyings: ["All"], statuses: ["All"] })}
                    statuses={tradesStatuses}
                    selectedStatuses={tradesFilter.statuses}
                    onSelectStatuses={(vals) => setTradesFilter(prev => ({ ...prev, statuses: vals }))}
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
                  userEmail={userEmail}
                  disablePinning={true}
                />
              )}
            </div>

            {/* Calendars Stack Container */}
            <div style={{ flex: 3.5, display: "flex", flexDirection: "column", gap: "16px", minWidth: 0 }}>
              {/* 2b. Holiday Calendar */}
              <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                <PanelTitle
                  title="Holiday Calendar"
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
                    userEmail={userEmail}
                  />
                )}
              </div>

              {/* 2c. Dividend Calendar */}
              <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                <PanelTitle
                  title="Dividend Calendar"
                  filterContent={
                    <TableFilterContent
                      underlyings={dividendUnderlyings}
                      selectedUnderlyings={dividendFilter.underlyings}
                      onSelectUnderlyings={(vals) => setDividendFilter(prev => ({ ...prev, underlyings: vals }))}
                      onReset={() => setDividendFilter({ underlyings: ["All"] })}
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
                    userEmail={userEmail}
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
