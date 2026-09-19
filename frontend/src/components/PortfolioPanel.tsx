"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Link2,
  RefreshCw,
  Shield,
  Sparkles,
  TrendingUp,
  Wallet,
} from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "");

type AccountType = "roth_ira" | "taxable" | "traditional_ira" | "other";

interface PortfolioAccount {
  id: string;
  name: string;
  account_type: AccountType;
  brokerage: string;
  last_synced_at?: string | null;
}

interface PortfolioHolding {
  account_id: string;
  account_name: string;
  account_type: AccountType;
  symbol: string;
  quantity: number;
  average_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
}

interface PortfolioInsight {
  id: string;
  account_id?: string;
  account_type?: AccountType;
  symbol?: string | null;
  priority: string;
  action: string;
  title: string;
  body: string;
}

interface PortfolioDashboard {
  connected: boolean;
  snaptrade_configured: boolean;
  accounts: PortfolioAccount[];
  holdings: PortfolioHolding[];
  insights: PortfolioInsight[];
  total_value: number;
  value_by_account_type: Record<string, number>;
  analysis_summary?: string;
}

const ACCOUNT_LABELS: Record<AccountType, string> = {
  roth_ira: "Roth IRA",
  taxable: "Taxable brokerage",
  traditional_ira: "Traditional IRA",
  other: "Other",
};

function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export default function PortfolioPanel({ onSelectTicker }: { onSelectTicker: (symbol: string) => void }) {
  const [data, setData] = useState<PortfolioDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPortfolio = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/portfolio`);
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Could not load portfolio");
      }
      setData(await res.json());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Portfolio load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPortfolio();
  }, [loadPortfolio]);

  const connectRobinhood = async () => {
    setConnecting(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/portfolio/connect`, { method: "POST" });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Could not start Robinhood connection");
      }
      const payload = await res.json();
      window.open(payload.portal_url, "_blank", "noopener,noreferrer");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setConnecting(false);
    }
  };

  const syncHoldings = async () => {
    setSyncing(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/portfolio/sync`, { method: "POST" });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Sync failed");
      }
      await loadPortfolio();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const analyzePortfolio = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/portfolio/analyze`, { method: "POST" });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Analysis failed");
      }
      setData(await res.json());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  };

  const updateAccountType = async (accountId: string, accountType: AccountType) => {
    try {
      await fetch(`${API_BASE}/api/v1/portfolio/accounts/${accountId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_type: accountType }),
      });
      await loadPortfolio();
    } catch (err) {
      console.error("Account type update failed:", err);
    }
  };

  if (loading && !data) {
    return <p className="text-sm text-neutral-500">Loading portfolio…</p>;
  }

  const rothValue = data?.value_by_account_type?.roth_ira ?? 0;
  const taxableValue = data?.value_by_account_type?.taxable ?? 0;

  return (
    <div className="space-y-6">
      <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-6">
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Wallet className="h-5 w-5 text-cyan-400" />
              <h2 className="text-lg font-bold tracking-tight">My Portfolio</h2>
            </div>
            <p className="text-sm text-neutral-400 mt-2 max-w-2xl">
              Read-only Robinhood sync via SnapTrade. Scout and Tactical research your actual holdings and
              produce separate guidance for long-term Roth growth vs. relatively safe taxable growth.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => void connectRobinhood()}
              disabled={connecting || !data?.snaptrade_configured}
              className="flex items-center gap-1.5 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white text-xs font-semibold px-3 py-2 rounded-lg"
              title={
                data?.snaptrade_configured
                  ? "Open secure read-only Robinhood login"
                  : "SnapTrade keys not configured on server"
              }
            >
              <Link2 className={`h-3.5 w-3.5 ${connecting ? "animate-pulse" : ""}`} />
              Connect Robinhood
            </button>
            <button
              onClick={() => void syncHoldings()}
              disabled={syncing || !data?.connected}
              className="flex items-center gap-1.5 bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50 text-white text-xs font-semibold px-3 py-2 rounded-lg"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
              Sync holdings
            </button>
            <button
              onClick={() => void analyzePortfolio()}
              disabled={analyzing || !data?.holdings?.length}
              className="flex items-center gap-1.5 bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white text-xs font-semibold px-3 py-2 rounded-lg"
            >
              <Sparkles className={`h-3.5 w-3.5 ${analyzing ? "animate-spin" : ""}`} />
              Analyze portfolio
            </button>
          </div>
        </div>

        {!data?.snaptrade_configured && (
          <div className="mt-4 text-xs text-amber-300 bg-amber-950/40 border border-amber-800/60 rounded-lg p-3">
            Add <code className="text-amber-100">SNAPTRADE_CLIENT_ID</code> and{" "}
            <code className="text-amber-100">SNAPTRADE_CONSUMER_KEY</code> in Render environment variables
            (free SnapTrade developer account). Connection is read-only — no trades are placed.
          </div>
        )}

        {error && (
          <div className="mt-4 bg-red-950/40 border border-red-800/80 p-3 rounded-lg flex items-center gap-2 text-red-200 text-sm">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-6">
          <MetricCard label="Total portfolio" value={formatUsd(data?.total_value ?? 0)} />
          <MetricCard label="Roth IRA" value={formatUsd(rothValue)} hint="Long-term, tax-free growth focus" />
          <MetricCard
            label="Taxable brokerage"
            value={formatUsd(taxableValue)}
            hint="Quality growth with modest tactical flexibility"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Shield className="h-4 w-4 text-emerald-400" />
            <h3 className="text-sm font-semibold uppercase tracking-wide">Accounts</h3>
          </div>
          {!data?.accounts?.length ? (
            <p className="text-xs text-neutral-500">
              No accounts linked yet. Connect Robinhood, complete the portal login, then click Sync holdings.
            </p>
          ) : (
            <div className="space-y-3">
              {data.accounts.map((account) => (
                <div
                  key={account.id}
                  className="bg-neutral-950/80 border border-neutral-800/80 rounded-lg p-3 text-xs space-y-2"
                >
                  <div className="flex justify-between gap-2">
                    <span className="font-semibold text-neutral-200">{account.name}</span>
                    <span className="text-neutral-500 uppercase">{account.brokerage}</span>
                  </div>
                  <select
                    value={account.account_type}
                    onChange={(event) =>
                      void updateAccountType(account.id, event.target.value as AccountType)
                    }
                    className="w-full bg-neutral-900 border border-neutral-800 rounded-md px-2 py-1.5 text-neutral-200"
                  >
                    {Object.entries(ACCOUNT_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="h-4 w-4 text-orange-400" />
            <h3 className="text-sm font-semibold uppercase tracking-wide">Tailored insights</h3>
          </div>
          {data?.analysis_summary && (
            <p className="text-xs text-neutral-300 mb-3 leading-relaxed">{data.analysis_summary}</p>
          )}
          {!data?.insights?.length ? (
            <p className="text-xs text-neutral-500">
              Run Analyze portfolio after syncing holdings. Insights are split by Roth vs taxable goals.
            </p>
          ) : (
            <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
              {data.insights.map((insight) => (
                <div
                  key={insight.id}
                  className="bg-neutral-950/80 border border-neutral-800/80 rounded-lg p-3 text-xs space-y-1"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold text-neutral-200">{insight.title}</span>
                    <span className="px-1.5 py-0.5 rounded border border-neutral-700 text-[10px] uppercase">
                      {insight.action}
                    </span>
                    {insight.symbol && (
                      <button
                        onClick={() => onSelectTicker(insight.symbol!)}
                        className="text-orange-300 hover:text-orange-200"
                      >
                        {insight.symbol}
                      </button>
                    )}
                  </div>
                  <p className="text-neutral-400 leading-relaxed">{insight.body}</p>
                  {insight.account_type && (
                    <p className="text-[10px] text-neutral-600 uppercase">
                      {ACCOUNT_LABELS[insight.account_type as AccountType] ?? insight.account_type}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wide mb-4">Holdings</h3>
        {!data?.holdings?.length ? (
          <p className="text-xs text-neutral-500">Synced positions will appear here.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-neutral-500 border-b border-neutral-800">
                  <th className="text-left py-2 pr-3">Symbol</th>
                  <th className="text-left py-2 pr-3">Account</th>
                  <th className="text-right py-2 pr-3">Qty</th>
                  <th className="text-right py-2 pr-3">Value</th>
                  <th className="text-right py-2">P/L</th>
                </tr>
              </thead>
              <tbody>
                {data.holdings.map((holding) => (
                  <tr key={`${holding.account_id}-${holding.symbol}`} className="border-b border-neutral-900/80">
                    <td className="py-2 pr-3">
                      <button
                        onClick={() => onSelectTicker(holding.symbol)}
                        className="font-semibold text-orange-300 hover:text-orange-200"
                      >
                        {holding.symbol}
                      </button>
                    </td>
                    <td className="py-2 pr-3 text-neutral-400">
                      {ACCOUNT_LABELS[holding.account_type] ?? holding.account_name}
                    </td>
                    <td className="py-2 pr-3 text-right text-neutral-300">{holding.quantity.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-right text-neutral-200">{formatUsd(holding.market_value)}</td>
                    <td
                      className={`py-2 text-right ${
                        holding.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400"
                      }`}
                    >
                      {formatUsd(holding.unrealized_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-neutral-950/60 border border-neutral-800/60 p-3 rounded-lg">
      <span className="text-[11px] text-neutral-500 block uppercase">{label}</span>
      <span className="text-lg font-bold text-neutral-100">{value}</span>
      {hint && <span className="text-[10px] text-neutral-600 mt-1 block">{hint}</span>}
    </div>
  );
}
