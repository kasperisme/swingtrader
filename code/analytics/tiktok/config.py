from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parent.parent

EASTERN = ZoneInfo("America/New_York")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_TIKTOK_MODEL = (
    os.environ.get("OLLAMA_TIKTOK_MODEL")
    or os.environ.get("OLLAMA_BLOG_MODEL")
    or os.environ.get("OLLAMA_IMPACT_MODEL")
    or "gemma4:e4b"
)

OUTPUT_DIR = Path(os.environ.get("TIKTOK_OUTPUT_DIR", str(_REPO_ROOT / "output" / "tiktok")))

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 24
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"

SAFE_ZONE_RIGHT = 1.0
SAFE_ZONE_BOTTOM = 0.15

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")  # Daniel
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")

BACKGROUND_MUSIC = os.environ.get("TIKTOK_BG_MUSIC", "")
BG_MUSIC_VOLUME = float(os.environ.get("TIKTOK_BG_MUSIC_VOLUME", "0.08"))

REPORTER_VIDEO = os.environ.get(
    "TIKTOK_REPORTER_VIDEO",
    str(_REPO_ROOT / "scripts" / "assets" / "reporter.mp4"),
)

LOOKBACK_HOURS = int(os.environ.get("TIKTOK_LOOKBACK_HOURS", "14"))
MAX_ARTICLES = int(os.environ.get("TIKTOK_MAX_ARTICLES", "15"))

CLUSTERS = [
    {
        "id": "MACRO_SENSITIVITY",
        "label": "Macro Sensitivity",
        "dimensions": [
            ("interest_rate_sensitivity_duration", "Interest Rate (Duration)"),
            ("interest_rate_sensitivity_debt", "Interest Rate (Debt)"),
            ("dollar_sensitivity", "Dollar Sensitivity"),
            ("inflation_sensitivity", "Inflation Sensitivity"),
            ("credit_spread_sensitivity", "Credit Spread Sensitivity"),
            ("commodity_input_exposure", "Commodity Input Exposure"),
            ("energy_cost_intensity", "Energy Cost Intensity"),
        ],
    },
    {
        "id": "SECTOR_ROTATION",
        "label": "Sector Rotation",
        "dimensions": [
            ("sector_financials", "Financials"),
            ("sector_technology", "Technology"),
            ("sector_healthcare", "Healthcare"),
            ("sector_energy", "Energy"),
            ("sector_realestate", "Real Estate"),
            ("sector_consumer", "Consumer"),
            ("sector_industrials", "Industrials"),
            ("sector_utilities", "Utilities"),
        ],
    },
    {
        "id": "BUSINESS_MODEL",
        "label": "Business Model",
        "dimensions": [
            ("revenue_predictability", "Revenue Predictability"),
            ("revenue_cyclicality", "Revenue Cyclicality"),
            ("pricing_power_structural", "Structural Pricing Power"),
            ("pricing_power_cyclical", "Cyclical Pricing Power"),
            ("capex_intensity", "Capex Intensity"),
        ],
    },
    {
        "id": "FINANCIAL_STRUCTURE",
        "label": "Financial Structure",
        "dimensions": [
            ("debt_burden", "Debt Burden"),
            ("floating_rate_debt_ratio", "Floating Rate Debt"),
            ("debt_maturity_nearterm", "Near-Term Debt Maturity"),
            ("financial_health", "Financial Health"),
            ("earnings_quality", "Earnings Quality"),
            ("accruals_ratio", "Accruals Ratio"),
            ("buyback_capacity", "Buyback Capacity"),
        ],
    },
    {
        "id": "GROWTH_PROFILE",
        "label": "Growth Profile",
        "dimensions": [
            ("revenue_growth_rate", "Revenue Growth"),
            ("eps_growth_rate", "EPS Growth"),
            ("eps_acceleration", "EPS Acceleration"),
            ("forward_growth_expectations", "Forward Growth"),
            ("earnings_revision_trend", "Earnings Revisions"),
        ],
    },
    {
        "id": "VALUATION_POSITIONING",
        "label": "Valuation & Positioning",
        "dimensions": [
            ("valuation_multiple", "Valuation Multiple"),
            ("factor_value", "Value Factor"),
            ("short_interest_ratio", "Short Interest"),
            ("short_squeeze_risk", "Short Squeeze Risk"),
            ("price_momentum", "Price Momentum"),
        ],
    },
    {
        "id": "GEOGRAPHY_TRADE",
        "label": "Geography & Trade",
        "dimensions": [
            ("china_revenue_exposure", "China Exposure"),
            ("emerging_market_exposure", "EM Exposure"),
            ("domestic_revenue_concentration", "Domestic Revenue"),
            ("tariff_sensitivity", "Tariff Sensitivity"),
        ],
    },
    {
        "id": "SUPPLY_CHAIN_EXPOSURE",
        "label": "Supply Chain",
        "dimensions": [
            ("upstream_concentration", "Supplier Concentration"),
            ("geographic_supply_risk", "Geographic Supply Risk"),
            ("inventory_intensity", "Inventory Intensity"),
            ("input_specificity", "Input Specificity"),
            ("supplier_bargaining_power", "Supplier Bargaining Power"),
            ("downstream_customer_concentration", "Customer Concentration"),
        ],
    },
    {
        "id": "MARKET_BEHAVIOUR",
        "label": "Market Behaviour",
        "dimensions": [
            ("institutional_appeal", "Institutional Appeal"),
            ("institutional_ownership_change", "Inst. Ownership Change"),
            ("short_squeeze_potential", "Short Squeeze Potential"),
            ("earnings_surprise_volatility", "Earnings Surprise Vol."),
        ],
    },
]

CLUSTER_ID_TO_LABEL = {c["id"]: c["label"] for c in CLUSTERS}
DIM_KEY_TO_LABEL = {}
for c in CLUSTERS:
    for key, label in c["dimensions"]:
        DIM_KEY_TO_LABEL[key] = label

CAPTION_FONT_SIZE = 52
CAPTION_MAX_CHARS = 32

BG_COLOR = "#FCFAF6"
TEXT_COLOR = "#0E1629"
TEXT_COLOR_DIM = "#536278"
BRAND_COLOR = "#F49E0A"
BRAND_COLOR_DIM = "#DFD6CD"
ACCENT_GREEN = "#10B981"
ACCENT_RED = "#EF4444"
ACCENT_YELLOW = "#F19040"
