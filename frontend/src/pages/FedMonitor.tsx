import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useData } from "../lib/data";
import { dateTime, num, pct } from "../lib/format";
import { HORIZONS, type Fed, type FedMeeting } from "../types";
import { Card, Delta, Empty, ErrorBox, Ext, Loading, MarketLink, Note, ProbBar, Scroll, StatusChip } from "../components/ui";

const bps = (b: number | null) => (b === null ? "pending" : b === 0 ? "No change" : `${b > 0 ? "+" : ""}${b} bps`);

function Upcoming({ m }: { m: FedMeeting }) {
  const ev = m.events.find((e) => e.unit?.primary !== false) ?? m.events[0];
  return (
    <Card title={`Next FOMC decision · ${m.announcement_date} (14:00 ET)`} right={ev?.url ? <Ext url={ev.url}>Polymarket</Ext> : null}>
      {!ev ? (
        <Empty>No Polymarket market for this meeting has been discovered yet.</Empty>
      ) : (
        <Scroll>
          <table className="tbl">
            <thead><tr><th>Outcome</th><th>Implied probability</th><th className="text-right">24h</th><th className="text-right">7d</th></tr></thead>
            <tbody>
              {[...ev.outcomes].sort((a, b) => (b.current_p ?? 0) - (a.current_p ?? 0)).map((o) => (
                <tr key={o.market_id}>
                  <td><MarketLink id={o.market_id}>{o.label}</MarketLink></td>
                  <td className="w-1/2"><ProbBar p={o.current_p} /></td>
                  <td className="text-right"><Delta v={o.shift?.d24h?.pp_change} flag={o.shift?.flag_24h} /></td>
                  <td className="text-right"><Delta v={o.shift?.d7d?.pp_change} flag={o.shift?.flag_7d} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-3 py-2"><Note>Probabilities are each outcome market's own Yes price; across a mutually-exclusive set they may not sum exactly to 100%. Event title: {ev.title}</Note></div>
        </Scroll>
      )}
    </Card>
  );
}

export default function FedMonitor() {
  const { data, error, loading } = useData<Fed>("derived/fed.json");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "no data"} />;
  const upcoming = data.meetings.find((m) => m.id === data.upcoming_meeting_id);
  const past = data.meetings.filter((m) => m.is_past && m.events.length).reverse();
  const lead = HORIZONS.map((h) => ({ h, brier: data.brier_by_lead_time[h]?.mean_brier ?? null, n: data.brier_by_lead_time[h]?.n_events ?? 0,
    bss: data.brier_by_lead_time[h]?.bss_vs_uniform ?? null }));
  return (
    <div className="space-y-4">
      <div className="grid lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3">{upcoming ? <Upcoming m={upcoming} /> : <Card title="Next FOMC decision"><Empty>No scheduled meeting in the configured calendar.</Empty></Card>}</div>
        <Card title="Brier score by lead time · FOMC decisions" className="lg:col-span-2">
          <div className="h-56 px-2 pt-3">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={lead}>
                <CartesianGrid stroke="#232b37" vertical={false} />
                <XAxis dataKey="h" stroke="#8592a3" fontSize={11} />
                <YAxis stroke="#8592a3" fontSize={11} />
                <Tooltip contentStyle={{ background: "#11161d", border: "1px solid #232b37", fontSize: 12 }}
                  formatter={(v, _n, p) => [`${num(Number(v))} (n=${(p.payload as { n: number }).n}, BSS ${num((p.payload as { bss: number | null }).bss, 2)})`, "mean Brier"]} />
                <Bar dataKey="brier" fill="#f2a93b" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="px-3 pb-2"><Note>One score per meeting (multi-outcome Brier, 0–2, when the full outcome set is tracked). Lower is better. Duplicate/correlated markets on the same meeting are excluded.</Note></div>
        </Card>
      </div>

      <Card title="Prior meetings · implied probability by lead time vs official decision"
        right={<span className="flex gap-3">{data.official_sources.map((s) => <Ext key={s.url} url={s.url}>{s.label}</Ext>)}</span>}>
        {!past.length ? <Empty>No historical Fed-decision markets collected yet.</Empty> : past.map((m) => (
          <div key={m.id} className="border-b border-line last:border-0">
            <div className="px-3 pt-3 pb-1 flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <span className="font-mono text-sm">{m.announcement_date}</span>
              <span className="text-sm">Official: <b className="font-mono">{bps(m.decision_bps)}</b> → {m.target_range_after ?? "—"}%</span>
              <Ext url={m.statement_url}>statement</Ext>
              <span className="text-xs text-dim">announced {dateTime(m.announcement_ts)}</span>
            </div>
            {m.events.map((ev) => (
              <div key={ev.event_id} className="pb-2">
                <div className="px-3 text-xs text-mute flex flex-wrap gap-3">
                  <Ext url={ev.url}>{ev.title}</Ext>
                  {ev.unit && <span>unit {ev.unit.type} · <StatusChip s={ev.unit.status} />{ev.unit.primary ? "" : ` · correlated with ${ev.unit.correlated_with} (not counted)`}</span>}
                  {ev.unit?.scores?.final !== undefined && <span>Brier final {num(ev.unit.scores.final)} vs uniform {num(ev.unit.baseline_uniform.final)}</span>}
                  {ev.unit?.exclusion_reason && <span className="text-down">excluded: {ev.unit.exclusion_reason}</span>}
                </div>
                <Scroll>
                  <table className="tbl">
                    <thead><tr><th>Outcome</th>{HORIZONS.map((h) => <th key={h} className="text-right">{h}</th>)}<th>Result</th><th>Verification</th></tr></thead>
                    <tbody>
                      {ev.outcomes.map((o) => (
                        <tr key={o.market_id}>
                          <td><MarketLink id={o.market_id}>{o.label}</MarketLink></td>
                          {HORIZONS.map((h) => (
                            <td key={h} className="num" title={o.missing[h] ?? ""}>
                              {o.probabilities[h] == null ? <span className="text-dim">·</span> : pct(o.probabilities[h])}
                            </td>
                          ))}
                          <td>{o.outcome_value === 1 ? <span className="text-up font-mono text-xs">YES</span> : o.outcome_value === 0 ? <span className="text-mute font-mono text-xs">no</span> : <StatusChip s={o.status} />}</td>
                          <td className="text-xs">{o.verification?.status === "verified" ? <span className="text-up">✓ matches Fed</span> :
                            o.verification?.status === "conflict" ? <span className="text-down">✗ conflict</span> : <span className="text-dim">{o.verification?.status?.replace(/_/g, " ") ?? "—"}</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Scroll>
              </div>
            ))}
          </div>
        ))}
        <div className="px-3 py-2"><Note>“·” = no valid observation at that lead time (hover for the reason: not yet trading, stale, no history). Values are the last observed price strictly before the announcement minus the lead time — post-announcement prices are never used.</Note></div>
      </Card>

      {data.other_fed_markets.length > 0 && (
        <Card title="Other Fed markets (rate path, leadership)">
          <Scroll>
            <table className="tbl">
              <thead><tr><th>Market</th><th>Status</th><th>p / outcome</th><th className="text-right">Brier final</th></tr></thead>
              <tbody>
                {data.other_fed_markets.slice(0, 40).map((r) => (
                  <tr key={r.market_id}>
                    <td className="max-w-[520px]"><MarketLink id={r.market_id}>{r.group_item_title ? `${r.event_title} — ${r.group_item_title}` : r.question}</MarketLink></td>
                    <td><StatusChip s={r.status} /></td>
                    <td>{r.status === "final" ? <span className="font-mono text-xs">{r.winner}</span> : <ProbBar p={r.current_p} />}</td>
                    <td className="num">{num(r.brier?.final)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        </Card>
      )}
    </div>
  );
}
