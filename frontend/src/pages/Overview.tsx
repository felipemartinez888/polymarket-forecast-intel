import { useData } from "../lib/data";
import { CATEGORY_LABEL, ago, date, num, pct, label } from "../lib/format";
import { href } from "../lib/router";
import type { Brief, Shift, Summary } from "../types";
import { Card, Delta, Empty, ErrorBox, Loading, MarketLink, ProbBar, QualityChip, RelevanceChip, Scroll, Stat, StatusChip } from "../components/ui";

function BriefTable({ rows, mode }: { rows: Brief[]; mode: "upcoming" | "awaiting" | "resolved" }) {
  if (!rows.length) return <Empty>None.</Empty>;
  return (
    <Scroll>
      <table className="tbl">
        <thead>
          <tr>
            <th>Market</th>
            <th>{mode === "resolved" ? "Outcome" : "Status"}</th>
            <th>{mode === "resolved" ? "Brier (final)" : "Implied p"}</th>
            <th>{mode === "upcoming" ? "Deadline" : "Ended"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 10).map((r) => (
            <tr key={r.market_id}>
              <td className="max-w-[420px]">
                <MarketLink id={r.market_id}>{r.group_item_title ? `${r.event_title} — ${r.group_item_title}` : r.question}</MarketLink>
                <div className="mt-0.5 flex gap-1.5 items-center text-[11px] text-dim">
                  <RelevanceChip r={r.relevance} /> {label(r.subcategory)}
                </div>
              </td>
              <td>{mode === "resolved" ? <span className="font-mono text-xs">{r.winner}</span> : <StatusChip s={r.status} />}</td>
              <td>{mode === "resolved" ? <span className="num block">{num(r.brier?.final)}</span> : <ProbBar p={r.current_p} />}</td>
              <td className="font-mono text-xs whitespace-nowrap">{date(r.end_ts)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Scroll>
  );
}

function Movers({ rows, k }: { rows: Shift[]; k: "d24h" | "d7d" }) {
  if (!rows.length) return <Empty>Not enough observations yet to compute changes.</Empty>;
  return (
    <Scroll>
      <table className="tbl">
        <thead><tr><th>Market</th><th className="text-right">Now</th><th className="text-right">Then</th><th className="text-right">Change</th></tr></thead>
        <tbody>
          {rows.slice(0, 8).map((s) => (
            <tr key={s.market_id}>
              <td className="max-w-[360px]"><MarketLink id={s.market_id}>{s.label ? `${s.event_title} — ${s.label}` : s.question}</MarketLink></td>
              <td className="num">{pct(s.current_p)}</td>
              <td className="num text-mute">{pct(s[k]?.past_p)}</td>
              <td className="text-right"><Delta v={s[k]?.pp_change} flag={k === "d24h" ? s.flag_24h : s.flag_7d} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Scroll>
  );
}

export default function Overview() {
  const { data, error, loading } = useData<Summary>("derived/summary.json");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "no data"} />;
  const fin = data.headline.final;
  const d7 = data.headline["7d"];
  const bss = fin?.pooled_bss_vs_uniform;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Markets tracked" value={data.counts.markets} sub={`${data.counts.active} active`} />
        <Stat label="Scored events" value={data.counts.scored_primary_events} sub="independent, final, verified outcomes" />
        <Stat label="Skill vs uniform · final" value={bss === null || bss === undefined ? "—" : num(bss, 2)}
          tone={bss === null || bss === undefined ? undefined : bss > 0 ? "up" : "down"}
          sub={<a className="lnk" href={href("performance")}>BSS; &gt;0 beats a no-information forecast</a>} />
        <Stat label="Skill vs uniform · 7 days out" value={d7?.pooled_bss_vs_uniform == null ? "—" : num(d7.pooled_bss_vs_uniform, 2)}
          sub={`n = ${d7?.n_events ?? 0} events`} />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title="Upcoming monitored events" right={<a className="lnk text-xs" href={href("explorer")}>all →</a>}>
          <BriefTable rows={data.upcoming} mode="upcoming" />
        </Card>
        <div className="grid gap-4">
          <Card title="Largest moves · 24h" right={<a className="lnk text-xs" href={href("shifts")}>shift monitor →</a>}>
            <Movers rows={data.movers_24h} k="d24h" />
          </Card>
          <Card title="Largest moves · 7 days"><Movers rows={data.movers_7d} k="d7d" /></Card>
        </div>
      </div>

      <Card title="Forecast quality by category · final pre-event observation" right={<a className="lnk text-xs" href={href("performance")}>details →</a>}>
        <Scroll>
          <table className="tbl">
            <thead>
              <tr><th>Category</th><th className="text-right">Events</th><th className="text-right">Mean Brier (binary, 0–1)</th>
                <th className="text-right">Mean Brier (multi, 0–2)</th><th className="text-right">Skill vs uniform</th><th className="text-right">Skill vs base rate</th></tr>
            </thead>
            <tbody>
              {Object.entries(data.by_category_final).map(([c, a]) => (
                <tr key={c}>
                  <td>{CATEGORY_LABEL[c] ?? c}</td>
                  <td className="num">{a?.n_events ?? 0}</td>
                  <td className="num">{num(a?.binary_set.mean_brier)} <span className="text-dim">({a?.binary_set.n_events ?? 0})</span></td>
                  <td className="num">{num(a?.multiclass.mean_brier)} <span className="text-dim">({a?.multiclass.n_events ?? 0})</span></td>
                  <td className="num">{num(a?.pooled_bss_vs_uniform, 2)}</td>
                  <td className="num">{num(a?.binary_set.bss_vs_base_rate ?? null, 2)}</td>
                </tr>
              ))}
              {!Object.keys(data.by_category_final).length && <tr><td colSpan={6}><Empty>No resolved, scoreable events yet.</Empty></td></tr>}
            </tbody>
          </table>
        </Scroll>
        <div className="px-3 py-2"><p className="text-xs text-dim">Lower Brier is better. Binary and multi-outcome scores use different scales and are never averaged together; the skill score is scale-free. Small samples are noisy — see confidence intervals on the accuracy page.</p></div>
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title="Awaiting resolution"><BriefTable rows={data.awaiting_resolution} mode="awaiting" /></Card>
        <Card title="Recently resolved"><BriefTable rows={data.recently_resolved} mode="resolved" /></Card>
      </div>

      <Card title="Data freshness">
        <div className="px-3 py-2.5 text-sm grid sm:grid-cols-3 gap-2">
          {["discover", "resolve", "analyze"].map((k) => (
            <div key={k}><span className="text-mute">{k}: </span><span className="font-mono">{ago(data.freshness.last_success?.[k])}</span></div>
          ))}
          <div className="sm:col-span-3 text-xs text-dim">Analytics generated {data.generated_at} · calc v{data.calc_version}. If a collection run fails, the dashboard keeps serving the last valid data. <QualityChip q="A" /> verified externally · <QualityChip q="B" /> UMA resolved · <QualityChip q="C" /> settlement prices only.</div>
        </div>
      </Card>
    </div>
  );
}
