"""report.py — render a performance snapshot to a self-contained HTML report.

Dark, brand-styled (amber accent), no external assets — open it, print it, or
share it. Degrades gracefully: any unavailable platform block just shows a muted
note. Driven entirely by the snapshot dict from snapshot.build_snapshot()."""

from __future__ import annotations

import html as _html
from typing import Any

_SEV = {"high": "#ff5c5c", "medium": "#f5a623", "low": "#8b93a7", "info": "#6fa8ff"}
_SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _e(v: Any) -> str:
    return _html.escape(str(v), quote=True)


def _kpi(label: str, value: str, sub: str = "") -> str:
    return (f'<div class="kpi"><div class="kpi-l">{_e(label)}</div>'
            f'<div class="kpi-v">{_e(value)}</div>'
            + (f'<div class="kpi-s">{_e(sub)}</div>' if sub else "") + '</div>')


def _rows(headers: list[str], rows: list[list[str]], aligns: list[str] | None = None) -> str:
    al = aligns or (["left"] + ["right"] * (len(headers) - 1))
    th = "".join(f'<th style="text-align:{a}">{_e(h)}</th>' for h, a in zip(headers, al))
    body = ""
    for r in rows:
        tds = "".join(f'<td style="text-align:{a}">{c}</td>' for c, a in zip(r, al))
        body += f"<tr>{tds}</tr>"
    return f'<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def _section(title: str, inner: str, note: str = "") -> str:
    n = f'<span class="sec-note">{_e(note)}</span>' if note else ""
    return f'<section><h2>{_e(title)}{n}</h2>{inner}</section>'


def to_html(s: dict) -> str:
    cur = (s.get("meta_ads") or {}).get("currency") or ""
    f = s.get("funnel", {})
    plat = s.get("platforms", {})

    # ---- platform status chips ----
    chips = "".join(
        f'<span class="chip {"ok" if v.get("available") else "bad"}">{_e(k)}'
        f'{"" if v.get("available") else " ✗"}</span>'
        for k, v in plat.items())

    # ---- KPI row ----
    kpis = []
    if "real_leads" in f:
        cpl = f.get("blended_cost_per_lead")
        kpis.append(_kpi("Real leads", str(f["real_leads"]),
                         (f"{cpl} {cur}/lead" if cpl else "no paid leads")))
    if "paid" in f:
        kpis.append(_kpi("Paid CTR", f'{f["paid"]["ctr"]}%',
                         f'{f["paid"]["clicks"]:,} clicks · {f["paid"]["spend"]:,.0f} {cur}'))
    if "organic_search" in f:
        o = f["organic_search"]
        kpis.append(_kpi("Organic clicks", f'{o["clicks"]:,}', f'{o["ctr"]}% CTR'))
    em = s.get("email", {})
    if em.get("available"):
        t = em["totals"]
        kpis.append(_kpi("Email delivered", f'{t["delivery_rate"]}%',
                         (f'{t["open_rate"]}% open · {t["click_rate"]}% click'
                          if em["tracking_on"] else f'{t["sent"]} sent · tracking off')))
    on = s.get("onsite", {})
    if on.get("available"):
        kpis.append(_kpi("Confirmed subs", str(on.get("confirmed_subscribes", 0)),
                         f'{on.get("pageviews", 0):,} pageviews'))
    kpi_row = f'<div class="kpis">{"".join(kpis)}</div>' if kpis else ""

    # ---- funnel ----
    fl = []
    if "paid" in f:
        fl.append(f'<li><b>Paid</b> {f["paid"]["impressions"]:,} impr → {f["paid"]["clicks"]:,} '
                  f'clicks ({f["paid"]["ctr"]}% CTR) · {f["paid"]["spend"]:,.0f} {cur}</li>')
    if "organic_search" in f:
        fl.append(f'<li><b>Organic search</b> {f["organic_search"]["impressions"]:,} impr → '
                  f'{f["organic_search"]["clicks"]:,} clicks</li>')
    if "ga4_sessions" in f:
        fl.append(f'<li><b>GA4 sessions</b> {f["ga4_sessions"]:,} '
                  f'<span class="warn">⚠ may include bots</span></li>')
    if "real_leads" in f:
        fl.append(f'<li><b>Real leads</b> {f["real_leads"]} (Supabase truth)</li>')
    funnel = _section("Funnel", f'<ul class="funnel">{"".join(fl)}</ul>') if fl else ""

    # ---- cost per lead ----
    eff = ""
    if s.get("efficiency"):
        rows = [[f'<code>{_e(r["feature"])}</code>', f'{r["spend"]:,.0f}', str(r["clicks"]),
                 f'{r["ctr"]}%', str(r["real_leads"]),
                 (f'{r["cost_per_lead"]}' if r["cost_per_lead"] is not None else "—"),
                 f'{r["landing_cvr"]}%'] for r in s["efficiency"]]
        m = s.get("meta_ads", {})
        note = (f'ACTIVE-only · {m.get("paused_spend", 0):.0f} {cur} paused excluded'
                if m.get("available") else "")
        eff = _section("Cost per real lead — by feature",
                       _rows([f"feature", f"spend ({cur})", "clicks", "CTR", "leads",
                              f"{cur}/lead", "land CVR"], rows), note)

    # ---- on-site CRO ----
    onsite = ""
    if on.get("available"):
        ff = on.get("form_funnel", {})
        inner = f'<p class="line">Pageviews <b>{on.get("pageviews", 0):,}</b> · confirmed subscribes ' \
                f'<b>{on.get("confirmed_subscribes", 0)}</b> · early-access {on.get("early_access_signups", 0)}</p>'
        if on.get("client_funnel_instrumented"):
            inner += f'<p class="line">Form funnel: viewed <b>{ff.get("form_viewed",0)}</b> → ' \
                     f'submitted <b>{ff.get("form_submitted",0)}</b> → subscribed <b>{ff.get("subscribed_client",0)}</b></p>'
        else:
            inner += '<p class="line warn">⚠ Client form-funnel not capturing yet — on-site drop-off is invisible.</p>'
        dl = on.get("downloads", {})
        inner += f'<p class="line">Screening downloads: {dl.get("events",0)} by {dl.get("people",0)} people</p>'
        onsite = _section("On-site funnel (CRO)", inner)

    # ---- email ----
    email = ""
    if em.get("available"):
        track_on = em["tracking_on"]
        hdrs = ["magnet", "sent", "delivered", "bounce"] + (["open", "click"] if track_on else [])
        rows = []
        for mag, g in list(em["by_magnet"].items())[:8]:
            row = [f'<code>{_e(mag)}</code>', str(g["sent"]), f'{g["delivery_rate"]}%', f'{g["bounce_rate"]}%']
            if track_on:
                row += [f'{g["open_rate"]}%', f'{g["click_rate"]}%']
            rows.append(row)
        note = "open/click ON" if track_on else "open/click OFF — deliverability only"
        email = _section("Email (Resend)", _rows(hdrs, rows), note)

    # ---- SEO ----
    seo = ""
    sc = s.get("search_console", {})
    if sc.get("available"):
        summ = sc.get("summary", {})
        top = "".join(f'<li><code>{_e(q.get("query",""))}</code> — {int(q.get("clicks",0))} clicks · '
                      f'{q.get("ctr",0):.1f}% CTR · pos {q.get("position",0):.1f}</li>'
                      for q in (sc.get("top_queries") or [])[:8])
        seo = _section("Organic search (Search Console)",
                       f'<p class="line">{int(summ.get("impressions",0)):,} impressions · '
                       f'{int(summ.get("clicks",0)):,} clicks · {summ.get("ctr",0):.2f}% CTR · '
                       f'avg pos {summ.get("position",0):.1f}</p>'
                       f'<div class="sub">Top queries</div><ul class="tight">{top}</ul>')

    # ---- action flags ----
    flags = sorted(s.get("health_flags", []), key=lambda x: _SEV_ORDER.get(x.get("severity"), 9))
    fcards = ""
    for fl_ in flags:
        col = _SEV.get(fl_.get("severity"), "#8b93a7")
        fcards += (f'<div class="flag" style="border-left-color:{col}">'
                   f'<div class="flag-h"><span class="sev" style="background:{col}">'
                   f'{_e(fl_.get("severity","").upper())}</span>'
                   f'<span class="area">{_e(fl_.get("area",""))}</span>'
                   f'<span class="route">→ {_e(fl_.get("route_to",""))}</span></div>'
                   f'<div class="flag-f">{_e(fl_.get("finding",""))}</div>'
                   f'<div class="flag-d"><b>Do:</b> {_e(fl_.get("action",""))}</div></div>')
    flags_sec = _section("Action flags (routed)", fcards or '<p class="line">No flags — clean run.</p>')

    title = f'Website Performance — {s.get("since","")} → today ({s.get("window_days","")}d)'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_e(title)}</title>
<style>
  :root{{--bg:#0b0f17;--card:#141a26;--b:#243049;--ink:#eef1f7;--mut:#93a0ba;--dim:#6f7d99;--amber:#f5a623;
    --mono:ui-monospace,SFMono-Regular,Menlo,monospace;--sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}}
  *{{box-sizing:border-box}}body{{margin:0;background:#05070c;color:var(--ink);font-family:var(--sans);line-height:1.5}}
  .wrap{{max-width:960px;margin:0 auto;padding:40px 22px 80px}}
  header{{border-bottom:1px solid var(--b);padding-bottom:20px;margin-bottom:26px}}
  .ey{{font-family:var(--mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--amber)}}
  h1{{font-size:25px;font-weight:800;margin:8px 0 4px}}.gen{{color:var(--dim);font-size:12px;font-family:var(--mono)}}
  .chips{{display:flex;flex-wrap:wrap;gap:7px;margin-top:14px}}
  .chip{{font-family:var(--mono);font-size:11px;padding:4px 10px;border-radius:999px;border:1px solid var(--b);color:var(--mut)}}
  .chip.ok{{color:#3ecf8e}}.chip.bad{{color:#ff5c5c;border-color:#5c2530}}
  .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:8px}}
  .kpi{{background:var(--card);border:1px solid var(--b);border-radius:12px;padding:14px 16px}}
  .kpi-l{{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}}
  .kpi-v{{font-size:24px;font-weight:750;margin-top:5px}}.kpi-s{{font-size:12px;color:var(--mut);margin-top:2px}}
  section{{margin-top:30px}}h2{{font-size:13px;font-family:var(--mono);letter-spacing:.14em;text-transform:uppercase;
    color:var(--dim);border-top:1px solid var(--b);padding-top:16px;margin:0 0 14px;display:flex;justify-content:space-between;align-items:baseline}}
  .sec-note{{font-size:11px;color:var(--dim);text-transform:none;letter-spacing:0}}
  ul.funnel{{list-style:none;padding:0;margin:0}}ul.funnel li{{padding:8px 0;border-bottom:1px solid #1a2130;font-size:14px;color:var(--mut)}}
  ul.funnel b{{color:var(--ink)}}.warn{{color:#f5a623}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);
    padding:8px 10px;border-bottom:1px solid var(--b)}}
  td{{padding:8px 10px;border-bottom:1px solid #1a2130;color:var(--mut)}}td code{{color:var(--amber)}}
  .line{{font-size:14px;color:var(--mut);margin:6px 0}}.line b{{color:var(--ink)}}
  .sub{{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);margin:14px 0 6px}}
  ul.tight{{margin:0;padding-left:18px}}ul.tight li{{font-size:13px;color:var(--mut);margin:3px 0}}
  code{{font-family:var(--mono);font-size:12px}}
  .flag{{background:var(--card);border:1px solid var(--b);border-left-width:4px;border-radius:10px;padding:13px 16px;margin-bottom:10px}}
  .flag-h{{display:flex;align-items:center;gap:10px;margin-bottom:6px}}
  .sev{{font-family:var(--mono);font-size:10px;font-weight:700;color:#0b0f17;padding:2px 7px;border-radius:5px}}
  .area{{font-family:var(--mono);font-size:12px;color:var(--ink)}}.route{{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--amber)}}
  .flag-f{{font-size:13.5px;color:var(--ink);margin-bottom:5px}}.flag-d{{font-size:13px;color:var(--mut)}}
  footer{{margin-top:40px;padding-top:16px;border-top:1px solid var(--b);color:var(--dim);font-size:11px;font-family:var(--mono)}}
</style></head><body><div class="wrap">
<header><div class="ey">News Impact Screener · Performance</div>
<h1>{_e(title)}</h1><div class="gen">generated {_e(s.get("generated_at",""))}</div>
<div class="chips">{chips}</div></header>
{kpi_row}{funnel}{eff}{onsite}{email}{seo}{flags_sec}
<footer>Supabase leads = conversion truth · Meta figures ACTIVE-only · GA4 aggregates may include bot traffic · read-only snapshot</footer>
</div></body></html>"""
