import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useData } from "../lib/data";
import { CATEGORY_LABEL, date, dateTime, label, money, num, pct } from "../lib/format";
import { HORIZONS, type History, type MarketRow, type Meta } from "../types";
import { Card, Empty, ErrorBox, Ext, Loading, Note, QualityChip, RelevanceChip, Scroll, StatusChip } from "../components/ui";

type Markets = Meta & { markets: MarketRow[] };

const FLAG_TEXT: Record<string, string> = {
  duplicate: "Duplicate of another market (same question and end date) — excluded from aggregates.",
  disputed_during_resolution: "The UMA resolution was disputed at some point.",
  reference_time_estimated_from_price_path: "The event became known before the deadline; the reference time was estimated as the moment the price settled at its final value. Forecasts are taken before that.",
  reference_time_is_market_end_date: "Scheduled data release without a configured release timestamp: the market end date is used as the reference time.",
  external_verification_conflict: "Polymarket's resolution disagrees with the official source — excluded from scoring.",
  parse_warnings: "Some API fields were malformed; see raw values.",
  no_price_history: "No price history is available from the CLOB API for this market.",
};

function Chart({ m }: { m: MarketRow }) {
  const { data, error, loading } = useData<History>(`history/${m.market_id}.json`);
  const pts = useMemo(() => (data?.points ?? []).map(([t, p]) => ({ t, p })), [data]);
  if (loading) return <Loading />;
  if (error || !pts.length) return <Empty>No stored price history for this market{error ? ` (${error})` : ""}.</Empty>;
  const markers = HORIZONS.map((h) => m.forecasts[h]).filter((f) => f?.status === "ok" && f.obs_ts).map((f) => f!.obs_ts!);
  return (
    <div className="h-72 px-2 pt-3">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pts} margin={{ right: 12 }}>
          <CartesianGrid stroke="#232b37" vertical={false} />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time" tickFormatter={(t: number) => date(t)} stroke="#8592a3" fontSize={11} minTickGap={40} />
          <YAxis domain={[0, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} stroke="#8592a3" fontSize={11} />
          <Tooltip contentStyle={{ background: "#11161d", border: "1px solid #232b37", fontSize: 12 }} labelFormatter={(t) => dateTime(Number(t))} formatter={(v) => [pct(Number(v)), m.tracked_outcome ?? "p"]} />
          {markers.map((t) => <ReferenceLine key={t} x={t} stroke="#5b6676" strokeDasharray="2 3" />)}
          {m.reference_ts && <ReferenceLine x={m.reference_ts} stroke="#e5615b" label={{ value: "reference", fill: "#e5615b", fontSize: 10, position: "insideTopRight" }} />}
          <Line dataKey="p" stroke="#f2a93b" dot={false} strokeWidth={1.5} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function MarketDetail({ id }: { id: string }) {
  const { data, error, loading } = useData<Markets>("derived/markets.json");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "no data"} />;
  const m = data.markets.find((r) => r.market_id === id);
  if (!m) return <Card><Empty>Market {id} is not in the tracked dataset.</Empty></Card>;
  const v = m.external_verification;
  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="text-xs text-mute flex flex-wrap gap-2 items-center">
          <span>{CATEGORY_LABEL[m.category ?? ""] ?? m.category} · {label(m.subcategory)}</span><RelevanceChip r={m.relevance} />
          <StatusChip s={m.status} /><QualityChip q={m.quality} />
          <span className="text-dim">rule: {m.rule_id ?? "—"}{m.override ? " · manual override" : ""}</span>
        </div>
        <h1 className="text-lg mt-1.5 leading-snug">{m.group_item_title ? <><span className="text-mute">{m.event_title} — </span>{m.group_item_title}</> : m.question}</h1>
        {m.group_item_title && <div className="text-sm text-mute mt-0.5">{m.question}</div>}
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <div><div className="text-[11px] text-mute uppercase">{m.status === "unresolved" ? "Current p" : "Outcome"}</div>
            <div className="font-mono text-lg">{m.status === "unresolved" ? pct(m.current_p) : (m.winner ?? "—")}</div>
            <div className="text-[11px] text-dim">tracked outcome: {m.tracked_outcome}</div></div>
          <div><div className="text-[11px] text-mute uppercase">Outcomes</div><div className="font-mono text-xs">{m.outcomes.join(" / ")}</div>
            {m.final_settlement_prices && <div className="text-[11px] text-dim">settlement: {m.final_settlement_prices.join(" / ")}</div>}</div>
          <div><div className="text-[11px] text-mute uppercase">Volume / liquidity</div><div className="font-mono">{money(m.volume)} / {money(m.liquidity)}</div></div>
          <div className="flex flex-col gap-1 text-xs"><Ext url={m.url}>Polymarket</Ext>
            {m.external_source && <Ext url={m.external_source}>official source</Ext>}
            {m.resolution_source && m.resolution_source !== m.external_source && <Ext url={m.resolution_source}>market's resolution source</Ext>}</div>
        </div>
      </div>

      {m.flags.length > 0 && (
        <div className="card p-3 border-accent/40 space-y-1">
          {m.flags.map((f) => <div key={f} className="text-sm"><span className="text-accent">⚠ </span>{FLAG_TEXT[f] ?? label(f)}</div>)}
        </div>
      )}

      <Card title={`Probability history (${m.tracked_outcome ?? "Yes"}) · dashed = scored observations, red = reference time`}>
        <Chart m={m} />
        <div className="px-3 pb-2"><Note>{m.n_history_points} stored points from the CLOB prices-history endpoint, plus Gamma snapshots for live markets. First {dateTime(m.first_obs_ts)}, last {dateTime(m.last_obs_ts)}.</Note></div>
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title="Point-in-time forecasts & scores">
          <Scroll>
            <table className="tbl">
              <thead><tr><th>Horizon</th><th className="text-right">p</th><th>Observed at</th><th className="text-right">Brier</th><th>Note</th></tr></thead>
              <tbody>
                {HORIZONS.map((h) => {
                  const f = m.forecasts[h];
                  return (
                    <tr key={h}>
                      <td className="font-mono text-xs">{h}</td>
                      <td className="num">{f?.status === "ok" ? pct(f.p) : "—"}</td>
                      <td className="font-mono text-xs">{f?.status === "ok" ? dateTime(f.obs_ts) : "—"}</td>
                      <td className="num">{num(m.brier[h])}</td>
                      <td className="text-xs text-mute">{f?.status === "ok" ? "" : label(f?.reason ?? f?.status ?? "not computed")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Scroll>
          <div className="px-3 py-2"><Note>Reference time: {dateTime(m.reference_ts)} ({label(m.reference_method)}). Each forecast is the last observed price strictly before reference − horizon. 30-day volatility of daily changes: {num(m.volatility_30d)}; time-weighted mean p (30d): {pct(m.time_weighted_p_30d)}.</Note></div>
        </Card>

        <Card title="Timestamps, resolution & verification">
          <div className="p-3 text-sm space-y-1.5">
            <div><span className="text-mute">Start / end / closed: </span><span className="font-mono text-xs">{dateTime(m.start_ts)} · {dateTime(m.end_ts)} · {dateTime(m.closed_ts)}</span></div>
            <div><span className="text-mute">Resolution: </span><StatusChip s={m.status} /> <span className="text-xs text-dim">basis: {label(m.resolution_basis)}, UMA: {m.uma_status ?? "—"}</span></div>
            <div className="text-xs text-dim">Status history: {m.status_history.map((s) => `${s.status} (${date(s.observed_at)})`).join(" → ") || "—"}</div>
            {v && <div><span className="text-mute">Official check: </span><span className={v.status === "verified" ? "text-up" : v.status === "conflict" ? "text-down" : "text-mute"}>{label(v.status)}</span>
              {v.detail && <span className="text-xs text-dim"> — {v.detail}</span>}</div>}
            {m.duplicate_of && <div className="text-xs">Duplicate of <a className="lnk" href={`#/market/${m.duplicate_of}`}>{m.duplicate_of}</a></div>}
            {m.correlated_with && <div className="text-xs">Correlated with scoring unit {m.correlated_with} (not counted separately)</div>}
            <div className="text-xs text-dim">IDs: market {m.market_id} · event {m.event_id} · retrieved {dateTime(m.retrieved_at)} · calc v{data.calc_version}</div>
          </div>
        </Card>
      </div>

      <Card title="Resolution conditions (from Polymarket)">
        <div className="p-3 text-sm text-mute whitespace-pre-wrap leading-relaxed">{m.description || "Not provided by the API."}</div>
      </Card>
    </div>
  );
}
