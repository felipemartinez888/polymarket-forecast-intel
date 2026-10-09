import { useData } from "../lib/data";
import { CATEGORY_LABEL, ago, dateTime } from "../lib/format";
import type { Status } from "../types";
import { Card, ErrorBox, Loading, Scroll, StatusChip, Stat } from "../components/ui";

export default function DataStatus() {
  const { data, error, loading } = useData<Status>("derived/status.json");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "no data"} />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Last collection" value={ago(data.last_success.discover)} sub={data.last_success.discover ?? "never"} />
        <Stat label="Last resolution check" value={ago(data.last_success.resolve)} sub={data.last_success.resolve ?? "never"} />
        <Stat label="Latest price observation" value={ago(data.latest_observation_ts)} sub={dateTime(data.latest_observation_ts)} />
        <Stat label="Stored data" value={`${(data.storage.bytes / 1e6).toFixed(1)} MB`} sub={`${data.storage.files} files · ${data.markets_without_history} markets without history`} />
      </div>
      <Card title="Markets by category">
        <div className="p-3 flex flex-wrap gap-4 text-sm">
          {Object.entries(data.categories).map(([c, n]) => <span key={c}><span className="text-mute">{CATEGORY_LABEL[c] ?? c}: </span><span className="font-mono">{n}</span></span>)}
        </div>
      </Card>
      <Card title="Recent pipeline runs">
        <Scroll>
          <table className="tbl">
            <thead><tr><th>Command</th><th>Started</th><th>Status</th><th className="text-right">Duration</th><th>Result</th><th>Problems</th></tr></thead>
            <tbody>
              {[...data.recent_runs].reverse().map((r, i) => (
                <tr key={i}>
                  <td className="font-mono text-xs">{r.command}</td>
                  <td className="font-mono text-xs whitespace-nowrap">{r.started_at}</td>
                  <td><StatusChip s={r.status === "ok" ? "final" : r.status === "partial" ? "proposed" : "disputed"} /> <span className="text-xs">{r.status}</span></td>
                  <td className="num text-xs">{r.duration_s}s</td>
                  <td className="text-xs text-mute font-mono">{r.result ? Object.entries(r.result).map(([k, v]) => `${k}=${String(v)}`).join(" ") : r.error}</td>
                  <td className="text-xs text-mute">{r.n_errors ? `${r.n_errors} API errors` : ""}{r.incomplete?.length ? ` · ${r.incomplete.length} incomplete windows` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      </Card>
      <Card title="Methodology in brief">
        <div className="p-3 text-sm text-mute space-y-2 leading-relaxed">
          <p><b className="text-ink">What is scored.</b> Only markets that closed with a one-hot settlement (UMA “resolved”, or settlement prices when no UMA status is reported) in Fed, crypto-regulation, macro and crypto-event categories. Proposed, disputed, invalid (50/50) and unverified markets are never scored. Crypto price-direction markets are collected but excluded.</p>
          <p><b className="text-ink">No look-ahead.</b> Each forecast is the last observed price strictly before (reference time − horizon). Reference time = official announcement (FOMC 14:00 ET), the moment an early-resolving event settled in price, or the deadline. Stale observations are treated as missing, never filled.</p>
          <p><b className="text-ink">No double counting.</b> One score per event: multi-outcome Brier (0–2) for complete mutually exclusive sets, otherwise the mean binary Brier (0–1) across the event's markets. All markets for the same FOMC meeting collapse to one unit; duplicate markets are dropped.</p>
          <p><b className="text-ink">Baselines.</b> Skill scores against an uninformed forecast (50% / 1/K) and, for binary markets, an expanding-window base rate that only uses outcomes known at forecast time.</p>
          <p>Full details: <code className="text-ink">docs/METHODOLOGY.md</code> in the repository. Calculation version {data.calc_version}; classification rules v{data.rules_version}; FOMC decisions transcribed {data.fomc_transcribed_at}.</p>
        </div>
      </Card>
    </div>
  );
}
