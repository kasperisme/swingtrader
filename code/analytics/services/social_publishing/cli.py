"""Manual per-ticker publisher.

    # List your connected Zernio accounts (to fill ZERNIO_ACCOUNT_* env vars):
    python -m services.social_publishing.cli accounts

    # See exactly what would post where — no network, no creds needed:
    python -m services.social_publishing.cli publish --ticker NWPX --dry-run

    # Push the finished assets to all four networks:
    python -m services.social_publishing.cli publish --ticker NWPX

    # Just LinkedIn + Instagram, or force a different backend:
    python -m services.social_publishing.cli publish --ticker NWPX \
        --platforms linkedin,instagram --backend ayrshare

    # Schedule for an explicit time (local tz, default America/New_York):
    python -m services.social_publishing.cli publish --ticker NWPX --at "2026-06-23 19:00"

    # Schedule at each platform's best-engagement time (Zernio analytics,
    # falls back to a labelled default until you have post history):
    python -m services.social_publishing.cli publish --ticker NWPX --best-time

Run it only once the content is final — this service does no creative work, it
just distributes whatever is in output/setups/<TICKER>/.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from . import config, schedule, storage
from .assets import PostPlan, build_plans
from .backends import get_backend

log = logging.getLogger("social_publishing")


def _parse_platforms(raw: str | None) -> list[str]:
    if not raw:
        return list(config.PLATFORMS)
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _resolve_schedule(backend, platform, account_id, args, now_utc):
    """Return (schedule_at | None, label) for one platform.

    --at gives one explicit time for every platform; --best-time resolves each
    platform's own best slot (Zernio analytics, else a labelled fallback);
    neither → immediate.
    """
    if args.at:
        when = schedule.parse_explicit(args.at, args.tz)
        return when, f"at {when.isoformat()}"
    if args.best_time:
        slots = []
        if hasattr(backend, "best_time_slots") and backend.is_configured():
            try:
                slots = backend.best_time_slots(platform, account_id)
            except Exception as exc:
                log.warning("best-time lookup failed for %s: %s", platform, exc)
        when, label = schedule.resolve_best(slots, platform, now_utc)
        return when, f"{when.isoformat()} — {label}"
    return None, "immediate"


def _print_plan(plan: PostPlan, account_note: str) -> None:
    media = "\n".join(f"      - {p.name}" for p in plan.media)
    preview = plan.caption.replace("\n", " ")
    preview = preview[:140] + ("…" if len(preview) > 140 else "")
    print(
        f"  [{plan.platform}]  kind={plan.kind}  caption<-{plan.caption_source}"
        f"{account_note}\n"
        f"    media:\n{media}\n"
        f"    caption: {preview}"
    )


def cmd_publish(args: argparse.Namespace) -> int:
    if args.at and args.best_time:
        print("error: use either --at or --best-time, not both.", file=sys.stderr)
        return 1
    backend = get_backend(args.backend or config.SOCIAL_BACKEND)
    platforms = _parse_platforms(args.platforms)
    try:
        plans = build_plans(args.ticker, platforms)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Resolve account ids up front so dry-run surfaces any missing mapping.
    accounts = {
        p.platform: (backend.account_id_for(p.platform) if backend.NEEDS_ACCOUNT_ID else None)
        for p in plans
    }
    # Resolve each platform's schedule once (shown in the plan + used to publish).
    now_utc = datetime.now(timezone.utc)
    try:
        sched = {
            p.platform: _resolve_schedule(backend, p.platform, accounts[p.platform], args, now_utc)
            for p in plans
        }
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"\n{args.ticker.upper()} via {backend.NAME} — {len(plans)} platform(s):\n")
    for plan in plans:
        acct = accounts[plan.platform]
        note = ""
        if backend.NEEDS_ACCOUNT_ID:
            note = f"  account={acct}" if acct else "  account=⚠ MISSING"
        note += f"\n    when: {sched[plan.platform][1]}"
        _print_plan(plan, note)

    if args.dry_run:
        print("\n[dry-run] nothing uploaded or posted.")
        return 0

    if not backend.is_configured():
        print(
            f"error: {backend.NAME} is not configured (set its API key in .env). "
            f"Use --dry-run to preview.",
            file=sys.stderr,
        )
        return 1

    print()
    ok = True
    for plan in plans:
        try:
            media_urls = storage.stage_media(args.ticker, plan.platform, plan.media)
            result = backend.publish(
                plan.platform,
                plan.caption,
                media_urls,
                plan.kind,
                account_id=accounts[plan.platform],
                schedule_at=sched[plan.platform][0],
            )
            mark = "✓" if result.ok else "✗"
            print(f"  {mark} {plan.platform}: {result.detail}")
            ok &= result.ok
        except Exception as exc:  # one platform failing must not abort the rest
            print(f"  ✗ {plan.platform}: {exc}")
            ok = False
    return 0 if ok else 2


def cmd_accounts(args: argparse.Namespace) -> int:
    backend = get_backend(args.backend or config.SOCIAL_BACKEND)
    if not hasattr(backend, "list_accounts"):
        print(f"{backend.NAME} has no account listing (addressed by platform name).")
        return 0
    if not backend.is_configured():
        print(f"error: {backend.NAME} API key not set in .env", file=sys.stderr)
        return 1
    accounts = backend.list_accounts()
    if not accounts:
        print("No connected accounts found.")
        return 0
    print("Connected accounts — add the ones you want to .env:\n")
    for a in accounts:
        platform = (a.get("platform") or a.get("type") or "?").lower()
        acct_id = a.get("accountId") or a.get("id") or "?"
        name = a.get("username") or a.get("displayName") or a.get("name") or ""
        print(f"  {platform:<12} {acct_id}   {name}")
        if platform in config.PLATFORMS:
            print(f"      → ZERNIO_ACCOUNT_{platform.upper()}={acct_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(prog="social_publishing")
    sub = parser.add_subparsers(dest="cmd", required=True)

    backend_help = "override SOCIAL_BACKEND for this run (zernio|ayrshare)"

    p = sub.add_parser("publish", help="publish a ticker's assets to socials")
    p.add_argument("--ticker", required=True)
    p.add_argument(
        "--platforms",
        help="comma list (instagram,facebook,tiktok,linkedin); default all",
    )
    p.add_argument("--backend", help=backend_help)
    p.add_argument(
        "--at",
        help="schedule for an explicit local time, 'YYYY-MM-DD HH:MM' (see --tz)",
    )
    p.add_argument(
        "--best-time",
        action="store_true",
        help="schedule at each platform's best-engagement time (Zernio analytics, "
        "labelled fallback until you have history)",
    )
    p.add_argument(
        "--tz",
        help=f"timezone for --at (default {schedule.DEFAULT_TZ})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve and print the plan without uploading or posting",
    )
    p.set_defaults(func=cmd_publish)

    a = sub.add_parser("accounts", help="list connected accounts (Zernio)")
    a.add_argument("--backend", help=backend_help)
    a.set_defaults(func=cmd_accounts)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
