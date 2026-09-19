"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Database,
  Newspaper,
  Pause,
  Play,
  Radar,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Wallet,
  X,
  Zap,
} from "lucide-react";
import DeskChat from "@/components/DeskChat";
import PortfolioPanel from "@/components/PortfolioPanel";
import StockChart, { type OhlcvBar } from "@/components/StockChart";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "");
const POLL_MS = 12_000;

const CHART_INTERVALS = [
  { label: "5m", interval: "5m", period: "5d" },
  { label: "15m", interval: "15m", period: "60d" },
  { label: "1H", interval: "60m", period: "3mo" },
  { label: "1D", interval: "1d", period: "1y" },
  { label: "1W", interval: "1wk", period: "5y" },
  { label: "1M", interval: "1mo", period: "max" },
] as const;

const INTRADAY_INTERVALS = new Set(["5m", "15m", "60m", "1h"]);

interface Snapshot {
  symbol: string;
  last_price: number;
  market_cap: number;
  fifty_two_week_high: number;
  fifty_two_week_low: number;
  trailing_pe: number | null;
  forward_pe: number | null;
  debt_to_equity: number | null;
  free_cashflow: number | null;
}

interface TechnicalSnapshot {
  sma_50: number | null;
  sma_200: number | null;
  rsi_14: number | null;
  volume_surge_ratio: number | null;
  trend: "BULLISH" | "BEARISH" | "NEUTRAL";
  last_price?: number;
  drawdown_from_high_pct?: number | null;
  golden_cross?: boolean | null;
}

interface NewsItem {
  title: string;
  link: string;
  published?: string;
  summary?: string;
}

interface ScoutProposal {
  symbol: string;
  action: string;
  target_price: number;
  shares: number;
  total_value: number;
  thesis: string;
}

interface TacticalProposal {
  symbol: string;
  action: string;
  target_price: number;
  stop_loss: number | null;
  time_horizon: string;
  setup_type: string;
  confidence: number;
  rationale: string;
}

interface RiskEval {
  approved: boolean;
  adjusted_shares: number;
  adjusted_total_value: number;
  reason: string;
}

interface ScanResult {
  ticker: string;
  snapshot: Snapshot;
  technical: TechnicalSnapshot;
  news: NewsItem[];
  history?: OhlcvBar[];
  proposal: ScoutProposal | null;
  tactical: TacticalProposal | null;
  risk: RiskEval | null;
  tactical_risk: RiskEval | null;
  order: unknown | null;
  tactical_order: unknown | null;
  dry_run: boolean;
  view_only?: boolean;
  message: string;
}

interface Order {
  id: string;
  timestamp: string;
  symbol: string;
  action: string;
  shares: number;
  price: number;
  total_value: number;
  status: string;
  is_dry_run: boolean;
  thesis: string;
  reason: string;
}

interface Recommendation {
  symbol: string;
  horizon: string;
  action: string;
  target_price: number;
  trailing_pe: number | null;
  forward_pe: number | null;
  thesis: string;
  source: string;
  updated_at: string;
}

function formatUsd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }
  return `$${value.toFixed(digits)}`;
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
}

const overviewCache = new Map<string, ScanResult>();
let didBootstrap = false;

export default function Dashboard() {
  const [ticker, setTicker] = useState("AAPL");
  const [loading, setLoading] = useState(false);
  const [sweeping, setSweeping] = useState(false);
  const [recsLoading, setRecsLoading] = useState(true);
  const [chartLoading, setChartLoading] = useState(false);
  const [scanData, setScanData] = useState<ScanResult | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [chartData, setChartData] = useState<OhlcvBar[]>([]);
  const [chartInterval, setChartInterval] = useState<(typeof CHART_INTERVALS)[number]["interval"]>("1d");
  const [error, setError] = useState<string | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const [activeTab, setActiveTab] = useState<"market" | "portfolio">("market");
  const [agentsPaused, setAgentsPaused] = useState(false);
  const [agentsStatusLoading, setAgentsStatusLoading] = useState(true);
  const requestIdRef = useRef(0);
  const historyRequestRef = useRef(0);
  const chartIntervalRef = useRef(chartInterval);
  chartIntervalRef.current = chartInterval;

  const applyOverview = useCallback((data: ScanResult) => {
    setScanData(data);
    if (chartIntervalRef.current === "1d" && data.history?.length) {
      setChartData(data.history);
    }
  }, []);

  const fetchOrders = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/orders`);
      if (res.ok) {
        const data: Order[] = await res.json();
        setOrders(data);
      }
    } catch (err) {
      console.error("Order fetch error:", err);
    }
  }, []);

  const fetchRecommendations = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/recommendations`);
      if (res.ok) {
        const data: Recommendation[] = await res.json();
        setRecommendations(data);
      }
    } catch (err) {
      console.error("Recommendation fetch error:", err);
    } finally {
      setRecsLoading(false);
    }
  }, []);

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/watchlist`);
      if (res.ok) {
        const data: string[] = await res.json();
        setWatchlist(data);
      }
    } catch (err) {
      console.error("Watchlist fetch error:", err);
    }
  }, []);

  const fetchHistory = useCallback(async (symbol: string, interval: string, period: string) => {
    const requestId = ++historyRequestRef.current;
    setChartLoading(true);
    try {
      const params = new URLSearchParams({ interval, period });
      const res = await fetch(`${API_BASE}/api/v1/history/${symbol}?${params.toString()}`);
      if (requestId !== historyRequestRef.current) {
        return;
      }
      if (!res.ok) {
        setChartData([]);
        return;
      }
      const data: OhlcvBar[] = await res.json();
      setChartData(data);
    } catch (err) {
      console.error("History fetch error:", err);
      if (requestId === historyRequestRef.current) {
        setChartData([]);
      }
    } finally {
      if (requestId === historyRequestRef.current) {
        setChartLoading(false);
      }
    }
  }, []);

  const selectTicker = useCallback(
    async (symbolToLoad: string) => {
      const symbol = symbolToLoad.trim().toUpperCase();
      if (!symbol) {
        return;
      }
      const requestId = ++requestIdRef.current;
      setTicker(symbol);
      setError(null);
      const cached = overviewCache.get(symbol);
      if (cached) {
        applyOverview(cached);
      } else {
        setHydrating(true);
        setChartLoading(true);
      }
      try {
        const res = await fetch(`${API_BASE}/api/v1/overview/${symbol}`);
        if (!res.ok) {
          const errJson = await res.json().catch(() => ({}));
          throw new Error(errJson.detail || "Quote request failed");
        }
        const data: ScanResult = await res.json();
        overviewCache.set(symbol, data);
        if (requestId !== requestIdRef.current) {
          return;
        }
        applyOverview(data);
      } catch (err: unknown) {
        if (requestId !== requestIdRef.current) {
          return;
        }
        if (!cached) {
          setError(errorMessage(err, "Could not load ticker"));
        }
      } finally {
        if (requestId === requestIdRef.current) {
          setHydrating(false);
          setChartLoading(false);
        }
      }
    },
    [applyOverview]
  );

  const prefetchTicker = useCallback((symbol: string) => {
    const key = symbol.toUpperCase();
    if (overviewCache.has(key)) {
      return;
    }
    void fetch(`${API_BASE}/api/v1/overview/${key}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: ScanResult | null) => {
        if (data?.ticker) {
          overviewCache.set(data.ticker, data);
        }
      })
      .catch(() => undefined);
  }, []);

  const fetchAgentsStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/agents/status`);
      if (res.ok) {
        const data: { paused: boolean } = await res.json();
        setAgentsPaused(Boolean(data.paused));
      }
    } catch (err) {
      console.error("Agent status fetch error:", err);
    } finally {
      setAgentsStatusLoading(false);
    }
  }, []);

  const toggleAgentsPaused = useCallback(async () => {
    const nextPaused = !agentsPaused;
    setAgentsStatusLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/agents/pause`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused: nextPaused }),
      });
      if (res.ok) {
        const data: { paused: boolean } = await res.json();
        setAgentsPaused(Boolean(data.paused));
      }
    } catch (err) {
      console.error("Agent pause toggle error:", err);
    } finally {
      setAgentsStatusLoading(false);
    }
  }, [agentsPaused]);

  const runScan = useCallback(
    async (symbolToScan: string) => {
      const symbol = symbolToScan.trim().toUpperCase();
      if (!symbol) {
        return;
      }
      if (agentsPaused) {
        setError("Agents are paused. Resume agents from the header to run scans.");
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/api/v1/scan/${symbol}`, {
          method: "POST",
        });
        if (!res.ok) {
          const errJson = await res.json().catch(() => ({}));
          throw new Error(errJson.detail || "Scan request failed");
        }
        const data: ScanResult = await res.json();
        overviewCache.set(symbol, data);
        setScanData(data);
        if (chartIntervalRef.current === "1d" && data.history?.length) {
          setChartData(data.history);
        }
        await Promise.all([fetchOrders(), fetchRecommendations()]);
      } catch (err: unknown) {
        setError(errorMessage(err, "An unexpected error occurred"));
      } finally {
        setLoading(false);
      }
    },
    [agentsPaused, fetchOrders, fetchRecommendations]
  );

  const triggerSweep = useCallback(async () => {
    if (agentsPaused) {
      setError("Agents are paused. Resume agents from the header to run sweeps.");
      return;
    }
    setSweeping(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/sweep`, { method: "POST" });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Sweep request failed");
      }
      const payload = await res.json();
      if (payload.status === "agents paused") {
        setAgentsPaused(true);
        setError("Agents are paused. Background sweeps and scans are stopped.");
        return;
      }
      await Promise.all([fetchRecommendations(), fetchOrders()]);
    } catch (err: unknown) {
      setError(errorMessage(err, "Sweep failed"));
    } finally {
      setSweeping(false);
    }
  }, [agentsPaused, fetchOrders, fetchRecommendations]);

  const addCurrentToWatchlist = useCallback(async () => {
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) {
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/v1/watchlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol }),
      });
      if (res.ok) {
        const data = await res.json();
        setWatchlist(data.watchlist);
      }
    } catch (err) {
      console.error("Watchlist add error:", err);
    }
  }, [ticker]);

  const removeWatchlistSymbol = useCallback(async (symbol: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/watchlist/${symbol}`, {
        method: "DELETE",
      });
      if (res.ok) {
        const data = await res.json();
        setWatchlist(data.watchlist);
      }
    } catch (err) {
      console.error("Watchlist remove error:", err);
    }
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("status") === "SUCCESS") {
      setActiveTab("portfolio");
    }
  }, []);

  useEffect(() => {
    fetchWatchlist();
    fetchOrders();
    fetchRecommendations();
    void fetchAgentsStatus();
    if (!didBootstrap) {
      didBootstrap = true;
      void selectTicker("AAPL");
    }
    const timer = window.setInterval(() => {
      void fetchOrders();
      void fetchRecommendations();
      void fetchWatchlist();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [fetchAgentsStatus, fetchOrders, fetchRecommendations, fetchWatchlist, selectTicker]);

  useEffect(() => {
    watchlist.forEach((symbol, index) => {
      window.setTimeout(() => prefetchTicker(symbol), 250 * (index + 1));
    });
  }, [prefetchTicker, watchlist]);

  useEffect(() => {
    const symbol = scanData?.ticker;
    if (!symbol) {
      return;
    }
    const spec = CHART_INTERVALS.find((item) => item.interval === chartInterval) ?? CHART_INTERVALS[3];
    void fetchHistory(symbol, spec.interval, spec.period);
  }, [scanData?.ticker, chartInterval, fetchHistory]);

  const technical = scanData?.technical;

  const openTickerFromPortfolio = useCallback(
    (symbol: string) => {
      setActiveTab("market");
      void selectTicker(symbol);
    },
    [selectTicker]
  );

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 font-sans p-6">
      <header className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-start md:items-center pb-6 border-b border-neutral-800 gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="h-6 w-6 text-orange-500" />
            <h1 className="text-xl font-bold tracking-tight">MARKET INTELLIGENCE COUNCIL</h1>
          </div>
          <p className="text-xs text-neutral-400 mt-1">
            Dual-horizon desk: fundamental scout, tactical momentum, deterministic risk sandbox.
            Use Ask the desk if a panel is unclear.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          <button
            onClick={() => void toggleAgentsPaused()}
            disabled={agentsStatusLoading}
            className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-2.5 rounded-lg border transition-all disabled:opacity-50 ${
              agentsPaused
                ? "bg-amber-950 border-amber-700 text-amber-200 hover:bg-amber-900"
                : "bg-neutral-900 border-neutral-700 text-neutral-200 hover:bg-neutral-800"
            }`}
            title={
              agentsPaused
                ? "Agents are paused — no background sweeps, scans, or LLM analysis"
                : "Pause background sweeps, scans, and LLM analysis to save credits"
            }
          >
            {agentsPaused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
            {agentsPaused ? "Resume agents" : "Pause agents"}
          </button>
          <div className="relative flex-1 md:w-64 min-w-[12rem]">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-neutral-500" />
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && selectTicker(ticker)}
              placeholder="Ticker (e.g. MSFT, PFE, NVDA)"
              className="w-full bg-neutral-900 border border-neutral-800 rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:border-orange-500 text-neutral-100 uppercase"
            />
          </div>
          <button
            onClick={() => runScan(ticker)}
            disabled={loading || agentsPaused}
            className="flex items-center gap-1.5 bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white text-xs font-semibold px-4 py-2.5 rounded-lg transition-all"
            title={
              agentsPaused
                ? "Resume agents to run scans"
                : "Run Scout + Tactical + Risk Guardian. May record a simulated order."
            }
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Scan
          </button>
        </div>
      </header>

      {agentsPaused && (
        <div className="max-w-7xl mx-auto mt-4 bg-amber-950/40 border border-amber-800/70 text-amber-100 text-xs rounded-lg px-4 py-2">
          Agents are paused. Background sweeps, manual scans, portfolio analysis, and Ask the desk are off until
          you click Resume agents.
        </div>
      )}

      <div className="max-w-7xl mx-auto mt-4 flex gap-2">
        <button
          onClick={() => setActiveTab("market")}
          className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border ${
            activeTab === "market"
              ? "bg-orange-950 border-orange-700 text-orange-200"
              : "bg-neutral-900 border-neutral-800 text-neutral-400 hover:text-neutral-200"
          }`}
        >
          <Activity className="h-3.5 w-3.5" />
          Market desk
        </button>
        <button
          onClick={() => setActiveTab("portfolio")}
          className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border ${
            activeTab === "portfolio"
              ? "bg-cyan-950 border-cyan-700 text-cyan-200"
              : "bg-neutral-900 border-neutral-800 text-neutral-400 hover:text-neutral-200"
          }`}
        >
          <Wallet className="h-3.5 w-3.5" />
          My portfolio
        </button>
      </div>

      {activeTab === "portfolio" ? (
        <div className="max-w-7xl mx-auto mt-6">
          <PortfolioPanel onSelectTicker={openTickerFromPortfolio} agentsPaused={agentsPaused} />
        </div>
      ) : (
        <>
      <div className="max-w-7xl mx-auto mt-4 flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-wide text-neutral-500 font-semibold">Watchlist</span>
        <span className="text-[10px] text-neutral-600">Click to load quotes. Scan is separate.</span>
        {watchlist.map((symbol) => (
          <div
            key={symbol}
            className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border ${
              scanData?.ticker === symbol
                ? "bg-orange-950 border-orange-700 text-orange-200"
                : "bg-neutral-900 border-neutral-800 text-neutral-300"
            }`}
          >
            <button
              onClick={() => void selectTicker(symbol)}
              className="hover:text-white"
            >
              {symbol}
            </button>
            <button
              onClick={() => void removeWatchlistSymbol(symbol)}
              className="text-neutral-500 hover:text-red-400"
              aria-label={`Remove ${symbol}`}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
        <button
          onClick={() => void addCurrentToWatchlist()}
          className="text-[11px] px-2.5 py-1 rounded-full border border-dashed border-neutral-700 text-neutral-400 hover:text-neutral-200"
        >
          + Add {ticker || "ticker"}
        </button>
      </div>

      <main className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6 items-start">
        <div className="lg:col-span-2 space-y-6 min-w-0">
          {hydrating && <div className="text-xs text-neutral-500">Refreshing quotes…</div>}
          {error && (
            <div className="bg-red-950/40 border border-red-800/80 p-4 rounded-xl flex items-center gap-3 text-red-200 text-sm">
              <AlertTriangle className="h-5 w-5 text-red-400 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {scanData && (
            <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-6">
              <div className="flex justify-between items-start gap-4">
                <div>
                  <span className="text-xs font-semibold px-2 py-0.5 rounded bg-neutral-800 text-neutral-300">
                    L1 TELEMETRY
                  </span>
                  <p className="text-[11px] text-neutral-500 mt-1">
                    Live quote and ratios. Candle size below does not re-run the agents.
                  </p>
                  <h2 className="text-3xl font-extrabold mt-2 tracking-tight">{scanData.snapshot.symbol}</h2>
                  <p className="text-2xl font-semibold text-neutral-200 mt-1">
                    {formatUsd(scanData.snapshot.last_price)}
                  </p>
                </div>
                <div className="text-right text-xs text-neutral-400 space-y-1">
                  <div>
                    52W High:{" "}
                    <span className="text-neutral-200">{formatUsd(scanData.snapshot.fifty_two_week_high)}</span>
                  </div>
                  <div>
                    52W Low:{" "}
                    <span className="text-neutral-200">{formatUsd(scanData.snapshot.fifty_two_week_low)}</span>
                  </div>
                  <div>
                    Market Cap:{" "}
                    <span className="text-neutral-200">
                      {scanData.snapshot.market_cap
                        ? `$${(scanData.snapshot.market_cap / 1e9).toFixed(2)}B`
                        : "N/A"}
                    </span>
                  </div>
                  {technical?.trend && (
                    <div>
                      Trend:{" "}
                      <span
                        className={
                          technical.trend === "BULLISH"
                            ? "text-emerald-400"
                            : technical.trend === "BEARISH"
                              ? "text-red-400"
                              : "text-neutral-200"
                        }
                      >
                        {technical.trend}
                        {technical.golden_cross ? " · GOLDEN CROSS" : ""}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-5">
                <div className="flex flex-wrap items-center gap-1.5 mb-2">
                  <span className="text-[10px] uppercase tracking-wide text-neutral-500 font-semibold mr-1">
                    Candles
                  </span>
                  {CHART_INTERVALS.map((item) => (
                    <button
                      key={item.interval}
                      onClick={() => setChartInterval(item.interval)}
                      className={`text-[11px] px-2 py-1 rounded-md border ${
                        chartInterval === item.interval
                          ? "bg-orange-950 border-orange-700 text-orange-200"
                          : "bg-neutral-950 border-neutral-800 text-neutral-400 hover:text-neutral-200"
                      }`}
                      title={`${item.label} bars over ${item.period}`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
                <div className="relative">
                  {chartLoading && (
                    <div className="absolute inset-0 z-10 flex items-center justify-center text-xs text-neutral-500 bg-neutral-950/40 rounded-lg">
                      Loading chart…
                    </div>
                  )}
                  <StockChart
                    data={chartData}
                    height={280}
                    timeVisible={INTRADAY_INTERVALS.has(chartInterval)}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6 pt-4 border-t border-neutral-800/80">
                <Metric
                  label="Trailing P/E"
                  value={scanData.snapshot.trailing_pe?.toFixed(2) ?? "N/A"}
                  hint="Price vs the last 12 months of earnings."
                />
                <Metric
                  label="Forward P/E"
                  value={scanData.snapshot.forward_pe?.toFixed(2) ?? "N/A"}
                  hint="Price vs expected next-year earnings."
                />
                <Metric
                  label="Debt / Equity"
                  value={scanData.snapshot.debt_to_equity ? `${scanData.snapshot.debt_to_equity.toFixed(1)}%` : "N/A"}
                  hint="Leverage. Yahoo often stores this as a percent."
                />
                <Metric
                  label="Free Cash Flow"
                  value={
                    scanData.snapshot.free_cashflow
                      ? `$${(scanData.snapshot.free_cashflow / 1e9).toFixed(1)}B`
                      : "N/A"
                  }
                  hint="Cash left after operations and capex."
                />
                <Metric
                  label="SMA 50"
                  value={technical?.sma_50 ? formatUsd(technical.sma_50) : "N/A"}
                  hint="50-day average price. Calculated on daily bars."
                />
                <Metric
                  label="SMA 200"
                  value={technical?.sma_200 ? formatUsd(technical.sma_200) : "N/A"}
                  hint="200-day average price. Golden cross = 50 above 200."
                />
                <Metric
                  label="RSI 14"
                  value={technical?.rsi_14 ? technical.rsi_14.toFixed(1) : "N/A"}
                  hint="Momentum 0–100. ~70 overbought, ~30 oversold."
                />
                <Metric
                  label="Vol Surge"
                  value={technical?.volume_surge_ratio ? `${technical.volume_surge_ratio.toFixed(2)}x` : "N/A"}
                  hint="Today’s volume vs the 20-day average."
                />
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="h-4 w-4 text-orange-400" />
                <h3 className="text-sm font-semibold tracking-wide uppercase">Fundamental Scout</h3>
                <span className="ml-auto text-[10px] uppercase text-neutral-500">Long Horizon</span>
              </div>
              <p className="text-[11px] text-neutral-500 mb-3">Valuation agent (P/E, debt). Click Scan to generate a thesis.</p>
              {scanData?.proposal ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <ActionBadge action={scanData.proposal.action} />
                    <span className="text-xs text-neutral-300">
                      {scanData.proposal.shares > 0
                        ? `${scanData.proposal.shares} shares @ ${formatUsd(scanData.proposal.target_price)}`
                        : `Target ${formatUsd(scanData.proposal.target_price)}`}
                    </span>
                  </div>
                  <p className="text-xs text-neutral-400 leading-relaxed bg-neutral-950/80 p-3 rounded-lg border border-neutral-800/80">
                    {scanData.proposal.thesis}
                  </p>
                </div>
              ) : (
                <div className="bg-neutral-950/80 border border-neutral-800/80 p-3 rounded-lg text-xs text-neutral-400">
                  {scanData?.view_only
                    ? "Click Scan to run the council on this name."
                    : scanData?.message || "No scan performed yet."}
                </div>
              )}
            </div>

            <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <Zap className="h-4 w-4 text-amber-400" />
                <h3 className="text-sm font-semibold tracking-wide uppercase">Tactical Momentum</h3>
                <span className="ml-auto text-[10px] uppercase text-neutral-500">Short Horizon</span>
              </div>
              <p className="text-[11px] text-neutral-500 mb-3">Short-term rules using RSI, trend, and volume surge.</p>
              {scanData?.tactical ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <ActionBadge action={scanData.tactical.action} />
                    <span className="text-xs text-neutral-300">
                      Target {formatUsd(scanData.tactical.target_price)}
                      {scanData.tactical.stop_loss
                        ? ` · Stop ${formatUsd(scanData.tactical.stop_loss)}`
                        : ""}
                    </span>
                    {scanData.tactical.confidence > 0 && (
                      <span className="text-[10px] text-neutral-500">
                        {(scanData.tactical.confidence * 100).toFixed(0)}% conf
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-neutral-400 leading-relaxed bg-neutral-950/80 p-3 rounded-lg border border-neutral-800/80">
                    {scanData.tactical.rationale}
                  </p>
                </div>
              ) : (
                <div className="bg-neutral-950/80 border border-neutral-800/80 p-3 rounded-lg text-xs text-neutral-400">
                  Awaiting a short-term momentum setup.
                </div>
              )}
            </div>
          </div>

          <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <ShieldCheck className="h-4 w-4 text-cyan-400" />
              <h3 className="text-sm font-semibold tracking-wide uppercase">Risk Guardian</h3>
            </div>
            <p className="text-[11px] text-neutral-500 mb-3">
              Hard position-size caps. Approved/vetoed is a sandbox check, not a live broker.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <RiskPanel title="Scout book" risk={scanData?.risk ?? null} empty="Awaiting scout proposal." />
              <RiskPanel title="Tactical book" risk={scanData?.tactical_risk ?? null} empty="Awaiting tactical proposal." />
            </div>
          </div>

          <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Newspaper className="h-4 w-4 text-neutral-400" />
              <h3 className="text-sm font-semibold tracking-wide uppercase">Ticker News</h3>
            </div>
            <p className="text-[11px] text-neutral-500 mb-3">Recent headlines used as context for the scout.</p>
            {scanData?.news?.length ? (
              <ul className="space-y-2">
                {scanData.news.map((item) => (
                  <li key={item.link || item.title}>
                    <a
                      href={item.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block text-xs text-neutral-300 hover:text-orange-300 leading-relaxed"
                    >
                      {item.title}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-neutral-500">No headlines ingested for this ticker.</p>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-6 min-w-0 lg:sticky lg:top-6">
          <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5 flex flex-col min-h-[280px] max-h-[420px]">
            <div className="flex items-center justify-between pb-4 border-b border-neutral-800 gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <Radar className="h-4 w-4 text-orange-400" />
                <h3 className="text-sm font-bold tracking-wide uppercase truncate">AI Opportunity Screener</h3>
              </div>
              <button
                onClick={() => void triggerSweep()}
                disabled={sweeping || agentsPaused}
                className="shrink-0 flex items-center gap-1 text-[10px] font-semibold uppercase bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50 px-2.5 py-1 rounded-md"
                title={
                  agentsPaused
                    ? "Resume agents to run sweeps"
                    : "Background scan of the watchlist plus a discovery universe."
                }
              >
                <Sparkles className={`h-3 w-3 ${sweeping ? "animate-spin" : ""}`} />
                {sweeping ? "Sweeping" : "Trigger Sweep"}
              </button>
            </div>
            <p className="text-[11px] text-neutral-500 mt-2">
              Saved ideas from scans and sweeps. Click a name to load quotes.
            </p>
            <div className="flex-1 overflow-y-auto mt-4 space-y-3 pr-1">
              {recsLoading ? (
                <p className="text-xs text-neutral-500 text-center py-12">Loading recommendations…</p>
              ) : recommendations.length === 0 ? (
                <p className="text-xs text-neutral-500 text-center py-12">
                  No opportunities yet. Run a sweep to scan the discovery universe.
                </p>
              ) : (
                recommendations.map((rec) => (
                  <button
                    key={`${rec.symbol}-${rec.horizon}`}
                    onClick={() => void selectTicker(rec.symbol)}
                    className="w-full text-left bg-neutral-950/90 border border-neutral-800/80 p-3 rounded-lg text-xs space-y-1.5 hover:border-orange-800/80 transition-colors"
                  >
                    <div className="flex justify-between items-center gap-2">
                      <span className="font-bold text-neutral-200">{rec.symbol}</span>
                      <ActionBadge action={rec.action} />
                    </div>
                    <div className="flex justify-between text-[10px] text-neutral-500 uppercase tracking-wide">
                      <span>{rec.horizon.replaceAll("_", " ")}</span>
                      <span>{formatUsd(rec.target_price)}</span>
                    </div>
                    <p className="text-[11px] text-neutral-500 line-clamp-2">{rec.thesis}</p>
                  </button>
                ))
              )}
            </div>
          </div>

          <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5 flex flex-col min-h-[280px] max-h-[420px]">
            <div className="flex items-center justify-between pb-4 border-b border-neutral-800">
              <div className="flex items-center gap-2">
                <Database className="h-4 w-4 text-neutral-400" />
                <h3 className="text-sm font-bold tracking-wide uppercase">Execution Ledger</h3>
              </div>
              <span className="text-[10px] bg-neutral-800 text-neutral-400 px-2 py-0.5 rounded uppercase font-semibold">
                DuckDB (Local)
              </span>
            </div>
            <p className="text-[11px] text-neutral-500 mt-2">Simulated fills only. Nothing is sent to a real broker.</p>
            <div className="flex-1 overflow-y-auto mt-4 space-y-3 pr-1">
              {orders.length === 0 ? (
                <p className="text-xs text-neutral-500 text-center py-12">No simulated orders recorded yet.</p>
              ) : (
                orders.map((ord) => (
                  <div
                    key={ord.id}
                    className="bg-neutral-950/90 border border-neutral-800/80 p-3 rounded-lg text-xs space-y-1"
                  >
                    <div className="flex justify-between items-center font-bold">
                      <span className="text-neutral-200 flex items-center gap-1">
                        {ord.symbol}
                        {ord.action === "BUY" ? (
                          <ArrowUpRight className="h-3 w-3 text-emerald-400" />
                        ) : (
                          <ArrowDownRight className="h-3 w-3 text-red-400" />
                        )}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-neutral-900 border border-neutral-700 text-neutral-300">
                        {ord.status}
                      </span>
                    </div>
                    <div className="text-neutral-400 flex justify-between">
                      <span>
                        {ord.shares} shares @ {formatUsd(ord.price)}
                      </span>
                      <span className="font-semibold text-neutral-300">{formatUsd(ord.total_value)}</span>
                    </div>
                    <p className="text-[11px] text-neutral-500 truncate pt-1">{ord.reason}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </main>
        </>
      )}
      <DeskChat
        apiBase={API_BASE}
        agentsPaused={agentsPaused}
        context={{
          ticker: scanData?.ticker ?? ticker,
          chart_interval: chartInterval,
          snapshot: scanData?.snapshot ?? null,
          technical: scanData?.technical ?? null,
          proposal: scanData?.proposal ?? null,
          tactical: scanData?.tactical ?? null,
          risk: scanData?.risk ?? null,
          tactical_risk: scanData?.tactical_risk ?? null,
          view_only: scanData?.view_only,
        }}
      />
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-neutral-950/60 border border-neutral-800/60 p-3 rounded-lg" title={hint}>
      <span className="text-[11px] text-neutral-500 block uppercase">{label}</span>
      <span className="text-base font-bold text-neutral-200">{value}</span>
      {hint && <span className="text-[10px] text-neutral-600 mt-1 block leading-snug">{hint}</span>}
    </div>
  );
}

function ActionBadge({ action }: { action: string }) {
  const tone =
    action === "BUY"
      ? "bg-emerald-950 border-emerald-700 text-emerald-300"
      : action === "SELL"
        ? "bg-red-950 border-red-700 text-red-300"
        : "bg-amber-950 border-amber-700 text-amber-300";
  return <span className={`px-2 py-0.5 rounded border text-xs font-bold ${tone}`}>{action}</span>;
}

function RiskPanel({ title, risk, empty }: { title: string; risk: RiskEval | null; empty: string }) {
  if (!risk) {
    return (
      <div className="bg-neutral-950/80 border border-neutral-800/80 p-3 rounded-lg text-xs text-neutral-400">
        <div className="text-[10px] uppercase text-neutral-500 mb-1">{title}</div>
        {empty}
      </div>
    );
  }
  return (
    <div className="space-y-2 bg-neutral-950/80 border border-neutral-800/80 p-3 rounded-lg">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase text-neutral-500">{title}</span>
        <span
          className={`px-2 py-0.5 rounded text-xs font-bold border ${
            risk.approved
              ? "bg-cyan-950 border-cyan-700 text-cyan-300"
              : "bg-red-950 border-red-700 text-red-300"
          }`}
        >
          {risk.approved ? "APPROVED" : "VETOED"}
        </span>
        <span className="text-xs text-neutral-300 ml-auto">{formatUsd(risk.adjusted_total_value)}</span>
      </div>
      <p className="text-xs text-neutral-400 leading-relaxed">{risk.reason}</p>
    </div>
  );
}
