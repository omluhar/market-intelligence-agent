"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Database,
  Newspaper,
  Radar,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  X,
  Zap,
} from "lucide-react";
import StockChart, { type OhlcvBar } from "@/components/StockChart";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "");
const POLL_MS = 12_000;
let didBootstrapScan = false;

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
  stop_loss: number;
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
  proposal: ScoutProposal | null;
  tactical: TacticalProposal | null;
  risk: RiskEval | null;
  tactical_risk: RiskEval | null;
  order: unknown | null;
  tactical_order: unknown | null;
  dry_run: boolean;
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
  const [error, setError] = useState<string | null>(null);

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

  const fetchHistory = useCallback(async (symbol: string) => {
    setChartLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/history/${symbol}`);
      if (!res.ok) {
        setChartData([]);
        return;
      }
      const data: OhlcvBar[] = await res.json();
      setChartData(data);
    } catch (err) {
      console.error("History fetch error:", err);
      setChartData([]);
    } finally {
      setChartLoading(false);
    }
  }, []);

  const runScan = useCallback(
    async (symbolToScan: string) => {
      const symbol = symbolToScan.trim().toUpperCase();
      if (!symbol) {
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
        setScanData(data);
        await Promise.all([fetchOrders(), fetchRecommendations(), fetchHistory(symbol)]);
      } catch (err: unknown) {
        setError(errorMessage(err, "An unexpected error occurred"));
      } finally {
        setLoading(false);
      }
    },
    [fetchHistory, fetchOrders, fetchRecommendations]
  );

  const triggerSweep = useCallback(async () => {
    setSweeping(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/sweep`, { method: "POST" });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Sweep request failed");
      }
      await Promise.all([fetchRecommendations(), fetchOrders()]);
    } catch (err: unknown) {
      setError(errorMessage(err, "Sweep failed"));
    } finally {
      setSweeping(false);
    }
  }, [fetchOrders, fetchRecommendations]);

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
    fetchWatchlist();
    fetchOrders();
    fetchRecommendations();
    if (!didBootstrapScan) {
      didBootstrapScan = true;
      void runScan("AAPL");
    }
    const timer = window.setInterval(() => {
      void fetchOrders();
      void fetchRecommendations();
      void fetchWatchlist();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [fetchOrders, fetchRecommendations, fetchWatchlist, runScan]);

  const technical = scanData?.technical;

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 font-sans p-6">
      <header className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-start md:items-center pb-6 border-b border-neutral-800 gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="h-6 w-6 text-orange-500" />
            <h1 className="text-xl font-bold tracking-tight">MARKET INTELLIGENCE COUNCIL</h1>
          </div>
          <p className="text-xs text-neutral-400 mt-1">
            Dual-horizon desk: fundamental scout, tactical momentum, deterministic risk sandbox
          </p>
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto">
          <div className="relative flex-1 md:w-64">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-neutral-500" />
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && runScan(ticker)}
              placeholder="Ticker (e.g. MSFT, PFE, NVDA)"
              className="w-full bg-neutral-900 border border-neutral-800 rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:border-orange-500 text-neutral-100 uppercase"
            />
          </div>
          <button
            onClick={() => runScan(ticker)}
            disabled={loading}
            className="flex items-center gap-1.5 bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white text-xs font-semibold px-4 py-2.5 rounded-lg transition-all"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Scan
          </button>
        </div>
      </header>

      <div className="max-w-7xl mx-auto mt-4 flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-wide text-neutral-500 font-semibold">Watchlist</span>
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
              onClick={() => {
                setTicker(symbol);
                void runScan(symbol);
              }}
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

              <div className="mt-5 relative">
                {chartLoading && (
                  <div className="absolute inset-0 z-10 flex items-center justify-center text-xs text-neutral-500 bg-neutral-950/40 rounded-lg">
                    Loading chart…
                  </div>
                )}
                <StockChart data={chartData} height={280} />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6 pt-4 border-t border-neutral-800/80">
                <Metric label="Trailing P/E" value={scanData.snapshot.trailing_pe?.toFixed(2) ?? "N/A"} />
                <Metric label="Forward P/E" value={scanData.snapshot.forward_pe?.toFixed(2) ?? "N/A"} />
                <Metric
                  label="Debt / Equity"
                  value={scanData.snapshot.debt_to_equity ? `${scanData.snapshot.debt_to_equity.toFixed(1)}%` : "N/A"}
                />
                <Metric
                  label="Free Cash Flow"
                  value={
                    scanData.snapshot.free_cashflow
                      ? `$${(scanData.snapshot.free_cashflow / 1e9).toFixed(1)}B`
                      : "N/A"
                  }
                />
                <Metric label="SMA 50" value={technical?.sma_50 ? formatUsd(technical.sma_50) : "N/A"} />
                <Metric label="SMA 200" value={technical?.sma_200 ? formatUsd(technical.sma_200) : "N/A"} />
                <Metric label="RSI 14" value={technical?.rsi_14 ? technical.rsi_14.toFixed(1) : "N/A"} />
                <Metric
                  label="Vol Surge"
                  value={technical?.volume_surge_ratio ? `${technical.volume_surge_ratio.toFixed(2)}x` : "N/A"}
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
              {scanData?.proposal ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <ActionBadge action={scanData.proposal.action} />
                    <span className="text-xs text-neutral-300">
                      {scanData.proposal.shares} shares @ {formatUsd(scanData.proposal.target_price)}
                    </span>
                  </div>
                  <p className="text-xs text-neutral-400 leading-relaxed bg-neutral-950/80 p-3 rounded-lg border border-neutral-800/80">
                    {scanData.proposal.thesis}
                  </p>
                </div>
              ) : (
                <div className="bg-neutral-950/80 border border-neutral-800/80 p-3 rounded-lg text-xs text-neutral-400">
                  {scanData?.message || "No scan performed yet."}
                </div>
              )}
            </div>

            <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <Zap className="h-4 w-4 text-amber-400" />
                <h3 className="text-sm font-semibold tracking-wide uppercase">Tactical Momentum</h3>
                <span className="ml-auto text-[10px] uppercase text-neutral-500">Short Horizon</span>
              </div>
              {scanData?.tactical ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <ActionBadge action={scanData.tactical.action} />
                    <span className="text-xs text-neutral-300">
                      Target {formatUsd(scanData.tactical.target_price)} · Stop {formatUsd(scanData.tactical.stop_loss)}
                    </span>
                    <span className="text-[10px] text-neutral-500">
                      {(scanData.tactical.confidence * 100).toFixed(0)}% conf
                    </span>
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
                disabled={sweeping}
                className="shrink-0 flex items-center gap-1 text-[10px] font-semibold uppercase bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50 px-2.5 py-1 rounded-md"
              >
                <Sparkles className={`h-3 w-3 ${sweeping ? "animate-spin" : ""}`} />
                {sweeping ? "Sweeping" : "Trigger Sweep"}
              </button>
            </div>
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
                    onClick={() => {
                      setTicker(rec.symbol);
                      void runScan(rec.symbol);
                    }}
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
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-neutral-950/60 border border-neutral-800/60 p-3 rounded-lg">
      <span className="text-[11px] text-neutral-500 block uppercase">{label}</span>
      <span className="text-base font-bold text-neutral-200">{value}</span>
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
