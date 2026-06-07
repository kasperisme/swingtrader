"""Language support for agent output + Telegram delivery.

Mirror of code/ui/lib/languages.ts. A user's preferred language lives in
``swingtrader.user_profiles.metadata.preferred_language`` (default "en").

Two halves:
  - ``language_instruction(lang)`` appends a "respond in X" line to LLM system
    prompts so generated prose (summaries, key findings) comes back localized.
  - ``I18N_MESSAGES`` / ``get_message`` hold the fixed Telegram template strings
    (headers, status labels, CTAs) translated per language.
"""

from __future__ import annotations

import logging

from shared.db import get_supabase_client

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "en"

# code -> English name (used in the LLM "respond in X" instruction)
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "pt": "Portuguese",
    "it": "Italian",
    "da": "Danish",
}

SUPPORTED_LANGUAGES = set(LANGUAGE_NAMES)


def normalize_language(value: object) -> str:
    """Coerce any stored value to a supported code, defaulting to English."""
    return value if isinstance(value, str) and value in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def language_instruction(language: str) -> str:
    """System-prompt suffix instructing the model to answer in ``language``.

    Empty for English (the base prompts are already English). Symbols, numbers,
    and proper nouns are kept as-is so tickers and prices don't get mangled.
    """
    lang = normalize_language(language)
    if lang == "en":
        return ""
    name = LANGUAGE_NAMES[lang]
    return (
        f"\n\n## Language\n"
        f"Write ALL user-facing output (summaries, key findings, alert text) in {name}. "
        "Keep ticker symbols, numbers, dates, and proper nouns unchanged."
    )


# ── Fixed Telegram template strings ─────────────────────────────────────────
# Keys are referenced by the engine + market-screenings runner formatters.
# Emoji and {name}/{summary} placeholders live in the formatter, not here.

I18N_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "run_failed": "Run failed",
        "no_trigger": "No trigger — conditions not met.",
        "billing_paused": "Agent paused",
        "billing_body": "Running scheduled agents requires an active paid plan. Set up billing to resume your alerts:",
        "billing_cta": "Set up billing",
        "new_screening": "New screening",
        "ticker_one": "ticker",
        "ticker_many": "tickers",
    },
    "es": {
        "run_failed": "Error en la ejecución",
        "no_trigger": "Sin activación — no se cumplen las condiciones.",
        "billing_paused": "Agente en pausa",
        "billing_body": "Ejecutar agentes programados requiere un plan de pago activo. Configura la facturación para reanudar tus alertas:",
        "billing_cta": "Configurar facturación",
        "new_screening": "Nuevo screening",
        "ticker_one": "ticker",
        "ticker_many": "tickers",
    },
    "de": {
        "run_failed": "Ausführung fehlgeschlagen",
        "no_trigger": "Kein Auslöser — Bedingungen nicht erfüllt.",
        "billing_paused": "Agent pausiert",
        "billing_body": "Für geplante Agenten ist ein aktives, kostenpflichtiges Abo erforderlich. Richte die Abrechnung ein, um deine Benachrichtigungen fortzusetzen:",
        "billing_cta": "Abrechnung einrichten",
        "new_screening": "Neues Screening",
        "ticker_one": "Ticker",
        "ticker_many": "Ticker",
    },
    "fr": {
        "run_failed": "Échec de l'exécution",
        "no_trigger": "Aucun déclenchement — conditions non remplies.",
        "billing_paused": "Agent en pause",
        "billing_body": "L'exécution d'agents programmés nécessite un abonnement payant actif. Configurez la facturation pour reprendre vos alertes :",
        "billing_cta": "Configurer la facturation",
        "new_screening": "Nouveau screening",
        "ticker_one": "ticker",
        "ticker_many": "tickers",
    },
    "pt": {
        "run_failed": "Falha na execução",
        "no_trigger": "Sem acionamento — condições não satisfeitas.",
        "billing_paused": "Agente pausado",
        "billing_body": "Executar agentes agendados requer um plano pago ativo. Configure o faturamento para retomar seus alertas:",
        "billing_cta": "Configurar faturamento",
        "new_screening": "Novo screening",
        "ticker_one": "ticker",
        "ticker_many": "tickers",
    },
    "it": {
        "run_failed": "Esecuzione non riuscita",
        "no_trigger": "Nessun trigger — condizioni non soddisfatte.",
        "billing_paused": "Agente in pausa",
        "billing_body": "L'esecuzione di agenti pianificati richiede un piano a pagamento attivo. Configura la fatturazione per riprendere i tuoi avvisi:",
        "billing_cta": "Configura la fatturazione",
        "new_screening": "Nuovo screening",
        "ticker_one": "ticker",
        "ticker_many": "ticker",
    },
    "da": {
        "run_failed": "Kørsel mislykkedes",
        "no_trigger": "Ingen udløsning — betingelser ikke opfyldt.",
        "billing_paused": "Agent sat på pause",
        "billing_body": "Planlagte agenter kræver et aktivt betalt abonnement. Opsæt betaling for at genoptage dine beskeder:",
        "billing_cta": "Opsæt betaling",
        "new_screening": "Ny screening",
        "ticker_one": "ticker",
        "ticker_many": "tickere",
    },
}


def get_message(language: str, key: str) -> str:
    """Localized template string, falling back to English for any gap."""
    lang = normalize_language(language)
    table = I18N_MESSAGES.get(lang, I18N_MESSAGES["en"])
    return table.get(key) or I18N_MESSAGES["en"].get(key, "")


def get_user_language(user_id: str | None) -> str:
    """Read a user's preferred_language from user_profiles.metadata.

    Best-effort: any error or missing row yields the default ("en"), so a
    delivery never fails just because the preference lookup did.
    """
    if not user_id:
        return DEFAULT_LANGUAGE
    try:
        res = (
            get_supabase_client()
            .schema("swingtrader")
            .table("user_profiles")
            .select("metadata")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        row = (res.data or [{}])[0]
        metadata = row.get("metadata") or {}
        return normalize_language(metadata.get("preferred_language"))
    except Exception as exc:  # noqa: BLE001 — never block delivery on this
        log.warning("[i18n] language lookup failed for user %s: %s", user_id, exc)
        return DEFAULT_LANGUAGE
