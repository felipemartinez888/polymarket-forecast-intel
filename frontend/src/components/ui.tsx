import type { ReactNode } from "react";
import { href } from "../lib/router";
import { pct, pp } from "../lib/format";

export function Card({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <header className="card-h">
          <span>{title}</span>
          <span className="normal-case tracking-normal">{right}</span>
        </header>
      )}
      <div>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "up" | "down" | "accent" }) {
  const c = tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "accent" ? "text-accent" : "text-ink";
  return (
    <div className="card px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-wider text-mute">{label}</div>
      <div className={`font-mono text-xl mt-0.5 ${c}`}>{value}</div>
      {sub && <div className="text-xs text-dim mt-0.5">{sub}</div>}
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  final: "border-up/40 text-up",
  unresolved: "border-info/40 text-info",
  proposed: "border-accent/50 text-accent",
  disputed: "border-down/50 text-down",
  invalid: "border-dim text-mute",
  closed_unverified: "border-down/40 text-down",
  pending: "border-info/40 text-info",
  not_scoreable: "border-dim text-mute",
};

export function StatusChip({ s }: { s: string | null | undefined }) {
  const v = s ?? "unknown";
  return <span className={`chip ${STATUS_TONE[v] ?? "border-line text-mute"}`}>{v.replace(/_/g, " ")}</span>;
}

export function QualityChip({ q }: { q: string | null | undefined }) {
  if (!q) return <span className="text-dim">—</span>;
  const tone = q === "A" ? "border-up/40 text-up" : q === "B" ? "border-info/40 text-info" : "border-accent/40 text-accent";
  const title = q === "A" ? "Externally verified against an official source" : q === "B" ? "UMA oracle resolved" : "Settlement prices only (no UMA status reported)";
  return <span className={`chip ${tone}`} title={title}>Q-{q}</span>;
}

export function RelevanceChip({ r }: { r: string | null | undefined }) {
  if (!r) return null;
  const tone = r === "high" ? "border-accent/50 text-accent" : r === "medium" ? "border-info/40 text-info" : "border-line text-mute";
  return <span className={`chip ${tone}`} title="Potential relevance to crypto investors (rule-based, not a price prediction)">{r}</span>;
}

export function ProbBar({ p }: { p: number | null | undefined }) {
  if (p === null || p === undefined) return <span className="text-dim">—</span>;
  return (
    <div className="flex items-center gap-2 min-w-[110px]">
      <div className="h-1.5 flex-1 bg-line rounded overflow-hidden">
        <div className="h-full bg-accent" style={{ width: `${Math.max(0, Math.min(1, p)) * 100}%` }} />
      </div>
      <span className="font-mono text-xs w-12 text-right">{pct(p)}</span>
    </div>
  );
}

export function Delta({ v, flag }: { v: number | null | undefined; flag?: boolean }) {
  if (v === null || v === undefined) return <span className="text-dim">—</span>;
  const c = v > 0 ? "text-up" : v < 0 ? "text-down" : "text-mute";
  return (
    <span className={`font-mono text-xs ${c} ${flag ? "font-semibold" : ""}`}>
      {pp(v)}
      {flag && <span className="ml-1 text-accent" title="Exceeds configured threshold — research signal only">▲</span>}
    </span>
  );
}

export function MarketLink({ id, children }: { id: string; children: ReactNode }) {
  return <a className="hover:text-accent" href={href("market", id)}>{children}</a>;
}

export function Ext({ url, children }: { url: string | null | undefined; children: ReactNode }) {
  if (!url) return <span className="text-dim">—</span>;
  return <a className="lnk" href={url} target="_blank" rel="noopener noreferrer">{children} ↗</a>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-3 py-6 text-sm text-mute text-center">{children}</div>;
}

export function Loading() {
  return <div className="p-8 text-mute text-sm animate-pulse">Loading data…</div>;
}

export function ErrorBox({ error }: { error: string }) {
  const noData = /404/.test(error);
  return (
    <div className="card p-4 text-sm">
      {noData ? (
        <>
          <div className="text-accent font-medium">No collected data is deployed yet.</div>
          <p className="text-mute mt-1">
            The dashboard only shows data gathered by the scheduled pipeline from Polymarket's public APIs. Run the
            “Collect data” workflow once (see the README), then redeploy. No placeholder or sample data is ever shown.
          </p>
        </>
      ) : (
        <div className="text-down">Failed to load data: {error}</div>
      )}
    </div>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="text-xs text-dim leading-relaxed">{children}</p>;
}

export function Scroll({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto">{children}</div>;
}
