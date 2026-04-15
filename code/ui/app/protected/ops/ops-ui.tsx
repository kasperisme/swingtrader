"use client";

import { useEffect, useState, useCallback } from "react";
import type { HealthResponse, JobHealth, WatchdogMeta } from "@/app/api/health/route";

const REFRESH_INTERVAL_MS = 60_000;

function formatAge(isoStr: string | null): string {
  if (!isoStr) return "never";
  const diffMs = Date.now() - new Date(isoStr).getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffH = diffMs / 3_600_000;
  if (diffH < 24) return `${diffH.toFixed(1)}h ago`;
  return `${(diffH / 24).toFixed(1)}d ago`;
}

function StatusBadge({ status }: { status: JobHealth["last_status"] }) {
  const map: Record<string, string> = {
    success: "bg-green-500/20 text-green-400 border border-green-500/30",
    running: "bg-blue-500/20 text-blue-400 border border-blue-500/30",
    failed:  "bg-red-500/20  text-red-400  border border-red-500/30",
  };
  const cls = map[status ?? ""] ?? "bg-zinc-500/20 text-zinc-400 border border-zinc-500/30";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status ?? "unknown"}
    </span>
  );
}

function JobCard({ job }: { job: JobHealth }) {
  const isStale =
    job.expected_interval &&
    job.last_finished_at &&
    (Date.now() - new Date(job.last_finished_at).getTime()) / 3_600_000 >
      job.expected_interval * 1.5;

  const borderColor =
    job.last_status === "failed"
      ? "border-red-500/40"
      : isStale
      ? "border-yellow-500/40"
      : "border-zinc-700/50";

  return (
    <div className={`rounded-xl border ${borderColor} bg-zinc-900/60 p-4 space-y-2`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-sm font-semibold text-zinc-100">
          {job.job_name}
        </span>
        <StatusBadge status={job.last_status} />
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-zinc-400">
        <span>Last run</span>
        <span className="text-zinc-200">{formatAge(job.last_started_at)}</span>

        <span>Last success</span>
        <span className={isStale ? "text-yellow-400" : "text-zinc-200"}>
          {job.last_status === "success"
            ? formatAge(job.last_finished_at)
            : job.last_finished_at
            ? formatAge(job.last_finished_at)
            : "—"}
        </span>

        {job.expected_interval && (
          <>
            <span>Expected every</span>
            <span className="text-zinc-200">
              {job.expected_interval < 24
                ? `${job.expected_interval}h`
                : `${job.expected_interval / 24}d`}
            </span>
          </>
        )}

        {job.consecutive_fails > 0 && (
          <>
            <span>Consecutive fails</span>
            <span className="text-red-400 font-semibold">{job.consecutive_fails}</span>
          </>
        )}
      </div>

      {/* Watchdog-specific metadata */}
      {job.job_name === "watchdog" && job.metadata && (() => {
        const m = job.metadata as WatchdogMeta;
        return (
          <div className="mt-1 pt-2 border-t border-zinc-800 space-y-1.5">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-zinc-400">
              {m.jobs_checked != null && (
                <>
                  <span>Jobs checked</span>
                  <span className="text-zinc-200">{m.jobs_checked}</span>
                </>
              )}
              {m.alerts_fired != null && (
                <>
                  <span>Alerts fired</span>
                  <span className={m.alerts_fired > 0 ? "text-yellow-400 font-semibold" : "text-zinc-200"}>
                    {m.alerts_fired}
                  </span>
                </>
              )}
            </div>
            {m.logs_with_errors && m.logs_with_errors.length > 0 && (
              <div className="text-xs text-red-400">
                Log errors: {m.logs_with_errors.join(", ")}
              </div>
            )}
            {m.logs_clean && m.logs_clean.length > 0 && (
              <div className="text-xs text-zinc-600">
                Clean: {m.logs_clean.join(", ")}
              </div>
            )}
          </div>
        );
      })()}

      {/* Generic metadata for other jobs */}
      {job.job_name !== "watchdog" && job.metadata && Object.keys(job.metadata).length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs text-zinc-500 hover:text-zinc-300">
            Metadata
          </summary>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-zinc-400">
            {Object.entries(job.metadata).map(([k, v]) => (
              <><span key={k}>{k}</span><span className="text-zinc-300">{String(v)}</span></>
            ))}
          </div>
        </details>
      )}

      {job.last_error && (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs text-red-400 hover:text-red-300">
            Show error
          </summary>
          <pre className="mt-2 overflow-x-auto rounded bg-zinc-950 p-2 text-xs text-red-300 whitespace-pre-wrap break-all">
            {job.last_error}
          </pre>
        </details>
      )}
    </div>
  );
}

function FreshnessRow({ label, isoStr, warnAfterH }: { label: string; isoStr: string | null; warnAfterH: number }) {
  const ageH = isoStr
    ? (Date.now() - new Date(isoStr).getTime()) / 3_600_000
    : Infinity;
  const isStale = ageH > warnAfterH;
  return (
    <div className="flex items-center justify-between py-2 border-b border-zinc-800 last:border-0">
      <span className="text-sm text-zinc-400">{label}</span>
      <span className={`text-sm font-medium ${isStale ? "text-yellow-400" : "text-zinc-200"}`}>
        {isoStr ? formatAge(isoStr) : "no data"}
      </span>
    </div>
  );
}

export function OpsUI() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: HealthResponse = await res.json();
      setHealth(data);
      setLastRefreshed(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-zinc-500 text-sm">
        Loading health data…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-500/40 bg-red-950/20 p-4 text-sm text-red-400">
        Failed to load health data: {error}
      </div>
    );
  }

  if (!health) return null;

  const overallColor = health.ok
    ? "text-green-400"
    : "text-red-400";

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Operations</h1>
          <p className="text-sm text-zinc-500 mt-0.5">
            Data backbone health &amp; job status
          </p>
        </div>
        <div className="text-right">
          <span className={`text-lg font-semibold ${overallColor}`}>
            {health.ok ? "All systems go" : `${health.alerts.length} alert${health.alerts.length !== 1 ? "s" : ""}`}
          </span>
          <p className="text-xs text-zinc-600 mt-0.5">
            Refreshes every 60s
            {lastRefreshed && ` · last ${formatAge(lastRefreshed.toISOString())}`}
          </p>
        </div>
      </div>

      {/* Alerts */}
      {health.alerts.length > 0 && (
        <div className="rounded-xl border border-yellow-500/30 bg-yellow-950/20 p-4 space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-yellow-500 mb-2">
            Active alerts
          </p>
          {health.alerts.map((a, i) => (
            <div key={i} className="flex items-start gap-2 text-sm text-yellow-300">
              <span className="mt-0.5 shrink-0">⚠</span>
              <span>{a}</span>
            </div>
          ))}
        </div>
      )}

      {/* Jobs */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500 mb-3">
          Background jobs
        </h2>
        {health.jobs.length === 0 ? (
          <p className="text-sm text-zinc-600">
            No jobs recorded yet. Jobs appear here after their first run.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {health.jobs.map((job) => (
              <JobCard key={job.job_name} job={job} />
            ))}
          </div>
        )}
      </section>

      {/* Data freshness */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500 mb-3">
          Data freshness
        </h2>
        <div className="rounded-xl border border-zinc-700/50 bg-zinc-900/60 px-4 divide-y divide-zinc-800">
          <FreshnessRow
            label="Latest news article"
            isoStr={health.freshness.latest_news_article_at}
            warnAfterH={3}
          />
          <FreshnessRow
            label="Latest screener run"
            isoStr={health.freshness.latest_scan_run_at}
            warnAfterH={26}
          />
        </div>
      </section>

      <p className="text-xs text-zinc-700">
        Checked at {new Date(health.checked_at).toLocaleString()}
      </p>
    </div>
  );
}
