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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from . import client
from .client import MetaError


def _split_utm(dest: str) -> tuple[str, str]:
    """Split a destination into (clean_link, url_tags). The UTM params move into the
    creative's `url_tags` field — Meta's canonical place for tracking params — which
    it (a) appends to every outbound click (so the landing page + Supabase capture
    still see utm_content) and (b) exposes on the creative so `insights`/`reconcile`
    can attribute each ad to its feature. Non-UTM query (tags/tickers presets) stays
    on the link. Prevents the duplicate-param mess of putting UTM in both places."""
    parts = urlsplit(dest)
    q = parse_qsl(parts.query, keep_blank_values=True)
    is_tag = lambda k: k.startswith("utm_") or k in ("fbclid", "gclid", "ttclid")
    keep = [(k, v) for k, v in q if not is_tag(k)]
    utm = [(k, v) for k, v in q if is_tag(k)]
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(keep), parts.fragment))
    return clean, urlencode(utm)

FEATURES = ["feat-screening-v1", "feat-news-v1"]
# EU/EEA member states — DSA beneficiary/payor is required only when targeting these.
_EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES",
    "SE", "IS", "LI", "NO",
}
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
                    headline=None, description=None, url_tags=None) -> str:
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

    # url_tags is a TOP-LEVEL creative field (not inside object_story_spec). Meta
    # appends it to every outbound click (so the landing page + Supabase still capture
    # utm_content) AND exposes it on the creative so insights/reconcile group by feature.
    def body(with_ig: bool) -> dict:
        b = {"name": name, "object_story_spec": json.dumps(spec(with_ig))}
        if url_tags:
            b["url_tags"] = url_tags
        return b

    try:
        return _post(f"{client.account()}/adcreatives", body(True))["id"]
    except MetaError as e:
        # Fall back to a Page-only creative when the IG identity is rejected — either
        # a plain access error ("instagram") or the IG account's "less-personalized
        # ads" / advertiser-identity block (subcode 3858412, message names the handle
        # but not the word "instagram").
        msg = str(e).lower()
        if ig_id and ("instagram" in msg or "personalized" in msg
                      or "advertiser" in msg or "3858412" in msg):
            print("    (IG identity rejected — creating Page-only; set an IG account "
                  "on the ad in Ads Manager if you want a specific handle)")
            return _post(f"{client.account()}/adcreatives", body(False))["id"]
        raise


def create_campaign(name: str, special: list[str], objective: str) -> str:
    try:
        return _post(f"{client.account()}/campaigns", {
            "name": name, "objective": objective, "status": "PAUSED",
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


def create_adset(name, campaign_id, budget_minor, targeting, dsa,
                 optimization_goal, promoted_object=None) -> str:
    body = {
        "name": name, "campaign_id": campaign_id, "status": "PAUSED",
        "daily_budget": str(budget_minor),
        "billing_event": "IMPRESSIONS", "optimization_goal": optimization_goal,
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "targeting": json.dumps(targeting),
    }
    # Conversion optimization (leads): tell Meta which pixel event to optimize for.
    if promoted_object:
        body["promoted_object"] = json.dumps(promoted_object)
    # DSA transparency (who benefits / who pays) — required when the audience
    # includes the EU, ignored otherwise; safe to always send.
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


# Saved-content convention: output/ads/<date>-<short-name>/<lead-magnet>/<format>/…
# where <lead-magnet> ∈ {briefing, market-screening}. Each magnet folder holds an
# ad.json + 1x1/ad.png. A "campaign" is the <date>-<short-name> dir; its magnet
# subfolders become the ad sets.
LEAD_MAGNETS = ("briefing", "market-screening")


def discover_campaign(name: str) -> tuple[list[str], str]:
    """Given a <date>-<short-name> campaign dir, return its lead-magnet ad slugs
    (`<name>/briefing`, `<name>/market-screening`, …) + the campaign name."""
    d = client._ANALYTICS / "output" / "ads" / name
    if not d.is_dir():
        raise MetaError(f"campaign dir not found: output/ads/{name}/")
    ordered = [m for m in LEAD_MAGNETS if (d / m / "ad.json").exists()]
    extra = sorted(s.name for s in d.iterdir()
                   if s.is_dir() and s.name not in LEAD_MAGNETS and (s / "ad.json").exists())
    magnets = ordered + extra
    if not magnets:
        raise MetaError(f"no lead-magnet ads (…/ad.json) found under output/ads/{name}/")
    return [f"{name}/{m}" for m in magnets], name


def build_drafts(slugs: list[str], budget_dkk: float, dry_run: bool,
                 campaign_name: str = "Feature A/B — screener vs news") -> int:
    page = os.environ.get("META_PAGE_ID", "").strip()
    ig = os.environ.get("META_IG_ACCOUNT_ID", "").strip()
    dsa = os.environ.get("META_DSA_BENEFICIARY", "News Impact Screener").strip()
    scat = os.environ.get("META_SPECIAL_AD_CATEGORY", "").strip()
    special = [scat] if scat else []
    budget_minor = int(round(budget_dkk * 100))  # DKK → øre

    # ── audience + objective (all env-overridable) ──────────────────────────
    # Default: English-speaking markets that match a US-stock product, optimizing
    # for the pixel LEAD event (sign-ups) — not just cheap clicks.
    countries = [c.strip().upper() for c in
                 os.environ.get("META_TARGET_COUNTRIES", "US,GB,CA,AU").split(",") if c.strip()]
    age_min = int(os.environ.get("META_AGE_MIN", "18"))
    age_max = int(os.environ.get("META_AGE_MAX", "65"))
    objective = os.environ.get("META_OBJECTIVE", "OUTCOME_LEADS").strip()
    opt_goal = os.environ.get("META_OPTIMIZATION_GOAL", "OFFSITE_CONVERSIONS").strip()
    conv_event = os.environ.get("META_CONVERSION_EVENT", "LEAD").strip()
    pixel = os.environ.get("META_PIXEL_ID", "").strip()
    targeting = {"geo_locations": {"countries": countries}, "age_min": age_min, "age_max": age_max}

    promoted_object = None
    if opt_goal == "OFFSITE_CONVERSIONS":
        if not pixel:
            raise MetaError(
                "lead optimization (OFFSITE_CONVERSIONS) needs a pixel — set META_PIXEL_ID in .env "
                "(your web Pixel id), or set META_OPTIMIZATION_GOAL=LINK_CLICKS to optimize for clicks.")
        promoted_object = {"pixel_id": pixel, "custom_event_type": conv_event}

    # DSA beneficiary/payor is EU-only — sending it on a non-EU geo can error, so
    # only attach it when the audience actually includes an EU country.
    dsa_eff = dsa if any(c in _EU_COUNTRIES for c in countries) else ""

    # label = the last path segment (the lead magnet), for readable ad-set/ad names
    specs = [(slug, slug.split("/")[-1], *_load(slug)) for slug in slugs]

    geo_str = ",".join(countries)
    print(f"\nCAMPAIGN  “{campaign_name}”  ·  {objective}  ·  special={special or 'none'}  ·  PAUSED")
    for slug, label, spec, cards in specs:
        ad = spec.get("ad", {})
        kind = "single image" if len(cards) == 1 else f"carousel · {len(cards)} cards"
        goal_str = (f"optimize {conv_event} conversions (pixel {pixel})"
                    if promoted_object else f"optimize {opt_goal}")
        print(f"  AD SET  {label}  ·  {budget_dkk:.0f} DKK/day  ·  {geo_str} {age_min}–{age_max}  ·  "
              f"{goal_str}  ·  PAUSED")
        print(f"    AD    {kind}  ·  cta={ad.get('cta_label')}")
        print(f"          → {ad.get('destination', '')[:78]}")

    if dry_run:
        print("\n[dry-run] nothing created. Set META_ADS_TOKEN (ads_management) + "
              "META_PAGE_ID in .env, then re-run with --go.")
        return 0
    if not page:
        raise MetaError("META_PAGE_ID not set in .env (ads must run from a Facebook Page)")

    campaign_id = create_campaign(campaign_name, special, objective)
    print(f"\n✓ campaign {campaign_id} (PAUSED)")
    manifest = []
    try:
        for slug, label, spec, cards in specs:
            ad = spec["ad"]
            hashes = [upload_image(c) for c in cards]
            cta = CTA_MAP.get((ad.get("cta_label") or "learn more").lower(), "LEARN_MORE")
            clean_link, url_tags = _split_utm(ad["destination"])
            creative = create_creative(f"{label}-creative", page, ig, clean_link,
                                       ad.get("primary_text", ""), cta, hashes,
                                       headline=ad.get("headline"), description=ad.get("description"),
                                       url_tags=url_tags)
            adset = create_adset(label, campaign_id, budget_minor, targeting, dsa_eff,
                                 opt_goal, promoted_object)
            ad_id = create_ad(f"{label}-ad", adset, creative)
            print(f"  ✓ {label}: adset {adset} · ad {ad_id} · creative {creative}  (PAUSED)")
            manifest.append({
                "campaign_id": campaign_id, "campaign_name": campaign_name,
                "ad_set_id": adset, "ad_id": ad_id, "creative_id": creative,
                "lead_magnet": label, "slug": slug,
                "design": _design_for(slug),   # the creative genome → join engagement on ad_id
            })
    except Exception:
        _delete(campaign_id)  # rollback — no orphan campaign left behind
        print(f"  ✗ failed — rolled back campaign {campaign_id}")
        raise

    _write_manifest(campaign_name, manifest)
    print("\nAll PAUSED — review in Ads Manager, then set Active to launch.")
    return 0


def _design_for(slug: str) -> dict:
    """The resolved design.json a render wrote next to the spec (creative genome)."""
    p = client._ANALYTICS / "output" / "ads" / slug / "design.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _write_manifest(campaign_name: str, rows: list[dict]) -> None:
    """Persist ad_id → design so engagement (Meta insights, by ad_id) can be joined to
    the creative attributes later. Written to the campaign folder when it exists."""
    if not rows:
        return
    camp_dir = client._ANALYTICS / "output" / "ads" / campaign_name
    dest = (camp_dir if camp_dir.is_dir() else client._ANALYTICS / "output" / "ads") / "launch_manifest.json"
    prior = []
    if dest.exists():
        try:
            prior = json.loads(dest.read_text())
        except ValueError:
            prior = []
    dest.write_text(json.dumps(prior + rows, indent=2))
    print(f"  ↳ launch manifest → {dest}")
