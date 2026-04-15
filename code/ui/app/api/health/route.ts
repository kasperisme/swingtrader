import { NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";

export const dynamic = "force-dynamic";

export interface JobHealth {
  job_name: string;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_status: "running" | "success" | "failed" | null;
  last_error: string | null;
  consecutive_fails: number;
  expected_interval_h: number | null;
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
      "job_name,last_started_at,last_finished_at,last_status,last_error,consecutive_fails,expected_interval_h",
    )
    .order("job_name");

  if (jobsErr) {
    console.error("[health] jobs query failed:", jobsErr);
  }

  const jobRows: JobHealth[] = (jobs ?? []) as JobHealth[];

  // Check staleness: if a job hasn't succeeded within 1.5× its expected interval
  for (const job of jobRows) {
    if (job.last_status === "failed") {
      alerts.push(`${job.job_name} last run FAILED (${job.consecutive_fails} consecutive)`);
    } else if (job.expected_interval_h && job.last_finished_at) {
      const finishedAt = new Date(job.last_finished_at);
      const ageH = (now.getTime() - finishedAt.getTime()) / 3_600_000;
      const threshold = job.expected_interval_h * 1.5;
      if (ageH > threshold) {
        const ageStr = ageH < 24
          ? `${ageH.toFixed(1)}h ago`
          : `${(ageH / 24).toFixed(1)}d ago`;
        alerts.push(`${job.job_name} is stale — last success ${ageStr} (expected every ${job.expected_interval_h}h)`);
      }
    } else if (job.expected_interval_h && !job.last_finished_at) {
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
