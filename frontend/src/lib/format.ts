export const pct = (p: number | null | undefined, d = 1): string =>
  p === null || p === undefined || Number.isNaN(p) ? "—" : `${(p * 100).toFixed(d)}%`;

export const num = (x: number | null | undefined, d = 3): string =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : x.toFixed(d);

export const pp = (x: number | null | undefined, d = 1): string =>
  x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(d)} pp`;

export const relPct = (x: number | null | undefined): string =>
  x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(0)}%`;

export const money = (x: number | null | undefined): string => {
  if (x === null || x === undefined) return "—";
  if (x >= 1e6) return `$${(x / 1e6).toFixed(1)}M`;
  if (x >= 1e3) return `$${(x / 1e3).toFixed(0)}k`;
  return `$${x.toFixed(0)}`;
};

export const date = (ts: number | null | undefined): string =>
  ts ? new Date(ts * 1000).toISOString().slice(0, 10) : "—";

export const dateTime = (ts: number | null | undefined): string =>
  ts ? new Date(ts * 1000).toISOString().slice(0, 16).replace("T", " ") + "Z" : "—";

export const ago = (iso: string | number | null | undefined): string => {
  if (!iso) return "never";
  const t = typeof iso === "number" ? iso * 1000 : Date.parse(iso);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};

export const ci = (c: [number, number] | null | undefined, d = 3): string =>
  c ? `[${c[0].toFixed(d)}, ${c[1].toFixed(d)}]` : "—";

export const label = (s: string | null | undefined): string =>
  (s ?? "—").replace(/_/g, " ");

export const CATEGORY_LABEL: Record<string, string> = {
  fed: "Fed & rates",
  crypto_regulation: "Crypto regulation",
  macro: "Macro data",
  crypto_events: "Crypto events",
  crypto_price: "Crypto price (excluded)",
};
