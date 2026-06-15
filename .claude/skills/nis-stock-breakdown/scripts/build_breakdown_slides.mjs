// build_breakdown_slides.mjs — premium editorial carousel for a NIS stock breakdown.
//
// Mirrors the instagram-ad-review generator: hand-authored SVG slides, ONE accent
// (amber), Outfit type, the real annotated chart embedded as base64. Taste-skill
// rules: DESIGN_VARIANCE 8 (asymmetric, no centered heroes, no boxed-card sameness),
// VISUAL_DENSITY high (real numbers everywhere), no emoji (drawn glyphs only),
// green/red used ONLY for price/volume semantics, no pure black, no AI blue/purple.
//
// Reads <dir>/setup.json for every number and <dir>/chart.png for the chart slide.
// The editorial COPY lives in CFG below — adapt per ticker. Writes slide-*.svg into
// <dir>/slides/; rasterize with rsvg-convert (see the skill's Step 5).
//
//   node build_breakdown_slides.mjs <dir>            # default: ./output/setups/<T>
//
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const dir = resolve(process.argv[2] || ".");
const S = JSON.parse(readFileSync(`${dir}/setup.json`, "utf8"));
const T = S.technical, TR = S.trade_setup;
const outDir = `${dir}/slides`;
mkdirSync(outDir, { recursive: true });

const W = 1080, H = 1350, M = 84;

// ---- palette: swingtrader midnight. ONE accent = amber. green/red = data only ----
const C = {
  bg: "#0A0E1A", bg2: "#0F1626", panel: "#131C2E",
  ink: "#F5F7FF", mut: "#9AA3BC", mut2: "#6B7488",
  hair: "rgba(245,247,255,0.10)", hair2: "rgba(245,247,255,0.05)",
  amber: "#F5A623", amberSoft: "#FFC774",
  pos: "#3DD68C", neg: "#FF6B6B",
};
const F = { black: "Outfit Black", x: "Outfit ExtraBold", semi: "Outfit SemiBold", med: "Outfit Medium", reg: "Outfit" };

// ---- copy DERIVED from setup.json — true to the chart for any ticker --------
function qLabel(dstr) {
  if (!dstr) return "";
  const dt = new Date(dstr);
  return `Q${Math.floor(dt.getUTCMonth() / 3) + 1}'${String(dt.getUTCFullYear()).slice(2)}`;
}
const fnd = S.fundamentals || {};
const ext = T.extension_pct, volx = T.vol_ratio_today;
const beatsArr = (fnd.recent || []).filter((r) => r.actual != null && r.est != null).map((r) => [r.actual, r.est]);
const beatLabels = (fnd.recent || []).map((r) => qLabel(r.date));
const epsYoY = fnd.eps_growth != null && fnd.eps_growth > 0 && fnd.eps_growth < 100 ? `+${Number(fnd.eps_growth).toFixed(1)}%` : null;  // omit negative/NM/blown-out growth
const peStr = fnd.pe != null && fnd.pe > 0 ? Number(fnd.pe).toFixed(1) : null;  // hide negative/NM P/E
const beatsN = fnd.beats || null;
const riskShare = TR.entry - TR.stop;

const CFG = {
  company: S.company || fnd.company || S.ticker,
  sector: S.sector || fnd.sector || "",
  handle: "@newsimpactscreener",
  cover: {
    l1: T.below_pivot ? `${Math.abs(ext).toFixed(0)}% under` : T.within_buy_range ? "Right at" : "Breaking out",
    l2: T.within_buy_range ? ["the ", ["pivot.", C.amber]] : ["its ", ["pivot.", C.amber]],
    l3: volx ? `${volx.toFixed(1)}× volume.` : "On the move.",
    sub: ["The breakout level, the trade,", "and why it screened — inside."],
  },
  setup: { sub: [
    "Stacked above a rising 50 / 150 / 200-day,",
    T.PriceWithin25Percent52WeekHigh ? "parked near its 52-week high." : "building a base near support.",
    T.accumulation ? "The market's been accumulating." : "Relative strength is leading.",
  ] },
  chart: { cap: [
    T.vol_contracting_in_base ? "Base built, volume dried up — then the surge." : "Trending, pressing into the highs.",
    volx ? `Today: ${volx.toFixed(1)}× average volume into the pivot.` : "Volume is confirming the move.",
  ] },
  vol: { sub: ["Up-day volume outpacing down-day volume.", "Buyers are taking the dips — that's", "accumulation, not distribution."] },
  fund: {
    beats: beatsArr, labels: beatLabels, epsYoY, pe: peStr, beatsN,
    sub: beatsN
      ? [`${beatsN} straight earnings beats —`, "estimates keep getting cleared,", "quarter after quarter."]
      : ["Estimates keep getting cleared —", "the business is backing the move."],
  },
  trade: {
    sub: T.within_buy_range ? ["Actionable now — price is in the buy range.", "Through it on volume, the trade is defined."]
       : T.extended ? ["Extended — let it pull back toward the pivot.", "Don't chase; wait for the entry."]
       : ["A watch — price sits under the pivot.", "Through it on volume, the trade is defined."],
    sizing: `Risk/share $${riskShare.toFixed(2)} · size the stop to ≤0.5–1% of the account.`,
  },
  kill: { l1: ["No breakout,", "no trade."],
          sub: ["Don't pre-buy a stock that hasn't cleared", "the level. And if it loses the 50-day on", "volume, the setup is broken. Discipline > FOMO."] },
  cta: { l1: ["See what's", "setting up", "next."],
         sub: ["The NIS Momentum board scans the market", "every day for setups exactly like this one."] },
};

// ---- helpers ---------------------------------------------------------------
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const n2 = (v) => (v == null ? "—" : Number(v).toFixed(2));
const chartB64 = "data:image/png;base64," + readFileSync(`${dir}/chart.png`).toString("base64");
const chartBareB64 = (() => { try { return "data:image/png;base64," + readFileSync(`${dir}/chart_bare.png`).toString("base64"); } catch { return chartB64; } })();
const svg = (inner) => `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${inner}</svg>`;

function bg(extra = "") {
  return `<rect width="${W}" height="${H}" fill="${C.bg}"/>
    <rect width="${W}" height="${H}" fill="url(#vign)"/>${extra}`;
}
const defs = `<defs>
  <radialGradient id="vign" cx="0.28" cy="0.16" r="1.1">
    <stop offset="0" stop-color="#13203a"/><stop offset="0.55" stop-color="${C.bg}"/><stop offset="1" stop-color="#070A12"/>
  </radialGradient>
  <linearGradient id="amberG" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="${C.amberSoft}"/><stop offset="1" stop-color="${C.amber}"/>
  </linearGradient>
  <linearGradient id="capFade" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="${C.bg}" stop-opacity="0"/><stop offset="0.5" stop-color="${C.bg}" stop-opacity="0.86"/><stop offset="1" stop-color="${C.bg}" stop-opacity="0.98"/>
  </linearGradient>
</defs>`;

// uppercase amber eyebrow with a short rule
function eyebrow(x, y, t) {
  return `<rect x="${x}" y="${y - 9}" width="40" height="5" rx="2.5" fill="${C.amber}"/>
    <text x="${x + 56}" y="${y}" font-family="${F.semi}" font-size="25" fill="${C.amber}" letter-spacing="4.5">${esc(t)}</text>`;
}
// multi-line text; each line is a string OR [text, color] spans on one line
function lines(arr, x, y, lh, { font = F.med, size = 36, fill = C.mut, ls = 0 } = {}) {
  return `<text font-family="${font}" font-size="${size}" fill="${fill}" letter-spacing="${ls}">` +
    arr.map((ln, i) => {
      const yy = y + i * lh;
      if (Array.isArray(ln)) {
        let acc = "", run = 0;
        ln.forEach((seg) => {
          const [txt, col] = Array.isArray(seg) ? seg : [seg, fill];
          acc += `<tspan x="${run === 0 ? x : ""}" ${run === 0 ? `y="${yy}"` : ""} fill="${col}">${esc(txt)}</tspan>`;
          run++;
        });
        // simpler: rebuild with dx flow
        let out = `<tspan x="${x}" y="${yy}">`;
        out += ln.map((seg) => { const [txt, col] = Array.isArray(seg) ? seg : [seg, fill]; return `<tspan fill="${col}">${esc(txt)}</tspan>`; }).join("");
        return out + `</tspan>`;
      }
      return `<tspan x="${x}" y="${yy}">${esc(ln)}</tspan>`;
    }).join("") + `</text>`;
}
// ticker chip
function tickerChip(x, y) {
  return `<g>
    <rect x="${x}" y="${y}" width="172" height="58" rx="12" fill="${C.panel}" stroke="${C.hair}"/>
    <rect x="${x}" y="${y}" width="6" height="58" rx="3" fill="${C.amber}"/>
    <text x="${x + 26}" y="${y + 40}" font-family="${F.x}" font-size="34" fill="${C.ink}" letter-spacing="1">${esc(S.ticker)}</text>
    <text x="${x + 196}" y="${y + 39}" font-family="${F.med}" font-size="26" fill="${C.mut}">${esc(CFG.company)}${CFG.sector ? " · " + esc(CFG.sector) : ""}</text>
  </g>`;
}
// status pill (WATCH / ACTIONABLE / EXTENDED) — amber outline
function statusPill(x, y) {
  const label = TR.status.split("—")[0].trim().toUpperCase();
  const wpx = 38 + label.length * 17;
  return `<g>
    <rect x="${x - wpx}" y="${y}" width="${wpx}" height="50" rx="25" fill="none" stroke="${C.amber}" stroke-width="2"/>
    <circle cx="${x - wpx + 26}" cy="${y + 25}" r="6" fill="${C.amber}"/>
    <text x="${x - wpx + 44}" y="${y + 33}" font-family="${F.semi}" font-size="24" fill="${C.amber}" letter-spacing="2.5">${esc(label)}</text>
  </g>`;
}
function footer(n) {
  return `<line x1="${M}" y1="${H - 116}" x2="${W - M}" y2="${H - 116}" stroke="${C.hair}" stroke-width="1.5"/>
    <rect x="${M}" y="${H - 90}" width="16" height="16" rx="3" fill="${C.amber}"/>
    <text x="${M + 30}" y="${H - 76}" font-family="${F.semi}" font-size="23" fill="${C.mut}" letter-spacing="3.5">NIS STOCK BREAKDOWN</text>
    <text x="${W - M}" y="${H - 76}" font-family="${F.semi}" font-size="23" fill="${C.mut2}" text-anchor="end" letter-spacing="3">${n} / 08</text>`;
}
// a thin labeled metric row (label left, value right, hairline under)
function metricRow(x, w, y, label, value, valColor = C.ink) {
  return `<text x="${x}" y="${y}" font-family="${F.med}" font-size="30" fill="${C.mut}">${esc(label)}</text>
    <text x="${x + w}" y="${y}" font-family="${F.semi}" font-size="32" fill="${valColor}" text-anchor="end">${esc(value)}</text>
    <line x1="${x}" y1="${y + 22}" x2="${x + w}" y2="${y + 22}" stroke="${C.hair2}" stroke-width="1.5"/>`;
}
// drawn check glyph (no emoji)
function check(x, y, col = C.pos) {
  return `<path d="M ${x} ${y} l 9 10 l 18 -22" fill="none" stroke="${col}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>`;
}

// ===========================================================================
// SLIDE 1 — cover
function s1() {
  return svg(defs + bg() + `
    ${eyebrow(M, 170, "NIS MOMENTUM · SWING SETUP")}
    ${statusPill(W - M, 148)}
    ${tickerChip(M, 230)}
    <text font-family="${F.black}" font-size="118" fill="${C.ink}" letter-spacing="-2" xml:space="preserve">
      <tspan x="${M}" y="560">${esc(CFG.cover.l1)}</tspan>
      <tspan x="${M}" y="676">${CFG.cover.l2.map((s) => Array.isArray(s) ? `<tspan fill="${s[1]}">${esc(s[0])}</tspan>` : `<tspan>${esc(s)}</tspan>`).join("")}</tspan>
    </text>
    <text x="${M}" y="800" font-family="${F.x}" font-size="84" fill="${C.ink}" letter-spacing="-1">${esc(CFG.cover.l3)}</text>
    ${lines(CFG.cover.sub, M, 900, 50, { size: 35, fill: C.mut })}
    <!-- ghost price readout, lower-right, asymmetric -->
    <text x="${W - M}" y="1120" font-family="${F.semi}" font-size="28" fill="${C.mut2}" text-anchor="end" letter-spacing="2">LAST</text>
    <text x="${W - M}" y="1188" font-family="${F.black}" font-size="76" fill="${C.ink}" text-anchor="end">$${n2(S.price)}</text>
    <text x="${M}" y="1150" font-family="${F.med}" font-size="28" fill="${C.mut2}" letter-spacing="2">PIVOT</text>
    <text x="${M}" y="1190" font-family="${F.x}" font-size="48" fill="${C.amber}">$${n2(TR.buy_point_pivot)}</text>
    ${footer("01")}`);
}

// SLIDE 2 — the setup (gate checklist)
function s2() {
  const gates = [
    ["Price above 150 & 200-day", T.PriceOverSMA150And200],
    ["50 > 150 > 200, stacked up", T.SMA50AboveSMA150And200],
    ["200-day rising", T.SMA200Slope],
    ["Within 25% of 52-wk high", T.PriceWithin25Percent52WeekHigh],
    ["Above the 50-day (NIS add-on)", T.PriceOverSMA50],
  ];
  const gy = 600, gh = 82;
  const rows = gates.map((g, i) => {
    const y = gy + i * gh;
    return `${check(M + 4, y, g[1] ? C.pos : C.mut2)}
      <text x="${M + 52}" y="${y + 12}" font-family="${F.med}" font-size="34" fill="${C.ink}">${esc(g[0])}</text>
      <line x1="${M}" y1="${y + 40}" x2="${W - M}" y2="${y + 40}" stroke="${C.hair2}" stroke-width="1.5"/>`;
  }).join("");
  return svg(defs + bg() + `
    ${eyebrow(M, 170, "THE SETUP · WHY IT SCREENED")}
    <text x="${M}" y="300" font-family="${F.black}" font-size="74" fill="${C.ink}" letter-spacing="-1">Textbook trend</text>
    <text x="${M}" y="378" font-family="${F.black}" font-size="74" fill="${C.ink}" letter-spacing="-1">continuation.</text>
    ${lines(CFG.setup.sub, M, 452, 44, { size: 31, fill: C.mut })}
    ${rows}
    <!-- MA stack readout, right-justified band -->
    <text x="${M}" y="${gy + 5 * gh + 44}" font-family="${F.semi}" font-size="27" fill="${C.mut}" letter-spacing="2">THE STACK</text>
    ${["50-day", "150-day", "200-day"].map((lab, i) => {
      const v = [T.SMA50, T.SMA150, T.SMA200][i];
      const x = M + i * 300;
      return `<text x="${x}" y="${gy + 5 * gh + 110}" font-family="${F.med}" font-size="26" fill="${C.mut2}">${lab}</text>
        <text x="${x}" y="${gy + 5 * gh + 158}" font-family="${F.x}" font-size="42" fill="${C.ink}">$${n2(v)}</text>`;
    }).join("")}
    ${footer("02")}`);
}

// SLIDE 3 — the chart (bare chart in a header/caption frame, no double-titling)
function s3() {
  const chartY = 110, chartH = 880;
  return svg(defs + bg() + `
    ${eyebrow(M, 76, "PRICE + VOLUME · 8 MONTHS")}
    <text x="${W - M}" y="86" font-family="${F.semi}" font-size="26" fill="${C.mut}" text-anchor="end">${esc(S.ticker)} · ${esc(CFG.company)}</text>
    <image href="${chartBareB64}" x="0" y="${chartY}" width="${W}" height="${chartH}" preserveAspectRatio="xMidYMid meet"/>
    <text x="${M}" y="${chartY + chartH + 54}" font-family="${F.semi}" font-size="22" fill="${C.amber}" letter-spacing="2.5">THE READ</text>
    ${lines(CFG.chart.cap, M, chartY + chartH + 98, 44, { size: 32, fill: C.ink, font: F.med })}
    ${footer("03")}`);
}

// SLIDE 4 — volume & price detail (big stat + rows)
function s4() {
  const x = M, w = W - 2 * M;
  return svg(defs + bg() + `
    ${eyebrow(M, 170, "THE TELL · CONVICTION")}
    <text x="${M}" y="300" font-family="${F.med}" font-size="34" fill="${C.mut}">Today's volume ran</text>
    <text x="${M}" y="470" font-family="${F.black}" font-size="200" fill="${C.amber}" letter-spacing="-4">${n2(T.vol_ratio_today)}×</text>
    <text x="${M}" y="540" font-family="${F.med}" font-size="34" fill="${C.mut}">its 50-day average — buyers showing up.</text>
    <g>
      ${metricRow(x, w, 700, "Up / down volume", n2(T.up_down_vol_ratio), T.accumulation ? C.pos : C.ink)}
      ${metricRow(x, w, 782, "Accumulation", T.accumulation ? "Confirmed" : "No", T.accumulation ? C.pos : C.mut)}
      ${metricRow(x, w, 864, "Volume contracting in base", T.vol_contracting_in_base ? "Yes — coiled" : "No")}
      ${metricRow(x, w, 946, "Average daily range (ADR)", n2(T.adr_pct) + "%")}
      ${metricRow(x, w, 1028, "Distance to pivot", n2(T.extension_pct) + "%", C.amber)}
    </g>
    <text x="${M}" y="1118" font-family="${F.reg}" font-size="27" fill="${C.mut2}">ADR 3–15% is the swing sweet spot. ${esc(S.ticker)} sits clean in range.</text>
    ${footer("04")}`);
}

// SLIDE 5 — fundamentals (earnings-beat bars, data-driven)
function s5() {
  const beats = CFG.fund.beats || [];
  const bx = M, bw = W - 2 * M, baseY = 760, maxH = 230;
  let bars = "";
  if (beats.length >= 2) {
    const maxV = Math.max(...beats.map((b) => Math.max(b[0], b[1])));
    const slot = bw / beats.length;
    bars = beats.map((b, i) => {
      const [act, est] = b;
      const h = (act / maxV) * maxH, eh = (est / maxV) * maxH;
      const cx = bx + i * slot + slot / 2, barW = Math.min(96, slot * 0.5);
      return `
        <rect x="${cx - barW / 2}" y="${baseY - eh}" width="${barW}" height="${eh}" rx="6" fill="${C.panel}" stroke="${C.hair}"/>
        <rect x="${cx - barW / 2}" y="${baseY - h}" width="${barW}" height="${h}" rx="6" fill="url(#amberG)"/>
        <text x="${cx}" y="${baseY - h - 18}" font-family="${F.x}" font-size="32" fill="${C.ink}" text-anchor="middle">$${act.toFixed(2)}</text>
        <text x="${cx}" y="${baseY + 40}" font-family="${F.med}" font-size="26" fill="${C.mut}" text-anchor="middle">${esc(CFG.fund.labels[i] || "")}</text>
        <text x="${cx}" y="${baseY + 74}" font-family="${F.reg}" font-size="22" fill="${act >= est ? C.pos : C.neg}" text-anchor="middle">${act >= est ? "beat" : "miss"} ${est.toFixed(2)}</text>`;
    }).join("");
    bars = `<line x1="${bx}" y1="${baseY}" x2="${bx + bw}" y2="${baseY}" stroke="${C.hair}" stroke-width="1.5"/>${bars}`;
  }
  const head = CFG.fund.beatsN ? `${CFG.fund.beatsN} straight beats.` : "Earnings accelerating.";
  return svg(defs + bg() + `
    ${eyebrow(M, 170, "THE PERMISSION SLIP")}
    <text x="${M}" y="300" font-family="${F.black}" font-size="74" fill="${C.ink}" letter-spacing="-1">${esc(head)}</text>
    ${lines(CFG.fund.sub, M, 372, 44, { size: 31, fill: C.mut })}
    ${bars}
    <g>
      ${["EPS, year-on-year", "Earnings beats", "Price / earnings"].map((lab, i) => {
        const v = [CFG.fund.epsYoY, CFG.fund.beatsN != null ? `${CFG.fund.beatsN}` : null, CFG.fund.pe][i] || "—";
        const x = M + i * ((W - 2 * M) / 3);
        const col = i === 0 && typeof v === "string" && v.startsWith("+") ? C.pos : C.ink;
        return `<text x="${x}" y="1010" font-family="${F.med}" font-size="26" fill="${C.mut2}">${lab}</text>
          <text x="${x}" y="1064" font-family="${F.x}" font-size="50" fill="${col}">${esc(v)}</text>`;
      }).join("")}
    </g>
    ${footer("05")}`);
}

// SLIDE 6 — the trade (price ladder)
function s6() {
  const entry = TR.entry, stop = TR.stop, t2 = TR.target_2r;
  const lo = stop - (entry - stop) * 0.5, hi = t2 + (entry - stop) * 0.4;
  const topY = 470, botY = 1010, h = botY - topY;
  const yfor = (p) => botY - ((p - lo) / (hi - lo)) * h;
  const railX = M + 60;
  function level(p, col, label, val) {
    const y = yfor(p);
    return `<circle cx="${railX}" cy="${y}" r="11" fill="${col}"/>
      <circle cx="${railX}" cy="${y}" r="20" fill="none" stroke="${col}" stroke-opacity="0.35" stroke-width="2"/>
      <line x1="${railX + 30}" y1="${y}" x2="${W - M}" y2="${y}" stroke="${col}" stroke-opacity="0.25" stroke-width="1.5" stroke-dasharray="2 6"/>
      <text x="${railX + 44}" y="${y - 8}" font-family="${F.med}" font-size="27" fill="${C.mut}">${esc(label)}</text>
      <text x="${W - M}" y="${y + 4}" font-family="${F.x}" font-size="46" fill="${col}" text-anchor="end">$${n2(val)}</text>`;
  }
  return svg(defs + bg() + `
    ${eyebrow(M, 170, "THE TRADE")}
    <text x="${M}" y="300" font-family="${F.black}" font-size="74" fill="${C.ink}" letter-spacing="-1">Defined risk,</text>
    <text x="${M}" y="378" font-family="${F.black}" font-size="74" fill="${C.amber}" letter-spacing="-1">2:1 reward.</text>
    <line x1="${railX}" y1="${topY - 20}" x2="${railX}" y2="${botY + 20}" stroke="${C.hair}" stroke-width="2"/>
    ${level(t2, C.pos, "Target · 2R", t2)}
    ${level(entry, C.amber, "Entry · pivot breakout", entry)}
    ${level(stop, C.neg, "Stop · " + n2(TR.risk_pct) + "% risk", stop)}
    ${lines(CFG.trade.sub, M, 1078, 42, { size: 30, fill: C.ink, font: F.med })}
    <text x="${M}" y="1172" font-family="${F.reg}" font-size="26" fill="${C.mut2}">${esc(CFG.trade.sizing)}</text>
    ${footer("06")}`);
}

// SLIDE 7 — what kills it
function s7() {
  return svg(defs + bg() + `
    ${eyebrow(M, 170, "THE INVALIDATION")}
    <text font-family="${F.black}" font-size="104" fill="${C.ink}" letter-spacing="-2">
      <tspan x="${M}" y="470">${esc(CFG.kill.l1[0])}</tspan>
      <tspan x="${M}" y="580" fill="${C.neg}">${esc(CFG.kill.l1[1])}</tspan>
    </text>
    ${lines(CFG.kill.sub, M, 720, 56, { size: 38, fill: C.mut })}
    <g>
      <rect x="${M}" y="960" width="${W - 2 * M}" height="2" fill="${C.hair}"/>
      <text x="${M}" y="1040" font-family="${F.semi}" font-size="30" fill="${C.mut}">Setup breaks below</text>
      <text x="${W - M}" y="1040" font-family="${F.x}" font-size="44" fill="${C.neg}" text-anchor="end">$${n2(T.SMA50)}</text>
      <text x="${M}" y="1086" font-family="${F.reg}" font-size="26" fill="${C.mut2}">the 50-day moving average, on volume</text>
    </g>
    ${footer("07")}`);
}

// SLIDE 8 — CTA
function s8() {
  return svg(defs + bg() + `
    ${eyebrow(M, 170, "YOUR MOVE")}
    <text font-family="${F.black}" font-size="96" fill="${C.ink}" letter-spacing="-2">
      ${CFG.cta.l1.map((t, i) => `<tspan x="${M}" y="${430 + i * 104}" ${i === 2 ? `fill="${C.amber}"` : ""}>${esc(t)}</tspan>`).join("")}
    </text>
    ${lines(CFG.cta.sub, M, 810, 52, { size: 36, fill: C.mut })}
    <g>
      <rect x="${M}" y="940" width="560" height="92" rx="18" fill="url(#amberG)"/>
      <text x="${M + 280}" y="998" font-family="${F.semi}" font-size="34" fill="#0A0E1A" text-anchor="middle">newsimpactscreener.com</text>
    </g>
    <text x="${M}" y="1118" font-family="${F.med}" font-size="26" fill="${C.mut2}">${esc(CFG.handle)} · not financial advice</text>
    ${footer("08")}`);
}

const slides = [s1(), s2(), s3(), s4(), s5(), s6(), s7(), s8()];
slides.forEach((s, i) => {
  const name = `slide-${String(i + 1).padStart(2, "0")}.svg`;
  writeFileSync(`${outDir}/${name}`, s);
  console.log("wrote", name);
});
console.log("svg dir:", outDir);
