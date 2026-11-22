from services.arena.digest import render


def _d():
    return {
        "session": "2026-11-20", "championship": {"name": "Season 1"}, "next_session": "2026-11-23",
        "headline": {"headline": "Jim Chaos leads", "detail": "Up 7%."},
        "names": {"a": "Agent <A>", "b": "Agent B"},
        "rows": [{"rank": 1, "slug": "a", "name": "Agent <A>", "return": 0.0719, "daily": -0.0058, "move": 2},
                 {"rank": 2, "slug": "b", "name": "Agent B", "return": -0.01, "daily": None, "move": -2}],
        "filled": [{"agent_slug": "a", "ticker": "UNH", "side": "sell", "quantity": 20, "fill_price": 339.77,
                    "position_effect": "open_short", "realized_pnl": None}],
        "queued": [{"agent_slug": "b", "ticker": "NVDA", "side": "sell", "quantity": 60, "thesis": "x" * 300}],
    }


def test_digest_renders_table_trades_and_unsubscribe():
    subject, html, text = render(_d(), "https://u.example/unsub?t=1")
    assert subject == "Arena, 2026-11-20: Jim Chaos leads"
    assert "Agent &lt;A&gt;" in html and "<A>" not in html            # names are escaped
    assert "&#9650;2" in html and "&#9660;2" in html                   # movement both ways
    assert "shorted 20 UNH at $339.77" in html
    assert "x" * 180 + "…" in html and "x" * 181 not in html           # thesis truncated
    assert "https://u.example/unsub?t=1" in html and "Unsubscribe: https://u.example/unsub?t=1" in text
    assert "(2026-11-23)" in text
