import Link from "next/link";
import { ArrowRight, Bot, LayoutGrid, Wallet } from "lucide-react";

import type { AgentsSummary, WorkspaceSummary } from "./dashboard-summary";
import type { PortfolioPosition } from "@/app/protected/trades/portfolio-from-trades";

/** "market_screening:nis-momentum" → "Nis Momentum". */
function sourceLabel(source: string): string {
  const raw = source.startsWith("market_screening:")
    ? source.slice("market_screening:".length)
    : source;
  return (
    raw.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).trim() ||
    "Screening"
  );
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days}d ago`;
}

function Card({
  href,
  icon: Icon,
  title,
  headline,
  sub,
  children,
}: {
  href: string;
  icon: typeof Bot;
  title: string;
  headline: string;
  sub: string;
  children?: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="group flex flex-col rounded-xl border border-border bg-card p-4 transition-colors hover:border-amber-500/40"
    >
      <div className="flex items-center gap-2">
        <Icon
          className="h-3.5 w-3.5 text-muted-foreground/60 transition-colors group-hover:text-amber-500"
          aria-hidden
        />
        <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">
          {title}
        </span>
        <ArrowRight className="ml-auto h-3.5 w-3.5 text-muted-foreground/30 transition-colors group-hover:text-amber-500" />
      </div>

      <p className="mt-3 text-2xl font-semibold leading-none tracking-tight tabular-nums">
        {headline}
      </p>
      <p className="mt-1.5 text-xs text-muted-foreground">{sub}</p>

      {children ? (
        <div className="mt-3 border-t border-border/60 pt-2.5 text-xs text-muted-foreground">
          {children}
        </div>
      ) : null}
    </Link>
  );
}

export function DashboardSummaryCards({
  workspace,
  agents,
  positions,
}: {
  workspace: WorkspaceSummary;
  agents: AgentsSummary;
  positions: PortfolioPosition[];
}) {
  const open = positions.filter((p) => p.netQty !== 0);
  const longs = open.filter((p) => p.sideLabel === "long").length;
  const shorts = open.length - longs;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Card
        href="/protected/workspace"
        icon={LayoutGrid}
        title="Workspace"
        headline={
          workspace.latest ? `${workspace.latest.rowCount}` : "Nothing yet"
        }
        sub={
          workspace.latest
            ? `names in ${sourceLabel(workspace.latest.source)} · ${relativeTime(workspace.latest.createdAt)}`
            : "Import a screening to start a list"
        }
      >
        {workspace.latest ? (
          <span>
            {workspace.runCount} screening{workspace.runCount === 1 ? "" : "s"}
            {workspace.watchlisted + workspace.pipeline > 0 ? (
              <>
                {" · "}
                <span className="text-foreground">
                  {workspace.watchlisted}
                </span>{" "}
                watchlisted
                {workspace.pipeline > 0 ? (
                  <>
                    {" · "}
                    <span className="text-foreground">
                      {workspace.pipeline}
                    </span>{" "}
                    in pipeline
                  </>
                ) : null}
              </>
            ) : (
              " · none triaged yet"
            )}
          </span>
        ) : null}
      </Card>

      <Card
        href="/protected/agents"
        icon={Bot}
        title="Agents"
        headline={agents.total ? `${agents.active}` : "None yet"}
        sub={
          agents.total
            ? `active of ${agents.total} scheduled`
            : "Schedule a screening to run itself"
        }
      >
        {agents.lastRun ? (
          <span className="line-clamp-2">
            <span
              className={
                agents.lastRun.triggered
                  ? "text-amber-500"
                  : "text-muted-foreground"
              }
            >
              {agents.lastRun.triggered ? "Fired" : "Quiet"}
            </span>
            {" · "}
            <span className="text-foreground">{agents.lastRun.name}</span>{" "}
            {relativeTime(agents.lastRun.runAt)}
            {agents.triggeredToday > 0
              ? ` · ${agents.triggeredToday} fired today`
              : ""}
          </span>
        ) : agents.total ? (
          <span>No runs yet — waiting on the schedule.</span>
        ) : null}
      </Card>

      <Card
        href="/protected/trades"
        icon={Wallet}
        title="Portfolio"
        headline={open.length ? `${open.length}` : "No positions"}
        sub={
          open.length
            ? `open position${open.length === 1 ? "" : "s"}${
                shorts > 0 ? ` · ${longs} long, ${shorts} short` : ""
              }`
            : "Log a trade to track it here"
        }
      >
        {open.length ? (
          <span className="line-clamp-2">
            {open
              .slice(0, 6)
              .map((p) => p.ticker)
              .join(" · ")}
            {open.length > 6 ? ` +${open.length - 6}` : ""}
          </span>
        ) : null}
      </Card>
    </div>
  );
}
