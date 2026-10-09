import { useState } from "react";
import { useRoute, href } from "./lib/router";
import { useData } from "./lib/data";
import { ago } from "./lib/format";
import type { Status } from "./types";
import Overview from "./pages/Overview";
import FedMonitor from "./pages/FedMonitor";
import Regulation from "./pages/Regulation";
import Performance from "./pages/Performance";
import Explorer from "./pages/Explorer";
import ShiftsPage from "./pages/Shifts";
import MarketDetail from "./pages/MarketDetail";
import DataStatus from "./pages/DataStatus";

const NAV: [string, string][] = [
  ["overview", "Overview"],
  ["fed", "Fed monitor"],
  ["regulation", "Crypto regulation"],
  ["performance", "Historical accuracy"],
  ["shifts", "Probability shifts"],
  ["explorer", "Explorer"],
  ["status", "Data & method"],
];

function Freshness() {
  const { data } = useData<Status>("derived/status.json");
  if (!data) return null;
  const last = data.last_success?.discover;
  const stale = !last || Date.now() - Date.parse(last) > 26 * 3600 * 1000;
  return (
    <a href={href("status")} className="flex items-center gap-1.5 text-[11px] text-mute hover:text-ink" title="Last successful collection run">
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${stale ? "bg-down" : "bg-up"}`} />
      data {ago(last)}
    </a>
  );
}

export default function App() {
  const route = useRoute();
  const [open, setOpen] = useState(false);
  const page = route[0];
  let body;
  switch (page) {
    case "fed": body = <FedMonitor />; break;
    case "regulation": body = <Regulation />; break;
    case "performance": body = <Performance />; break;
    case "shifts": body = <ShiftsPage />; break;
    case "explorer": body = <Explorer />; break;
    case "status": body = <DataStatus />; break;
    case "market": body = <MarketDetail id={route[1] ?? ""} />; break;
    default: body = <Overview />;
  }
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 bg-bg/95 backdrop-blur border-b border-line">
        <div className="max-w-[1400px] mx-auto px-3 sm:px-4 h-11 flex items-center gap-4">
          <a href={href("overview")} className="font-mono text-sm tracking-tight whitespace-nowrap">
            <span className="text-accent">▌</span>FORECAST<span className="text-mute">/INTEL</span>
          </a>
          <nav className="hidden lg:flex items-center gap-1 text-[13px]">
            {NAV.map(([k, l]) => (
              <a key={k} href={href(k)}
                className={`px-2.5 py-1 rounded ${page === k || (k === "overview" && !NAV.some(([n]) => n === page) && page !== "market") ? "text-ink bg-panel2" : "text-mute hover:text-ink"}`}>
                {l}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <Freshness />
            <button className="lg:hidden btn" onClick={() => setOpen(!open)} aria-label="Menu">☰</button>
          </div>
        </div>
        {open && (
          <nav className="lg:hidden border-t border-line px-3 py-2 grid grid-cols-2 gap-1 text-sm">
            {NAV.map(([k, l]) => (
              <a key={k} href={href(k)} onClick={() => setOpen(false)} className={`px-2 py-1.5 rounded ${page === k ? "bg-panel2 text-ink" : "text-mute"}`}>{l}</a>
            ))}
          </nav>
        )}
      </header>
      <main className="max-w-[1400px] mx-auto px-3 sm:px-4 py-4">{body}</main>
      <footer className="max-w-[1400px] mx-auto px-3 sm:px-4 pb-8 pt-2 text-[11px] text-dim leading-relaxed">
        Personal research tool. Data: Polymarket public Gamma &amp; CLOB APIs (read-only) and official sources linked per market.
        Market probabilities describe event likelihood only — they are not forecasts of crypto prices and nothing here is a trading recommendation.
      </footer>
    </div>
  );
}
