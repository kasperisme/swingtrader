"""Create the feature A/B as PAUSED drafts in Ads Manager (nothing spends until
you flip them to Active). One campaign → one ad set per feature → one single-image
ad per feature, built from each slug's ad.json + its 1x1/ad.png (nis-ad-image).

    python -m services.meta_ads.cli draft            # dry-run: validate + print the plan
    python -m services.meta_ads.cli draft --go       # actually create the PAUSED drafts

Needs (in .env): META_ADS_TOKEN with **ads_management**, META_AD_ACCOUNT_ID,
META_PAGE_ID (+ optional META_IG_ACCOUNT_ID, META_SPECIAL_AD_CATEGORY).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from . import client
from .client import MetaError

FEATURES = ["feat-screening-v1", "feat-news-v1"]
CTA_MAP = {
    "sign up": "SIGN_UP", "subscribe": "SUBSCRIBE", "learn more": "LEARN_MORE",
    "get offer": "GET_OFFER", "download": "DOWNLOAD",
}


def _post(path: str, data: dict) -> dict:
    if not client.TOKEN:
        raise MetaError("META_ADS_TOKEN not set in .env")
    return client._check(requests.post(
        f"{client.BASE}/{path.lstrip('/')}",
        data={"access_token": client.TOKEN, **data}, timeout=90))


def upload_image(path: Path) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            f"{client.BASE}/{client.account()}/adimages",
            data={"access_token": client.TOKEN},
            files={"filename": (path.name, f, "image/png")}, timeout=120)
    imgs = client._check(r).get("images", {})
    if not imgs:
        raise MetaError(f"image upload returned no hash for {path.name}")
    return next(iter(imgs.values()))["hash"]


def _delete(node_id: str) -> None:
    requests.delete(f"{client.BASE}/{node_id}",
                    params={"access_token": client.TOKEN}, timeout=30)


def create_creative(name, page_id, ig_id, dest, message, cta_type, image_hashes,
                    headline=None, description=None) -> str:
    single = len(image_hashes) == 1

    def spec(with_ig: bool) -> dict:
        link_data = {
            "link": dest,
            "message": message,
            "call_to_action": {"type": cta_type, "value": {"link": dest}},
        }
        if single:                                   # single-image link ad
            link_data["image_hash"] = image_hashes[0]
            if headline:
                link_data["name"] = headline
            if description:
                link_data["description"] = description
        else:                                        # carousel
            link_data["child_attachments"] = [{"link": dest, "image_hash": h} for h in image_hashes]
            link_data["multi_share_optimized"] = False   # keep our slide order
            link_data["multi_share_end_card"] = True
        s = {"page_id": page_id, "link_data": link_data}
        if with_ig and ig_id:
            # v21+ renamed instagram_actor_id → instagram_user_id (takes the
            # IG-business-account id from act_.../instagram_accounts).
            s["instagram_user_id"] = ig_id
        return s

    try:
        return _post(f"{client.account()}/adcreatives",
                     {"name": name, "object_story_spec": json.dumps(spec(True))})["id"]
    except MetaError as e:
        if ig_id and "instagram" in str(e).lower():
            print("    (IG id rejected — creating without an explicit IG identity; "
                  "set it on the ad in Ads Manager if you want a specific IG account)")
            return _post(f"{client.account()}/adcreatives",
                         {"name": name, "object_story_spec": json.dumps(spec(False))})["id"]
        raise


def create_campaign(name: str, special: list[str]) -> str:
    try:
        return _post(f"{client.account()}/campaigns", {
            "name": name, "objective": "OUTCOME_TRAFFIC", "status": "PAUSED",
            "special_ad_categories": json.dumps(special),
            # false = each ad set keeps its own fixed budget (no cross-sharing),
            # so the feature A/B stays isolated and unbiased.
            "is_adset_budget_sharing_enabled": "false",
        })["id"]
    except MetaError as e:
        if "special ad" in str(e).lower() and not special:
            raise MetaError(
                f"{e}\n  → Meta requires a special ad category for this audience. "
                "Set META_SPECIAL_AD_CATEGORY=FINANCIAL_PRODUCTS_SERVICES in .env and re-run.")
        raise


def create_adset(name, campaign_id, budget_minor, targeting, dsa) -> str:
    body = {
        "name": name, "campaign_id": campaign_id, "status": "PAUSED",
        "daily_budget": str(budget_minor),
        "billing_event": "IMPRESSIONS", "optimization_goal": "LINK_CLICKS",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "targeting": json.dumps(targeting),
    }
    # EU (DSA) transparency: who benefits from / who pays for the ad. Required
    # whenever the audience includes the EU (we target DK).
    if dsa:
        body["dsa_beneficiary"] = dsa
        body["dsa_payor"] = dsa
    return _post(f"{client.account()}/adsets", body)["id"]


def create_ad(name, adset_id, creative_id) -> str:
    return _post(f"{client.account()}/ads", {
        "name": name, "adset_id": adset_id, "status": "PAUSED",
        "creative": json.dumps({"creative_id": creative_id}),
    })["id"]


def preflight() -> int:
    """Check every gate that blocks `draft --go`, in one pass. Each of these was a
    real error we hit; this turns them into an up-front green/red checklist so you
    fix them all before creating anything. Returns count of hard failures."""
    page = os.environ.get("META_PAGE_ID", "").strip()
    ig = os.environ.get("META_IG_ACCOUNT_ID", "").strip()
    need_scopes = {"ads_management", "pages_read_engagement", "pages_manage_ads"}
    fails = 0

    def ok(label, detail=""):
        print(f"  ✓ {label}" + (f"  — {detail}" if detail else ""))

    def bad(label, fix):
        nonlocal fails
        fails += 1
        print(f"  ✗ {label}\n      → {fix}")

    print("\nmeta_ads preflight — gates for `draft --go`:\n")

    # 1) Token + scopes
    try:
        d = client.get("debug_token", {"input_token": client.TOKEN}).get("data", {})
        scopes = set(d.get("scopes", []))
        missing = need_scopes - scopes
        if d.get("type") != "SYSTEM_USER":
            print(f"  · token type is {d.get('type')} (a System User token is recommended)")
        if missing:
            bad(f"token scopes missing: {', '.join(sorted(missing))}",
                "regenerate the System User token with ads_management + pages_read_engagement "
                "+ pages_manage_ads, then update META_ADS_TOKEN in .env")
        else:
            ok("token scopes", "ads_management · pages_read_engagement · pages_manage_ads")
    except Exception as e:
        bad(f"token invalid / unreadable ({e})", "check META_ADS_TOKEN in .env")
        return fails  # nothing else will work without a token

    # 2) Ad account reachable + active
    try:
        acc = client.get(client.account(), {"fields": "name,account_status,currency,disable_reason"})
        status = acc.get("account_status")
        if status == 1:
            ok("ad account", f"{acc.get('name')} · {client.account()} · {acc.get('currency')}")
        else:
            bad(f"ad account status={status} (1=ACTIVE expected; disable_reason={acc.get('disable_reason')})",
                "resolve the account status in Ads Manager / Billing")
    except Exception as e:
        bad(f"ad account unreachable ({e})", "check META_AD_ACCOUNT_ID in .env")

    # 3) Page assigned to the acting user (create-content on behalf of the Page)
    if not page:
        bad("META_PAGE_ID not set", "set the Facebook Page id in .env (ads run from a Page)")
    else:
        try:
            pages = client.get("me/accounts", {"fields": "id,name,tasks", "limit": 100}).get("data", [])
            hit = next((p for p in pages if p.get("id") == page), None)
            if not hit:
                bad("Page not assigned to this token",
                    f"Business Settings → System Users → assign Page {page} with ADVERTISE + CREATE_CONTENT")
            elif "CREATE_CONTENT" not in (hit.get("tasks") or []):
                bad(f"Page assigned but missing CREATE_CONTENT (tasks={hit.get('tasks')})",
                    "grant the System User CREATE_CONTENT/MANAGE on the Page")
            else:
                ok("Page access", f"{hit.get('name')} · {page}")
        except Exception as e:
            bad(f"cannot list Pages ({e})", "token likely missing pages_show_list / pages_read_engagement")

    # 4) IG advertisable via the ad account (optional identity)
    if not ig:
        print("  · no META_IG_ACCOUNT_ID — ads run Page-only (still eligible for IG placements)")
    else:
        try:
            igs = client.get(f"{client.account()}/instagram_accounts",
                             {"fields": "id,username", "limit": 25}).get("data", [])
            hit = next((a for a in igs if a.get("id") == ig), None)
            if hit:
                ok("Instagram identity", f"@{hit.get('username')} · {ig}")
                print("      (if 'less personalized ads' is on for this IG account, Meta blocks it as an "
                      "advertiser identity — turn it off in IG → Accounts Center → Ad preferences, "
                      "else the run falls back to Page-only)")
            else:
                bad("IG account not advertisable by this ad account",
                    f"Business Settings → assign Instagram {ig} to ad account {client.account()}")
        except Exception as e:
            bad(f"cannot list IG accounts ({e})", "check IG assignment in Business Settings")

    # 5) Informational — not API-checkable, but the two we hit
    print("\n  not auto-checkable (verify manually if the run still fails):")
    print("    · the Meta App must be in LIVE mode (developers.facebook.com → App Mode)")
    print("    · EU targeting (DK) needs a DSA beneficiary/payor — handled in code "
          "(META_DSA_BENEFICIARY, default 'News Impact Screener')")

    print(f"\n{'✓ all gates clear — safe to run `draft --go`' if not fails else f'✗ {fails} gate(s) to fix before `draft --go`'}\n")
    return fails


def _load(slug: str):
    d = client._ANALYTICS / "output" / "ads" / slug
    spec = json.loads((d / "ad.json").read_text())
    single = d / "1x1" / "ad.png"
    if single.exists():                              # single-image ad (default)
        return spec, [single]
    cards = sorted((d / "1x1").glob("slide-*.png"))  # carousel (legacy)
    if len(cards) < 2:
        raise MetaError(f"{slug}: need a 1x1/ad.png (single image) or ≥2 1x1/slide-*.png "
                        "(carousel) — render with nis-ad-image first")
    return spec, cards


def build_drafts(slugs: list[str], budget_dkk: float, dry_run: bool) -> int:
    page = os.environ.get("META_PAGE_ID", "").strip()
    ig = os.environ.get("META_IG_ACCOUNT_ID", "").strip()
    dsa = os.environ.get("META_DSA_BENEFICIARY", "News Impact Screener").strip()
    scat = os.environ.get("META_SPECIAL_AD_CATEGORY", "").strip()
    special = [scat] if scat else []
    budget_minor = int(round(budget_dkk * 100))  # DKK → øre

    specs = [(slug, *_load(slug)) for slug in slugs]

    print(f"\nCAMPAIGN  “Feature A/B — screener vs news”  ·  OUTCOME_TRAFFIC  ·  "
          f"special={special or 'none'}  ·  PAUSED")
    for slug, spec, cards in specs:
        ad = spec.get("ad", {})
        kind = "single image" if len(cards) == 1 else f"carousel · {len(cards)} cards"
        print(f"  AD SET  {slug}  ·  {budget_dkk:.0f} DKK/day  ·  DK 18–65  ·  "
              f"optimize LINK_CLICKS  ·  PAUSED")
        print(f"    AD    {kind}  ·  cta={ad.get('cta_label')}")
        print(f"          → {ad.get('destination', '')[:78]}")

    if dry_run:
        print("\n[dry-run] nothing created. Set META_ADS_TOKEN (ads_management) + "
              "META_PAGE_ID in .env, then re-run with --go.")
        return 0
    if not page:
        raise MetaError("META_PAGE_ID not set in .env (ads must run from a Facebook Page)")

    campaign_id = create_campaign("Feature A/B — screener vs news", special)
    print(f"\n✓ campaign {campaign_id} (PAUSED)")
    try:
        for slug, spec, cards in specs:
            ad = spec["ad"]
            hashes = [upload_image(c) for c in cards]
            cta = CTA_MAP.get((ad.get("cta_label") or "learn more").lower(), "LEARN_MORE")
            creative = create_creative(f"{slug}-creative", page, ig, ad["destination"],
                                       ad.get("primary_text", ""), cta, hashes,
                                       headline=ad.get("headline"), description=ad.get("description"))
            adset = create_adset(slug, campaign_id, budget_minor,
                                 {"geo_locations": {"countries": ["DK"]}, "age_min": 18, "age_max": 65},
                                 dsa)
            ad_id = create_ad(f"{slug}-ad", adset, creative)
            print(f"  ✓ {slug}: adset {adset} · ad {ad_id} · creative {creative}  (PAUSED)")
    except Exception:
        _delete(campaign_id)  # rollback — no orphan campaign left behind
        print(f"  ✗ failed — rolled back campaign {campaign_id}")
        raise
    print("\nAll PAUSED — review in Ads Manager, then set Active to launch.")
    return 0
