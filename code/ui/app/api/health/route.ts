import { NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";

export interface WatchdogMeta {
  jobs_checked?: number;
  alerts_fired?: number;
  logs_clean?: string[];
  logs_with_errors?: string[];
  checked_at?: string;
}

export interface JobRun {
  id: number;
  started_at: string;
  finished_at: string;
  status: "success" | "failed";
  duration_s: number | null;
  error: string | null;
}

export interface JobHealth {
  job_name: string;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_status: "running" | "success" | "failed" | null;
  last_error: string | null;
  consecutive_fails: number;
  expected_interval: number | string | null;
  metadata: Record<string, unknown> | null;
  recent_runs: JobRun[];
}

export interface DataFreshness {
  latest_news_article_at: string | null;
  latest_scan_run_at: string | null;
}

export interface HealthResponse {
  ok: boolean;
  checked_at: string;
  jobs: JobHealth[];
  freshness: DataFreshness;
  alerts: string[];
}

export async function GET() {
  const supabase = createServiceClient();
  const now = new Date();
  const alerts: string[] = [];

  // ── Job health rows ────────────────────────────────────────────────────────
  const { data: jobs, error: jobsErr } = await supabase
    .schema("swingtrader")
    .from("job_health")
    .select(
      "job_name,last_started_at,last_finished_at,last_status,last_error,consecutive_fails,expected_interval,metadata",
    )
    .order("job_name");

  if (jobsErr) {
    console.error("[health] jobs query failed:", jobsErr);
  }

  // ── Recent job runs (last 10 per job, grouped in memory) ──────────────────
  const { data: runs } = await supabase
    .schema("swingtrader")
    .from("job_runs")
    .select("id,job_name,started_at,finished_at,status,duration_s,error")
    .order("started_at", { ascending: false })
    .limit(200);

  const runsByJob = new Map<string, JobRun[]>();
  for (const run of runs ?? []) {
    const list = runsByJob.get(run.job_name) ?? [];
    if (list.length < 10) list.push(run as JobRun);
    runsByJob.set(run.job_name, list);
  }

  const jobRows: JobHealth[] = (jobs ?? []).map((j) => ({
    ...(j as Omit<JobHealth, "recent_runs">),
    recent_runs: runsByJob.get(j.job_name) ?? [],
  }));

  // Parse expected_interval — may be a float (hours) or Postgres INTERVAL string "HH:MM:SS"
  function parseIntervalH(raw: number | string | null): number | null {
    if (raw == null) return null;
    if (typeof raw === "number") return raw;
    try {
      // "0:15:00" or "1 day 02:00:00"
      let days = 0;
      let s = raw;
      if (s.includes("day")) {
        const [dayPart, rest] = s.split("day");
        days = parseInt(dayPart.trim(), 10);
        s = rest.replace(/^s/, "").trim();
      }
      const [h, m, sec] = s.split(":").map(Number);
      return days * 24 + h + m / 60 + sec / 3600;
    } catch {
      return null;
    }
  }

  // Check staleness: if a job hasn't succeeded within 1.5× its expected interval
  for (const job of jobRows) {
    const intervalH = parseIntervalH(job.expected_interval);
    if (job.last_status === "failed") {
      alerts.push(`${job.job_name} last run FAILED (${job.consecutive_fails} consecutive)`);
    } else if (intervalH && job.last_finished_at) {
      const finishedAt = new Date(job.last_finished_at);
      const ageH = (now.getTime() - finishedAt.getTime()) / 3_600_000;
      const threshold = intervalH * 1.5;
      if (ageH > threshold) {
        const ageStr = ageH < 24
          ? `${ageH.toFixed(1)}h ago`
          : `${(ageH / 24).toFixed(1)}d ago`;
        alerts.push(`${job.job_name} is stale — last success ${ageStr} (expected every ${intervalH.toFixed(2)}h)`);
      }
    } else if (intervalH && !job.last_finished_at) {
      alerts.push(`${job.job_name} has never completed a run`);
    }
  }

  // ── Data freshness ─────────────────────────────────────────────────────────
  const [newsRes, scanRes] = await Promise.all([
    supabase
      .schema("swingtrader")
      .from("news_articles")
      .select("created_at")
      .order("created_at", { ascending: false })
      .limit(1),
    supabase
      .schema("swingtrader")
      .from("user_scan_runs")
      .select("created_at")
      .order("created_at", { ascending: false })
      .limit(1),
  ]);

  const freshness: DataFreshness = {
    latest_news_article_at: newsRes.data?.[0]?.created_at ?? null,
    latest_scan_run_at: scanRes.data?.[0]?.created_at ?? null,
  };

  // News freshness alert: if latest article is >3h old
  if (freshness.latest_news_article_at) {
    const ageH =
      (now.getTime() - new Date(freshness.latest_news_article_at).getTime()) /
      3_600_000;
    if (ageH > 3) {
      alerts.push(`News data stale — last article ${ageH.toFixed(1)}h ago`);
    }
  } else {
    alerts.push("No news articles found in database");
  }

  const ok = alerts.length === 0;

  return NextResponse.json<HealthResponse>({
    ok,
    checked_at: now.toISOString(),
    jobs: jobRows,
    freshness,
    alerts,
  });
}
