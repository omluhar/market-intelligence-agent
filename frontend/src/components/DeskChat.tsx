"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { MessageCircle, Send, X } from "lucide-react";

export interface DeskChatContext {
  ticker: string | null;
  chart_interval: string;
  snapshot?: unknown;
  technical?: unknown;
  proposal?: unknown;
  tactical?: unknown;
  risk?: unknown;
  tactical_risk?: unknown;
  view_only?: boolean;
}

interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

const STARTERS = [
  "What am I looking at on this screen?",
  "What does RSI 14 mean for this ticker?",
  "What's the difference between Scout and Tactical?",
  "What happens when I click Scan?",
];

export default function DeskChat({
  apiBase,
  context,
  agentsPaused = false,
}: {
  apiBase: string;
  context: DeskChatContext;
  agentsPaused?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [turns, setTurns] = useState<ChatTurn[]>([
    {
      role: "assistant",
      content:
        "Ask me what any panel, ratio, or button means. I can also explain the ticker you have open.",
    },
  ]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, open]);

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
      const res = await fetch(`${apiBase}/api/v1/desk-chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          history: nextTurns.slice(-8),
          context,
        }),
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Desk guide request failed");
      }
      const data = await res.json();
      setTurns([...nextTurns, { role: "assistant", content: data.reply }]);
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Could not reach the desk guide.";
      setTurns([...nextTurns, { role: "assistant", content: detail }]);
    } finally {
      setPending(false);
    }
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void send(input);
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-orange-600 hover:bg-orange-500 text-white text-xs font-semibold px-4 py-3 shadow-lg"
      >
        <MessageCircle className="h-4 w-4" />
        Ask the desk
      </button>
    );
  }

  return (
    <div className="fixed bottom-5 right-5 z-40 w-[min(100%-1.5rem,380px)] h-[min(70vh,520px)] bg-neutral-950 border border-neutral-800 rounded-2xl shadow-2xl flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800">
        <div>
          <p className="text-sm font-semibold">Desk guide</p>
          <p className="text-[11px] text-neutral-500">
            {agentsPaused
              ? "Paused — resume agents to chat"
              : context.ticker
                ? `Context: ${context.ticker}`
                : "Explains this interface"}
          </p>
        </div>
        <button onClick={() => setOpen(false)} className="text-neutral-400 hover:text-white" aria-label="Close chat">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {turns.map((turn, index) => (
          <div
            key={`${turn.role}-${index}`}
            className={`text-xs leading-relaxed rounded-xl px-3 py-2 ${
              turn.role === "user"
                ? "bg-orange-950/70 border border-orange-800/60 text-orange-50 ml-8"
                : "bg-neutral-900 border border-neutral-800 text-neutral-300 mr-6"
            }`}
          >
            {turn.content}
          </div>
        ))}
        {pending && <p className="text-[11px] text-neutral-500">Thinking…</p>}
        <div ref={bottomRef} />
      </div>
      <div className="px-3 pb-2 flex flex-wrap gap-1.5">
        {STARTERS.map((starter) => (
          <button
            key={starter}
            onClick={() => void send(starter)}
            disabled={pending || agentsPaused}
            className="text-[10px] px-2 py-1 rounded-full border border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-600 disabled:opacity-50"
          >
            {starter}
          </button>
        ))}
      </div>
      <form onSubmit={onSubmit} className="p-3 border-t border-neutral-800 flex gap-2">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={agentsPaused ? "Agents paused" : "What is Trailing P/E?"}
          disabled={agentsPaused}
          className="flex-1 bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-2 text-xs text-neutral-100 focus:outline-none focus:border-orange-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={pending || agentsPaused || !input.trim()}
          className="bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white rounded-lg px-3"
          aria-label="Send"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </form>
    </div>
  );
}
