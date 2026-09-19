"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { MessageCircle, Send } from "lucide-react";

interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

const STARTERS = [
  "How should I rebalance across my Roth and taxable accounts?",
  "Which holdings should I trim based on my cost basis?",
  "How much cash should stay in each account?",
  "What would you add to my Roth IRA right now?",
];

export default function PortfolioChat({
  apiBase,
  agentsPaused,
  hasHoldings,
}: {
  apiBase: string;
  agentsPaused: boolean;
  hasHoldings: boolean;
}) {
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [turns, setTurns] = useState<ChatTurn[]>([
    {
      role: "assistant",
      content:
        "Ask about your real holdings, cost basis, rebalancing across accounts, or follow-ups on tailored insights. Sync holdings and run Analyze first for the richest answers.",
    },
  ]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || pending || agentsPaused) {
      return;
    }
    const nextTurns = [...turns, { role: "user" as const, content: message }];
    setTurns(nextTurns);
    setInput("");
    setPending(true);
    try {
      const res = await fetch(`${apiBase}/api/v1/portfolio/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          history: nextTurns.slice(-8),
        }),
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Portfolio chat request failed");
      }
      const data = await res.json();
      setTurns([...nextTurns, { role: "assistant", content: data.reply }]);
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Could not reach the portfolio advisor.";
      setTurns([...nextTurns, { role: "assistant", content: detail }]);
    } finally {
      setPending(false);
    }
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void send(input);
  };

  return (
    <div className="bg-neutral-900/60 border border-neutral-800 rounded-xl p-5 flex flex-col min-h-[320px] max-h-[480px]">
      <div className="flex items-center gap-2 mb-3 pb-3 border-b border-neutral-800">
        <MessageCircle className="h-4 w-4 text-cyan-400" />
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide">Portfolio advisor chat</h3>
          <p className="text-[11px] text-neutral-500">
            {agentsPaused
              ? "Resume agents to chat"
              : hasHoldings
                ? "Uses your synced holdings, average cost, and account goals"
                : "Sync holdings first for account-specific answers"}
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-2 pr-1 mb-3">
        {turns.map((turn, index) => (
          <div
            key={`${turn.role}-${index}`}
            className={`text-xs leading-relaxed rounded-lg px-3 py-2 ${
              turn.role === "user"
                ? "bg-cyan-950/50 border border-cyan-800/50 text-cyan-50 ml-6"
                : "bg-neutral-950/80 border border-neutral-800/80 text-neutral-300 mr-4"
            }`}
          >
            {turn.content}
          </div>
        ))}
        {pending && <p className="text-[11px] text-neutral-500">Thinking…</p>}
        <div ref={bottomRef} />
      </div>

      <div className="flex flex-wrap gap-1.5 mb-3">
        {STARTERS.map((starter) => (
          <button
            key={starter}
            onClick={() => void send(starter)}
            disabled={pending || agentsPaused || !hasHoldings}
            className="text-[10px] px-2 py-1 rounded-full border border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-600 disabled:opacity-50"
          >
            {starter}
          </button>
        ))}
      </div>

      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={
            agentsPaused ? "Agents paused" : "Ask about a holding or rebalance plan…"
          }
          disabled={agentsPaused}
          className="flex-1 bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-xs text-neutral-100 focus:outline-none focus:border-cyan-600 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={pending || agentsPaused || !input.trim()}
          className="bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white rounded-lg px-3"
          aria-label="Send"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </form>
    </div>
  );
}
