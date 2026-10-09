import { useState } from "react";
import { useData, download, toCsv } from "../lib/data";
import { CATEGORY_LABEL, dateTime, label, money, pct, relPct } from "../lib/format";
import type { Shifts } from "../types";
import { Card, Delta, Empty, ErrorBox, Loading, MarketLink, Note, RelevanceChip, Scroll } from "../components/ui";

export default function ShiftsPage() {
  const { data, error, loading } = useData<Shifts>("derived/shifts.json");
  const [t24, setT24] = useState<number | null>(null);
  const [t7, setT7] = useState<number | null>(null);
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [inclPrice, setInclPrice] = useState(false);
  const [sortKey, setSortKey] = useState<"d24h" | "d7d">("d24h");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "no data"} />;
  const th24 = t24 ?? data.thresholds.pp_24h;
  const th7 = t7 ?? data.thresholds.pp_7d;
  const rows = data.markets
    .filter((s) => inclPrice || s.category !== "crypto_price")
    .map((s) => ({ ...s, f24: !!s.d24h && Math.abs(s.d24h.pp_change) >= th24, f7: !!s.d7d && Math.abs(s.d7d.pp_change) >= th7 }))
    .filter((s) => !onlyFlagged || s.f24 || s.f7)
    .sort((a, b) => Math.abs(b[sortKey]?.pp_change ?? 0) - Math.abs(a[sortKey]?.pp_change ?? 0));
  const exp = () => rows.map((s) => ({
    market_id: s.market_id, question: s.question, label: s.label, category: s.category, current_p: s.current_p, current_ts: s.current_ts,
    p_24h_ago: s.d24h?.past_p, ts_24h_ago: s.d24h?.past_ts, pp_change_24h: s.d24h?.pp_change, rel_change_24h_pct: s.d24h?.relative_change_pct,
    p_7d_ago: s.d7d?.past_p, ts_7d_ago: s.d7d?.past_ts, pp_change_7d: s.d7d?.pp_change, rel_change_7d_pct: s.d7d?.relative_change_pct,
    flag_24h: s.f24, flag_7d: s.f7, volume: s.volume, liquidity: s.liquidity, volume_24h: s.volume_24h, url: s.url,
  }));
  return (
    <Card title={`Probability shift monitor · ${rows.filter((r) => r.f24 || r.f7).length} flagged`}
      right={<button className="btn" onClick={() => download("probability_shifts.csv", toCsv(exp()), "text/csv")}>CSV</button>}>
      <div className="p-3 flex flex-wrap gap-4 items-end text-xs text-mute">
        <label className="flex flex-col gap-1">Flag 24h move ≥ (pp)<input type="number" className="inp w-24" value={th24} onChange={(e) => setT24(Number(e.target.value))} /></label>
        <label className="flex flex-col gap-1">Flag 7d move ≥ (pp)<input type="number" className="inp w-24" value={th7} onChange={(e) => setT7(Number(e.target.value))} /></label>
        <label className="flex flex-col gap-1">Sort by
          <select className="inp" value={sortKey} onChange={(e) => setSortKey(e.target.value as "d24h" | "d7d")}><option value="d24h">|24h change|</option><option value="d7d">|7d change|</option></select></label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} /> flagged only</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={inclPrice} onChange={(e) => setInclPrice(e.target.checked)} /> include crypto-price markets</label>
      </div>
      <Scroll>
        <table className="tbl">
          <thead><tr><th>Market</th><th className="text-right">Now</th><th className="text-right">24h ago</th><th className="text-right">Δ 24h</th><th className="text-right">rel.</th>
            <th className="text-right">7d ago</th><th className="text-right">Δ 7d</th><th className="text-right">rel.</th><th className="text-right">Vol 24h</th><th className="text-right">Liquidity</th></tr></thead>
          <tbody>
            {rows.slice(0, 300).map((s) => (
              <tr key={s.market_id}>
                <td className="max-w-[380px]"><MarketLink id={s.market_id}>{s.label ? `${s.event_title} — ${s.label}` : s.question}</MarketLink>
                  <div className="text-[11px] text-dim mt-0.5 flex gap-1.5 items-center"><RelevanceChip r={s.relevance} />{CATEGORY_LABEL[s.category] ?? s.category} · {label(s.subcategory)} · as of {dateTime(s.current_ts)}</div></td>
                <td className="num">{pct(s.current_p)}</td>
                <td className="num text-mute" title={dateTime(s.d24h?.past_ts)}>{pct(s.d24h?.past_p)}</td>
                <td className="text-right"><Delta v={s.d24h?.pp_change} flag={s.f24} /></td>
                <td className="num text-xs text-mute">{relPct(s.d24h?.relative_change_pct)}</td>
                <td className="num text-mute" title={dateTime(s.d7d?.past_ts)}>{pct(s.d7d?.past_p)}</td>
                <td className="text-right"><Delta v={s.d7d?.pp_change} flag={s.f7} /></td>
                <td className="num text-xs text-mute">{relPct(s.d7d?.relative_change_pct)}</td>
                <td className="num text-xs">{money(s.volume_24h)}</td>
                <td className="num text-xs">{money(s.liquidity)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      {!rows.length && <Empty>No active markets with enough observations.</Empty>}
      <div className="px-3 py-2"><Note>{data.note} Example: 40% → 65% is +25 pp (absolute) and +62.5% (relative). A past value is shown only if an observation exists within 6h (24h window) / 24h (7d window) of the target time; otherwise “—”.</Note></div>
    </Card>
  );
}
