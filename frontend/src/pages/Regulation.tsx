import { useData } from "../lib/data";
import { CATEGORY_LABEL, date, label, num } from "../lib/format";
import type { Brief, Regulation as Reg } from "../types";
import { Card, Empty, ErrorBox, Ext, Loading, MarketLink, Note, ProbBar, QualityChip, Scroll, StatusChip } from "../components/ui";

function Rows({ rows }: { rows: Brief[] }) {
  return (
    <Scroll>
      <table className="tbl">
        <thead><tr><th>Market</th><th>Status</th><th>Implied p / outcome</th><th>Deadline</th><th className="text-right">Brier final</th><th>Links</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.market_id}>
              <td className="max-w-[460px]"><MarketLink id={r.market_id}>{r.group_item_title ? `${r.event_title} — ${r.group_item_title}` : r.question}</MarketLink>
                {r.flags?.length ? <div className="text-[11px] text-accent mt-0.5">{r.flags.map(label).join(" · ")}</div> : null}</td>
              <td><StatusChip s={r.status} /></td>
              <td>{r.status === "final" ? <span className="font-mono text-xs">{r.winner}</span> : <ProbBar p={r.current_p} />}</td>
              <td className="font-mono text-xs whitespace-nowrap">{date(r.end_ts)}</td>
              <td className="num">{num(r.brier?.final)} <QualityChip q={r.quality} /></td>
              <td className="text-xs whitespace-nowrap"><Ext url={r.url}>Polymarket</Ext>{r.external_source && <> · <Ext url={r.external_source}>source</Ext></>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Scroll>
  );
}

export default function Regulation() {
  const { data, error, loading } = useData<Reg>("derived/regulation.json");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "no data"} />;
  const ms = data.milestone_order.filter((k) => data.clarity_milestones[k]?.length);
  return (
    <div className="space-y-4">
      <Card title="CLARITY Act · milestones with an actual Polymarket market"
        right={<span className="flex gap-3">{(data.official_sources.clarity_act ?? []).map((s) => <Ext key={s.url} url={s.url}>{s.label}</Ext>)}</span>}>
        {!ms.length ? <Empty>No CLARITY Act markets discovered yet. Milestones without a market are intentionally not shown.</Empty> : ms.map((k) => (
          <div key={k} className="border-b border-line last:border-0">
            <div className="px-3 pt-2.5 text-[11px] uppercase tracking-wider text-accent">{label(k)}</div>
            <Rows rows={data.clarity_milestones[k]} />
          </div>
        ))}
        <div className="px-3 py-2"><Note>{data.note} Always read each market's resolution text (market detail page) — settlement conditions differ between “passes”, “signed” and “law by date”.</Note></div>
      </Card>

      {data.groups.filter((g) => g.subcategory !== "clarity_act").map((g) => (
        <Card key={`${g.category}/${g.subcategory}`} title={`${CATEGORY_LABEL[g.category] ?? g.category} · ${label(g.subcategory)}`}
          right={<span className="flex gap-3">{(data.official_sources[g.subcategory] ?? []).map((s) => <Ext key={s.url} url={s.url}>{s.label}</Ext>)}</span>}>
          <Rows rows={g.markets.slice(0, 50)} />
        </Card>
      ))}
      {!data.groups.length && <Card><Empty>No crypto regulation or crypto-event markets collected yet.</Empty></Card>}
      <Note>Event probability and crypto price impact are different questions: a high probability that a bill passes says nothing by itself about how Bitcoin will react, or whether the outcome is already priced in.</Note>
    </div>
  );
}
