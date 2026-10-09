import { useMemo, useState } from "react";
import { useData, download, toCsv, dataUrl } from "../lib/data";
import { CATEGORY_LABEL, date, label, money, num, pct } from "../lib/format";
import { HORIZONS, type HorizonKey, type MarketRow, type Meta } from "../types";
import { Card, Empty, ErrorBox, Loading, MarketLink, ProbBar, QualityChip, RelevanceChip, Scroll, StatusChip } from "../components/ui";

type Markets = Meta & { markets: MarketRow[] };

// Synonyms so that searching "rate cuts" also finds "25 bps decrease", "FOMC" finds "Fed decision", etc.
const SYNONYMS: Record<string, string[]> = {
  fed: ["fed", "fomc", "federal reserve"], fomc: ["fomc", "fed decision", "fed"], "interest rates": ["rate", "bps", "fed"],
  "rate cuts": ["cut", "decrease", "lower"], "rate hikes": ["hike", "increase", "raise"], "clarity act": ["clarity"],
  inflation: ["inflation", "cpi", "pce"], stablecoins: ["stablecoin", "genius"], "bitcoin etf": ["bitcoin etf", "btc etf"],
};

function matches(r: MarketRow, q: string): boolean {
  if (!q) return true;
  const hay = `${r.question} ${r.event_title} ${r.group_item_title ?? ""} ${r.subcategory ?? ""} ${r.category ?? ""}`.toLowerCase();
  const key = q.toLowerCase().trim();
  const alts = SYNONYMS[key] ?? [key];
  return alts.some((a) => hay.includes(a));
}

export default function Explorer() {
  const { data, error, loading } = useData<Markets>("derived/markets.json");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [sub, setSub] = useState("");
  const [status, setStatus] = useState("");
  const [h, setH] = useState<HorizonKey>("final");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [pMin, setPMin] = useState(0);
  const [pMax, setPMax] = useState(100);
  const [bMax, setBMax] = useState("");
  const [volMin, setVolMin] = useState("");
  const [compMin, setCompMin] = useState(0);
  const [showExcluded, setShowExcluded] = useState(false);
  const [limit, setLimit] = useState(100);

  const rows = useMemo(() => {
    if (!data) return [];
    const f = from ? Date.parse(from) / 1000 : -Infinity;
    const t = to ? Date.parse(to) / 1000 + 86400 : Infinity;
    return data.markets.filter((r) => {
      if (!showExcluded && (r.excluded || r.duplicate_of || r.category === "crypto_price")) return false;
      if (cat && r.category !== cat) return false;
      if (sub && r.subcategory !== sub) return false;
      if (status === "active" && r.status !== "unresolved") return false;
      if (status === "resolved" && r.status !== "final") return false;
      if (status === "other" && ["unresolved", "final"].includes(r.status)) return false;
      const ts = r.end_ts ?? 0;
      if (ts < f || ts > t) return false;
      const p = r.status === "unresolved" ? r.current_p : r.forecasts[h]?.p;
      if ((pMin > 0 || pMax < 100) && (p === undefined || p === null || p * 100 < pMin || p * 100 > pMax)) return false;
      if (bMax && !(r.brier[h] !== undefined && r.brier[h]! <= Number(bMax))) return false;
      if (volMin && (r.volume ?? 0) < Number(volMin)) return false;
      if (r.completeness * 100 < compMin) return false;
      return matches(r, q);
    });
  }, [data, q, cat, sub, status, h, from, to, pMin, pMax, bMax, volMin, compMin, showExcluded]);

  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "no data"} />;
  const cats = [...new Set(data.markets.map((r) => r.category).filter(Boolean))] as string[];
  const subs = [...new Set(data.markets.filter((r) => !cat || r.category === cat).map((r) => r.subcategory).filter(Boolean))] as string[];

  const flat = () => rows.map((r) => ({
    market_id: r.market_id, event_id: r.event_id, question: r.question, outcome_label: r.group_item_title, category: r.category,
    subcategory: r.subcategory, status: r.status, winner: r.winner, current_p: r.current_p, end_utc: date(r.end_ts),
    reference_ts: r.reference_ts, reference_method: r.reference_method,
    ...Object.fromEntries(HORIZONS.flatMap((k) => [[`p_${k}`, r.forecasts[k]?.p ?? null], [`brier_${k}`, r.brier[k] ?? null]])),
    quality: r.quality, flags: r.flags.join(";"), volume: r.volume, url: r.url, calc_version: data.calc_version, generated_at: data.generated_at,
  }));

  return (
    <div className="space-y-4">
      <Card title={`Explorer · ${rows.length} of ${data.markets.length} markets`} right={
        <span className="flex gap-2">
          <button className="btn" onClick={() => download("markets_filtered.csv", toCsv(flat()), "text/csv")}>CSV</button>
          <button className="btn" onClick={() => download("markets_filtered.json", JSON.stringify({ generated_at: data.generated_at, calc_version: data.calc_version, markets: rows }, null, 1), "application/json")}>JSON</button>
          <a className="btn" href={dataUrl("derived/markets.json")} download>full dataset</a>
        </span>}>
        <div className="p-3 grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-2 text-xs">
          <label className="col-span-2 flex flex-col gap-1 text-mute">Keyword (Fed, FOMC, rate cuts, CLARITY Act, CPI, PCE, SEC, CFTC, stablecoins, Bitcoin ETF…)
            <input className="inp" value={q} onChange={(e) => setQ(e.target.value)} placeholder="search" /></label>
          <label className="flex flex-col gap-1 text-mute">Category
            <select className="inp" value={cat} onChange={(e) => { setCat(e.target.value); setSub(""); }}>
              <option value="">all</option>{cats.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c] ?? c}</option>)}</select></label>
          <label className="flex flex-col gap-1 text-mute">Subcategory
            <select className="inp" value={sub} onChange={(e) => setSub(e.target.value)}>
              <option value="">all</option>{subs.map((c) => <option key={c} value={c}>{label(c)}</option>)}</select></label>
          <label className="flex flex-col gap-1 text-mute">Status
            <select className="inp" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">all</option><option value="active">active</option><option value="resolved">resolved (final)</option><option value="other">proposed / disputed / invalid</option></select></label>
          <label className="flex flex-col gap-1 text-mute">Horizon
            <select className="inp" value={h} onChange={(e) => setH(e.target.value as HorizonKey)}>{HORIZONS.map((k) => <option key={k}>{k}</option>)}</select></label>
          <label className="flex flex-col gap-1 text-mute">End from<input type="date" className="inp" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label className="flex flex-col gap-1 text-mute">End to<input type="date" className="inp" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          <label className="flex flex-col gap-1 text-mute">Probability % (min–max)
            <span className="flex gap-1"><input type="number" className="inp w-full" min={0} max={100} value={pMin} onChange={(e) => setPMin(Number(e.target.value))} />
              <input type="number" className="inp w-full" min={0} max={100} value={pMax} onChange={(e) => setPMax(Number(e.target.value))} /></span></label>
          <label className="flex flex-col gap-1 text-mute">Brier ≤<input className="inp" value={bMax} onChange={(e) => setBMax(e.target.value)} placeholder="e.g. 0.1" /></label>
          <label className="flex flex-col gap-1 text-mute">Volume ≥ $<input className="inp" value={volMin} onChange={(e) => setVolMin(e.target.value)} /></label>
          <label className="flex flex-col gap-1 text-mute">Completeness ≥ {compMin}%
            <input type="range" min={0} max={100} step={10} value={compMin} onChange={(e) => setCompMin(Number(e.target.value))} /></label>
          <label className="flex items-center gap-2 text-mute col-span-2"><input type="checkbox" checked={showExcluded} onChange={(e) => setShowExcluded(e.target.checked)} />
            include duplicates, excluded & crypto-price markets</label>
        </div>
        <Scroll>
          <table className="tbl">
            <thead><tr><th>Market</th><th>Category</th><th>Status</th><th>p ({h} / now)</th><th className="text-right">Brier {h}</th><th>End</th><th className="text-right">Volume</th><th>Q</th></tr></thead>
            <tbody>
              {rows.slice(0, limit).map((r) => (
                <tr key={r.market_id}>
                  <td className="max-w-[440px]"><MarketLink id={r.market_id}>{r.group_item_title ? `${r.event_title} — ${r.group_item_title}` : r.question}</MarketLink>
                    {r.flags.length > 0 && <div className="text-[11px] text-accent mt-0.5">{r.flags.map(label).join(" · ")}</div>}</td>
                  <td className="text-xs whitespace-nowrap">{label(r.subcategory)} <RelevanceChip r={r.relevance} /></td>
                  <td><StatusChip s={r.status} /></td>
                  <td><ProbBar p={r.status === "unresolved" ? r.current_p : r.forecasts[h]?.p} /></td>
                  <td className="num">{num(r.brier[h])}</td>
                  <td className="font-mono text-xs whitespace-nowrap">{date(r.end_ts)}</td>
                  <td className="num text-xs">{money(r.volume)}</td>
                  <td><QualityChip q={r.quality} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
        {!rows.length && <Empty>No markets match these filters.</Empty>}
        {rows.length > limit && <div className="p-3 text-center"><button className="btn" onClick={() => setLimit(limit + 200)}>show more ({rows.length - limit} remaining)</button></div>}
        <div className="px-3 pb-3 text-[11px] text-dim">Probability column shows the live price for active markets and the point-in-time forecast at the selected horizon for closed ones ({pct(null)} = not available).</div>
      </Card>
    </div>
  );
}
