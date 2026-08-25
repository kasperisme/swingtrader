"""The briefing's one ask: what it picks, and what it refuses to pretend.

The email is the only surface that reaches all 105 subscribers on a schedule,
and until now it asked for nothing that needed an account — its CTAs resolved
perfectly well while logged out. These tests pin the two things that make the
replacement work rather than just exist:

  * the action names something that ACTUALLY happened to this reader's own
    watchlist, and degrades to a quieter ask when nothing did, and
  * the destination is always behind the auth wall, because an action that
    resolves logged out cannot move anyone up a rung.
"""

from __future__ import annotations

import base64
import json
import os

import pytest

from services.briefings.action import choose_action


def section(ticker: str, n: int, sentiment: float) -> dict:
    return {
        "ticker": ticker,
        "article_count": n,
        "avg_sentiment": sentiment,
        "items": [{"title": f"{ticker} story {i}"} for i in range(n)],
    }


def briefing(*sections: dict, tags: list | None = None) -> dict:
    return {"tickers": list(sections), "tags": tags or [], "total_articles":
            sum(s["article_count"] for s in sections)}


# ---------------------------------------------------------------- movers ---
def test_picks_the_tickers_that_actually_moved():
    b = briefing(section("NVDA", 4, -0.6), section("KO", 0, 0.0),
                 section("AMD", 3, -0.5))
    a = choose_action(b, tickers=["NVDA", "KO", "AMD"], tags=[])
    assert a["kind"] == "movers"
    assert "NVDA" in a["label"] and "AMD" in a["label"]
    assert "KO" not in a["label"], "a ticker with no news is not a mover"


def test_confidence_beats_a_single_loud_outlier():
    """Three stories agreeing outranks one extreme print.

    Ranking on |sentiment| alone puts a lone -0.9 above three consistent -0.5s,
    which is the wrong way round for someone deciding what to open first.
    """
    b = briefing(section("QUIET", 1, -0.9), section("LOUD", 6, -0.5))
    a = choose_action(b, tickers=["QUIET", "LOUD"], tags=[])
    assert a["label"].startswith("Open LOUD"), a["label"]


def test_flags_disagreement_between_movers():
    b = briefing(section("NVDA", 3, 0.7), section("INTC", 3, -0.7))
    a = choose_action(b, tickers=["NVDA", "INTC"], tags=[])
    assert "disagree" in a["sublabel"], a["sublabel"]


def test_reports_a_shared_direction_when_they_agree():
    b = briefing(section("NVDA", 3, 0.7), section("AMD", 3, 0.6))
    a = choose_action(b, tickers=["NVDA", "AMD"], tags=[])
    assert "positive" in a["sublabel"] and "disagree" not in a["sublabel"]


def test_singular_grammar_for_one_story():
    b = briefing(section("NVDA", 1, 0.5))
    a = choose_action(b, tickers=["NVDA"], tags=[])
    assert "1 scored story " in a["sublabel"], a["sublabel"]


def test_caps_at_two_movers():
    b = briefing(*[section(t, 3, -0.5) for t in ("A", "B", "C", "D")])
    a = choose_action(b, tickers=["A", "B", "C", "D"], tags=[])
    assert len(a["next_path"].split("tickers=")[1].split(",")) == 2


# ----------------------------------------------------------- quiet days ---
def test_a_quiet_day_does_not_manufacture_urgency():
    """The failure this guards: crying wolf trains people to stop opening it.

    A watchlist with no scored coverage must not produce a "your tickers moved"
    ask, because they did not.
    """
    b = briefing(section("NVDA", 0, 0.0), section("AMD", 0, 0.0))
    a = choose_action(b, tickers=["NVDA", "AMD"], tags=[])
    assert a["kind"] == "quiet"
    assert "moved" not in a["label"].lower()
    assert "NVDA" in a["next_path"]


def test_tag_only_subscribers_get_the_trend_board():
    """They have no symbol to open, so a chart deep link would be empty."""
    a = choose_action(briefing(), tickers=[], tags=["ai-chips", "tariffs"])
    assert a["kind"] == "themes"
    assert a["next_path"] == "/protected/news-trends"


def test_empty_subscription_still_returns_a_usable_action():
    a = choose_action(briefing(), tickers=[], tags=[])
    assert a["next_path"].startswith("/protected")


# ------------------------------------------------------- the load-bearing ---
@pytest.mark.parametrize("tickers,tags", [
    (["NVDA"], []),
    ([], ["ai-chips"]),
    ([], []),
])
def test_every_action_lands_behind_the_auth_wall(tickers, tags):
    """The whole point of the change.

    `/quote/<symbol>` and `/marketscreenings` both render logged out, which is
    why the previous CTAs converted nobody. If any branch here ever routes
    somewhere public, the email goes back to asking for nothing.
    """
    b = briefing(section("NVDA", 3, 0.5)) if tickers else briefing()
    a = choose_action(b, tickers=tickers, tags=tags)
    assert a["next_path"].startswith("/protected"), a


def test_action_shape_is_complete():
    a = choose_action(briefing(section("NVDA", 2, 0.4)), tickers=["NVDA"], tags=[])
    assert set(a) == {"kind", "label", "sublabel", "next_path"}
    assert a["label"] and a["next_path"]


# -------------------------------------------------- cross-language token ---
def test_token_payload_matches_what_the_typescript_verifier_requires():
    """The TS route refuses anything without `p == "signin"` and a live `exp`.

    Both sides are hand-written against the same shape, so a change to either
    is a silent breakage of one-click sign-in — the failure would look like
    "everyone suddenly has to log in", with no error anywhere.
    """
    os.environ["UNSUBSCRIBE_SECRET"] = "test-secret"
    from shared.email import sign_signin_token

    token = sign_signin_token("Reader@Example.com", "/protected/charts?tickers=NVDA")
    body = token.split(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))

    assert payload["p"] == "signin"
    assert payload["next"].startswith("/protected")
    assert isinstance(payload["exp"], int)
    assert "@" in payload["email"]


def test_token_expiry_is_bounded():
    """A briefing lives in an inbox forever and gets forwarded."""
    os.environ["UNSUBSCRIBE_SECRET"] = "test-secret"
    from shared.email import sign_signin_token

    token = sign_signin_token("a@b.com", "/protected", ttl_days=7, now=1_000_000)
    body = token.split(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert payload["exp"] == 1_000_000 + 7 * 86400


def test_a_weak_read_next_to_a_clear_one_is_not_called_disagreement():
    """Found against live data: INTC at -0.30 and AMD at -0.08.

    One clear negative and one too weak to call is not two views in conflict.
    Overstating it is exactly the small dishonesty that teaches a reader to
    discount everything else in the email.
    """
    b = briefing(section("INTC", 2, -0.30), section("AMD", 6, -0.083))
    a = choose_action(b, tickers=["INTC", "AMD"], tags=[])
    assert "disagree" not in a["sublabel"], a["sublabel"]
    assert "leaning" not in a["sublabel"], a["sublabel"]
    assert "8 scored stories" in a["sublabel"]


def test_genuinely_opposed_movers_still_say_so():
    b = briefing(section("NVDA", 3, 0.6), section("INTC", 3, -0.6))
    a = choose_action(b, tickers=["NVDA", "INTC"], tags=[])
    assert "disagree" in a["sublabel"]


@pytest.mark.parametrize("tickers,verb", [(["KO", "PEP"], " sit "), (["KO"], " sits ")])
def test_quiet_copy_agrees_in_number(tickers, verb):
    b = briefing(*[section(t, 0, 0.0) for t in tickers])
    a = choose_action(b, tickers=tickers, tags=[])
    assert verb in a["sublabel"], a["sublabel"]
