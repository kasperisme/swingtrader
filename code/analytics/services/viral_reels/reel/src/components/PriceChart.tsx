import React from 'react';
import {PriceNewsChartSpec} from '../types';
import {Theme} from '../theme';
import {clamp, lerp} from '../util/interp';

interface Props {
  spec: PriceNewsChartSpec;
  progress: number; // 0..1 line-draw progress
  activeEventIndex: number | null; // pin to emphasize
  pulse?: number; // 0..1 catch-beat glow on the leading edge
  topInset?: number; // reserved headroom at the top (keeps the line below the card)
  rightInset?: number; // reserved strip on the right for the moving price tag
  theme: Theme;
  width: number;
  height: number;
}

const PAD_L = 24;
const PAD_R = 24;
const PAD_T = 16;
const PAD_B = 76; // room for date ticks on the x-axis

const dateLabel = (t: string): string => {
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return t;
  return d.toLocaleDateString('en-US', {month: 'short', day: 'numeric', timeZone: 'UTC'});
};

/** Snap an ISO date to the nearest price-point index. */
const indexForDate = (points: {t: string}[], t: string): number => {
  let best = 0;
  let bestDiff = Infinity;
  const target = new Date(t).getTime();
  points.forEach((p, i) => {
    const d = Math.abs(new Date(p.t).getTime() - target);
    if (d < bestDiff) {
      bestDiff = d;
      best = i;
    }
  });
  return best;
};

export const PriceChart: React.FC<Props> = ({
  spec,
  progress,
  activeEventIndex,
  pulse = 0,
  topInset = 0,
  rightInset = 0,
  theme,
  width,
  height,
}) => {
  const {points, events} = spec;
  if (points.length < 2) return null;

  const closes = points.map((p) => p.close);
  const opens = points.map((p) => (p.open ?? p.close));
  const lows = points.map((p) => (p.low ?? Math.min(p.open ?? p.close, p.close)));
  const highs = points.map((p) => (p.high ?? Math.max(p.open ?? p.close, p.close)));

  const padT = PAD_T + topInset; // headroom so the line's peak stays below the card
  const innerW = width - PAD_L - PAD_R - rightInset; // right strip for the price tag
  const innerH = height - padT - PAD_B;
  const baseline = padT + innerH;

  const reveal = clamp(progress, 0, 1) * (points.length - 1);
  const last = Math.floor(reveal);
  const frac = reveal - last;
  const nextIdx = Math.min(last + 1, points.length - 1);
  const curClose = lerp(closes[last], closes[nextIdx], frac);

  // Both axes grow with the reveal: the y-range is the running min/max over the
  // data revealed so far (incl. the live point), so the viewer can't see the
  // whole range up front — it expands as new highs/lows arrive. A small minimum
  // band keeps the very first points from being wildly amplified.
  // Running min/max over the candles revealed so far (incl. the live point).
  // The leading (in-progress) candle's full low/high is folded in *gradually*
  // via `frac`: at the start of a segment it contributes only `curClose`, and
  // by the time `last` ticks over to the next integer it has reached the real
  // low/high — so the range is a continuous function of `reveal`. Adding a new
  // candle's extent in one step (the old behaviour) is what snapped the y-domain
  // and made the whole graph jump vertically between frames.
  const revLows = lows.slice(0, last + 1);
  const revHighs = highs.slice(0, last + 1);
  let min = Math.min(...revLows, curClose, lerp(curClose, lows[nextIdx], frac));
  let max = Math.max(...revHighs, curClose, lerp(curClose, highs[nextIdx], frac));
  const minSpan = curClose * 0.02;
  if (max - min < minSpan) {
    const mid = (max + min) / 2;
    min = mid - minSpan / 2;
    max = mid + minSpan / 2;
  }
  const pad = (max - min) * 0.12 || 1;
  const lo = min - pad;
  const hi = max + pad;

  // The revealed data always fills the full width: the visible domain is
  // [0, reveal], so the leading edge stays pinned to the right and earlier
  // points compress/shift left as the chart grows.
  const dom = Math.max(reveal, 1e-6);
  const x = (i: number) => PAD_L + (i / dom) * innerW;
  const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * innerH;

  const curX = lerp(x(last), x(nextIdx), frac);
  const curY = y(curClose);

  // Candle width tracks the point spacing (one candle per trading day). As the
  // domain expands the spacing shrinks and candles thin, matching the line
  // chart's "compress left" feel. Clamp so they stay visible but never collide.
  const spacing = innerW / dom;
  const candleW = clamp(spacing * 0.64, 3, 38);

  const up = curClose >= closes[0];
  const lineColor = up ? theme.positive : theme.negative;

  const gridVals = [hi - pad, (hi + lo) / 2, lo + pad];

  return (
    <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
      {/* horizontal gridlines + price labels (left side; the live price rides
          the right strip as a moving tag) */}
      {gridVals.map((v, i) => (
        <g key={i}>
          <line x1={PAD_L} y1={y(v)} x2={PAD_L + innerW} y2={y(v)} stroke={theme.grid} strokeWidth={1} />
          <text
            x={PAD_L + 4}
            y={y(v) - 8}
            textAnchor="start"
            fill={theme.textMuted}
            fontFamily={theme.numberFontFamily}
            fontSize={22}
          >
            {(spec.valuePrefix ?? '') + v.toFixed(0)}
          </text>
        </g>
      ))}

      {/* x-axis date ticks — anchored to data points; they enter at the right
          edge and slide/compress left as the domain expands (no fade). */}
      {(() => {
        const step = Math.max(1, Math.round((points.length - 1) / 5));
        const idxs: number[] = [];
        for (let idx = 0; idx < points.length; idx += step) idxs.push(idx);
        return idxs
          .filter((idx) => idx <= reveal + 1e-6)
          .map((idx) => {
            const px = x(idx);
            const anchor = px <= PAD_L + 20 ? 'start' : px >= PAD_L + innerW - 20 ? 'end' : 'middle';
            return (
              <text
                key={idx}
                x={px}
                y={baseline + 46}
                textAnchor={anchor}
                fill={theme.textMuted}
                fontFamily={theme.numberFontFamily}
                fontSize={24}
              >
                {dateLabel(points[idx].t)}
              </text>
            );
          });
      })()}

      {/* candlesticks — one per revealed trading day. The in-progress (leading)
          candle scales in via `frac` so the reveal stays continuous; fully
          formed candles render at full opacity. */}
      {(() => {
        const candles: React.ReactNode[] = [];
        const draw = (i: number, op: number) => {
          const o = opens[i];
          const c = closes[i];
          const cup = c >= o;
          const col = cup ? theme.positive : theme.negative;
          const cx = x(i);
          const yO = y(o);
          const yC = y(c);
          const bodyTop = Math.min(yO, yC);
          const bodyH = Math.max(2, Math.abs(yC - yO));
          const w = candleW;
          return (
            <g key={i} opacity={op}>
              {/* wick: high → low */}
              <line x1={cx} y1={y(highs[i])} x2={cx} y2={y(lows[i])} stroke={col} strokeWidth={Math.max(1.5, w * 0.16)} />
              {/* body: open → close */}
              <rect x={cx - w / 2} y={bodyTop} width={w} height={bodyH} fill={col} rx={Math.min(3, w * 0.22)} />
            </g>
          );
        };
        for (let i = 0; i <= last; i++) candles.push(draw(i, 1));
        // Leading candle forming on the open segment (only while mid-segment).
        if (frac > 1e-3 && nextIdx > last) candles.push(draw(nextIdx, clamp(frac * 1.4, 0, 1)));
        return candles;
      })()}

      {/* event pins (only once the line has drawn past them) */}
      {events.map((e, i) => {
        const ei = indexForDate(points, e.t);
        if (reveal < ei - 0.001) return null;
        const appear = clamp((reveal - ei) * 4 + 0.0001, 0, 1);
        const px = x(ei);
        const py = y(closes[ei]);
        const sentiment = e.sentiment ?? 0;
        const color = sentiment > 0.05 ? theme.positive : sentiment < -0.05 ? theme.negative : theme.accent;
        const isActive = activeEventIndex === i;
        const r = (isActive ? 16 : 12) * appear;
        return (
          <g key={i}>
            <line
              x1={px}
              y1={py}
              x2={px}
              y2={baseline}
              stroke={color}
              strokeWidth={isActive ? 3 : 1.5}
              strokeDasharray="4 7"
              opacity={0.45 * appear}
            />
            {isActive ? <circle cx={px} cy={py} r={r * 2.1} fill={color} opacity={0.18} /> : null}
            <circle cx={px} cy={py} r={r} fill={color} stroke={theme.bg} strokeWidth={4} />
          </g>
        );
      })}

      {/* leading edge dot (glows during the catch beat) */}
      {pulse > 0.02 ? <circle cx={curX} cy={curY} r={22 + 46 * pulse} fill={lineColor} opacity={0.18 * pulse} /> : null}
      <circle cx={curX} cy={curY} r={12 + 4 * pulse} fill={lineColor} />
      <circle cx={curX} cy={curY} r={22 + 10 * pulse} fill={lineColor} opacity={0.22} />

      {/* live price tag — pinned to the right strip, rides up/down with the line */}
      {rightInset > 0
        ? (() => {
            const pct = ((curClose - closes[0]) / closes[0]) * 100;
            const ticker = spec.label || spec.ticker;
            const pillW = Math.max(120, rightInset - 20);
            const pillH = 138;
            const gap = 16;
            const pillX = curX + gap;
            const pillY = clamp(curY - pillH / 2, padT, baseline - pillH);
            const cx = pillX + pillW / 2;
            const connY = clamp(curY, pillY + 12, pillY + pillH - 12);
            return (
              <g>
                <line x1={curX} y1={curY} x2={pillX} y2={connY} stroke={lineColor} strokeWidth={3} />
                <rect x={pillX} y={pillY} width={pillW} height={pillH} rx={18} fill={lineColor} />
                <text x={cx} y={pillY + 42} textAnchor="middle" fill={theme.bg}
                  fontFamily={theme.fontFamily} fontSize={28} fontWeight={800}
                  letterSpacing={2} opacity={0.85}>
                  {ticker}
                </text>
                <text x={cx} y={pillY + 88} textAnchor="middle" fill={theme.bg}
                  fontFamily={theme.numberFontFamily} fontSize={40} fontWeight={800}>
                  {(spec.valuePrefix ?? '') + curClose.toFixed(2)}
                </text>
                <text x={cx} y={pillY + 122} textAnchor="middle" fill={theme.bg}
                  fontFamily={theme.numberFontFamily} fontSize={27} fontWeight={800}>
                  {(pct >= 0 ? '+' : '') + pct.toFixed(1) + '%'}
                </text>
              </g>
            );
          })()
        : null}
    </svg>
  );
};
