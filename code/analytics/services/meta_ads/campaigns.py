"""Create the feature A/B as PAUSED drafts in Ads Manager (nothing spends until
you flip them to Active). One campaign → one ad set per feature → one carousel ad
per feature, built from the ad specs + their 1:1 slides.

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


def create_creative(name, page_id, ig_id, dest, message, cta_type, image_hashes) -> str:
    def spec(with_ig: bool) -> dict:
        s = {
            "page_id": page_id,
            "link_data": {
                "link": dest,
                "message": message,
                "child_attachments": [{"link": dest, "image_hash": h} for h in image_hashes],
                "call_to_action": {"type": cta_type, "value": {"link": dest}},
                "multi_share_optimized": False,   # keep our slide order (don't auto-reorder)
                "multi_share_end_card": True,
            },
        }
        if with_ig and ig_id:
            s["instagram_actor_id"] = ig_id
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


def _load(slug: str):
    d = client._ANALYTICS / "output" / "ads" / slug
    spec = json.loads((d / "ad.json").read_text())
    cards = sorted((d / "1x1").glob("slide-*.png"))
    if len(cards) < 2:
        raise MetaError(f"{slug}: need ≥2 1:1 cards — render with --ratios 1x1 first")
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
        print(f"  AD SET  {slug}  ·  {budget_dkk:.0f} DKK/day  ·  DK 18–65  ·  "
              f"optimize LINK_CLICKS  ·  PAUSED")
        print(f"    AD    carousel · {len(cards)} cards  ·  cta={ad.get('cta_label')}")
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
                                       ad.get("primary_text", ""), cta, hashes)
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
