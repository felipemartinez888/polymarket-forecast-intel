import { useState } from "react";
import { Bar, CartesianGrid, ComposedChart, ErrorBar, Legend, Line, LineChart, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { useData, dataUrl } from "../lib/data";
import { CATEGORY_LABEL, ci, label, num, pct } from "../lib/format";
import { HORIZONS, type HorizonKey, type Performance as Perf } from "../types";
import { Card, Empty, ErrorBox, Loading, Note, Scroll } from "../components/ui";

const tip = { background: "#11161d", border: "1px solid #232b37", fontSize: 12 };

function Calibration({ data, h }: { data: Perf; h: HorizonKey }) {
  const cal = data.calibration[h];
  const pts = cal.bins.filter((b) => b.n > 0).map((b) => ({
    x: b.mean_forecast, y: b.observed_freq, n: b.n, bin: b.bin,
    err: b.ci_low !== null && b.ci_high !== null && b.observed_freq !== null ? [b.observed_freq - b.ci_low, b.ci_high - b.observed_freq] : [0, 0],
  }));
  const diag = [{ x: 0, d: 0 }, { x: 1, d: 1 }];
  return (
    <div className="grid lg:grid-cols-5 gap-4">
      <div className="lg:col-span-3 h-80 px-2 pt-3">
        {!pts.length ? <Empty>No resolved forecasts at this horizon yet.</Empty> : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart margin={{ left: 0, right: 12, bottom: 8 }}>
              <CartesianGrid stroke="#232b37" />
              <XAxis type="number" dataKey="x" domain={[0, 1]} ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]} tickFormatter={(v: number) => `${v * 100}%`} stroke="#8592a3" fontSize={11}
                label={{ value: "mean forecast", position: "insideBottom", offset: -4, fill: "#5b6676", fontSize: 11 }} />
              <YAxis type="number" domain={[0, 1]} ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]} tickFormatter={(v: number) => `${v * 100}%`} stroke="#8592a3" fontSize={11} />
              <Tooltip contentStyle={tip} formatter={(v) => pct(Number(v))} labelFormatter={() => ""} />
              <Line data={diag} dataKey="d" stroke="#5b6676" strokeDasharray="4 4" dot={false} isAnimationActive={false} name="perfect calibration" />
              <Scatter data={pts} dataKey="y" fill="#f2a93b" name="observed frequency">
                <ErrorBar dataKey="err" width={4} stroke="#f2a93b" direction="y" />
              </Scatter>
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
      <div className="lg:col-span-2">
        <Scroll>
          <table className="tbl">
            <thead><tr><th>Bin</th><th className="text-right">n</th><th className="text-right">Mean p</th><th className="text-right">Observed</th><th className="text-right">95% CI</th></tr></thead>
            <tbody>
              {cal.bins.map((b) => (
                <tr key={b.bin} className={b.n === 0 ? "opacity-40" : ""}>
                  <td className="font-mono text-xs">{b.bin}</td>
                  <td className={`num ${b.low_sample ? "text-accent" : ""}`}>{b.n}</td>
                  <td className="num">{pct(b.mean_forecast)}</td>
                  <td className="num">{pct(b.observed_freq)}</td>
                  <td className="num text-xs text-mute">{b.ci_low === null ? "—" : `${pct(b.ci_low, 0)}–${pct(b.ci_high, 0)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
        <div className="px-3 py-2"><Note>n = {cal.n} market-level forecasts; ECE = {num(cal.ece)}. Orange counts are below the minimum sample for inference. Wilson 95% intervals. Outcomes inside one event are correlated, so intervals are optimistic.</Note></div>
      </div>
    </div>
  );
}

export default function Performance() {
  const { data, error, loading } = useData<Perf>("derived/performance.json");
  const [h, setH] = useState<HorizonKey>("final");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "no data"} />;

  const byH = HORIZONS.map((k) => ({
    h: k, binary: data.by_horizon[k]?.binary_set.mean_brier ?? null, multi: data.by_horizon[k]?.multiclass.mean_brier ?? null,
    bss: data.by_horizon[k]?.pooled_bss_vs_uniform ?? null, n: data.by_horizon[k]?.n_events ?? 0,
  }));
  const trend = data.trend.filter((t) => t.horizon === "final");
  const ml = data.market_level;

  return (
    <div className="space-y-4">
      <Card title="Calibration" right={
        <span className="flex gap-1">{HORIZONS.map((k) => (
          <button key={k} onClick={() => setH(k)} className={`btn ${h === k ? "border-accent text-accent" : ""}`}>{k}</button>))}</span>}>
        <Calibration data={data} h={h} />
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title="Brier score & skill by forecast horizon">
          <div className="h-64 px-2 pt-3">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={byH}>
                <CartesianGrid stroke="#232b37" vertical={false} />
                <XAxis dataKey="h" stroke="#8592a3" fontSize={11} />
                <YAxis yAxisId="b" stroke="#8592a3" fontSize={11} />
                <YAxis yAxisId="s" orientation="right" stroke="#5aa9e6" fontSize={11} domain={[-1, 1]} />
                <Tooltip contentStyle={tip} formatter={(v) => num(Number(v))} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar yAxisId="b" dataKey="binary" name="Brier binary (0–1)" fill="#f2a93b" />
                <Bar yAxisId="b" dataKey="multi" name="Brier multi (0–2)" fill="#8b6a3e" />
                <Line yAxisId="s" dataKey="bss" name="skill vs uniform" stroke="#5aa9e6" dot />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="px-3 pb-2"><Note>One score per independent event. Skill = 1 − Brier / Brier(uninformed), &gt; 0 means better than a uniform forecast.</Note></div>
        </Card>

        <Card title="Trend over time · final pre-event observation">
          <div className="h-64 px-2 pt-3">
            {!trend.length ? <Empty>Not enough resolved events to show a trend.</Empty> : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trend}>
                  <CartesianGrid stroke="#232b37" vertical={false} />
                  <XAxis dataKey="quarter" stroke="#8592a3" fontSize={11} />
                  <YAxis stroke="#8592a3" fontSize={11} domain={[-1, 1]} />
                  <Tooltip contentStyle={tip} formatter={(v, n, p) => [`${num(Number(v), 2)} (n=${(p.payload as { n_events: number }).n_events})`, String(n)]} />
                  <Line dataKey="pooled_bss_vs_uniform" name="skill vs uniform" stroke="#5aa9e6" dot />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="px-3 pb-2"><Note>Quarters with fewer than the configured minimum events are flagged low-sample in the export; treat trends from a handful of events as anecdotal.</Note></div>
        </Card>
      </div>

      <Card title="By category and horizon">
        <Scroll>
          <table className="tbl">
            <thead><tr><th>Category</th><th>Horizon</th><th className="text-right">Events</th><th className="text-right">Brier binary</th><th className="text-right">95% CI</th>
              <th className="text-right">Brier multi</th><th className="text-right">Skill vs uniform</th><th className="text-right">Skill vs base rate</th><th className="text-right">95% CI</th></tr></thead>
            <tbody>
              {Object.entries(data.by_category).flatMap(([c, hs]) => HORIZONS.filter((k) => hs[k]?.n_events).map((k) => (
                <tr key={`${c}-${k}`}>
                  <td>{CATEGORY_LABEL[c] ?? c}</td><td className="font-mono text-xs">{k}</td>
                  <td className="num">{hs[k].n_events}</td>
                  <td className="num">{num(hs[k].binary_set.mean_brier)}</td>
                  <td className="num text-xs text-mute">{ci(hs[k].binary_set.ci95)}</td>
                  <td className="num">{num(hs[k].multiclass.mean_brier)}</td>
                  <td className="num">{num(hs[k].pooled_bss_vs_uniform, 2)}</td>
                  <td className="num">{num(hs[k].binary_set.bss_vs_base_rate ?? null, 2)}</td>
                  <td className="num text-xs text-mute">{ci(hs[k].binary_set.bss_vs_base_rate_ci95 ?? null, 2)}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </Scroll>
        {!data.n_primary_scored_events && <Empty>No scored events yet.</Empty>}
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title="Market-level metrics (binary, one forecast per market per horizon)">
          <Scroll>
            <table className="tbl">
              <thead><tr><th>Horizon</th><th className="text-right">n</th><th className="text-right">Brier</th><th className="text-right">Log loss</th><th className="text-right">MAE</th>
                <th className="text-right">Directional</th><th className="text-right">Coverage</th></tr></thead>
              <tbody>
                {HORIZONS.map((k) => (
                  <tr key={k}>
                    <td className="font-mono text-xs">{k}</td><td className="num">{ml[k]?.n ?? 0}</td><td className="num">{num(ml[k]?.mean_brier)}</td>
                    <td className="num">{num(ml[k]?.log_loss)}</td><td className="num">{num(ml[k]?.mae)}</td>
                    <td className="num">{pct(ml[k]?.directional_accuracy ?? null)}</td><td className="num">{pct(ml[k]?.directional_coverage ?? null, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <div className="px-3 py-2"><Note>Directional = share of correct calls when p is more than 5 pp away from 50% (coverage = share of forecasts that made a call). It is a classification metric, not a measure of probabilistic accuracy. Log loss clips p to [1%, 99%].</Note></div>
        </Card>

        <Card title="Coverage & missing-data diagnostics">
          <Scroll>
            <table className="tbl">
              <thead><tr><th>Horizon</th><th className="text-right">Final events</th><th className="text-right">With forecast</th><th>Missing because</th></tr></thead>
              <tbody>
                {HORIZONS.map((k) => (
                  <tr key={k}>
                    <td className="font-mono text-xs">{k}</td><td className="num">{data.coverage[k]?.units_final}</td><td className="num">{data.coverage[k]?.units_with_forecast}</td>
                    <td className="text-xs text-mute">{Object.entries(data.coverage[k]?.missing_reasons ?? {}).map(([r, n]) => `${label(r)}: ${n}`).join(" · ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <div className="px-3 py-2 space-y-1 text-xs text-mute">
            <div>Unit status: {Object.entries(data.unit_status_counts).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"}</div>
            <div>Exclusions: {Object.entries(data.exclusions).map(([k, v]) => `${label(k)}: ${v}`).join(" · ") || "none"}</div>
            <div>Outcome quality: {Object.entries(data.quality_counts).map(([k, v]) => `Q-${k}: ${v}`).join(" · ") || "—"}</div>
          </div>
        </Card>
      </div>

      <Card title="Caveats & exports">
        <div className="px-3 py-3 space-y-2">
          <Note>{data.independence_caveat}</Note>
          <Note>Polymarket's track record here is measured only on the markets this tool tracks; it does not establish that prices beat other forecasters (e.g. CME FedWatch) — that comparison is not included because no free, reproducible archive of those forecasts is used.</Note>
          <div className="flex flex-wrap gap-2 pt-1">
            <a className="btn" href={dataUrl("derived/exports/event_scores.csv")} download>event_scores.csv</a>
            <a className="btn" href={dataUrl("derived/exports/market_forecasts.csv")} download>market_forecasts.csv</a>
            <a className="btn" href={dataUrl("derived/exports/accuracy_metrics.json")} download>accuracy_metrics.json</a>
          </div>
        </div>
      </Card>
    </div>
  );
}
