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
  const lows = points.map((p) => (p.low ?? p.close));
  const highs = points.map((p) => (p.high ?? p.close));

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
  const revLows = lows.slice(0, last + 1).concat(curClose);
  const revHighs = highs.slice(0, last + 1).concat(curClose);
  let min = Math.min(...revLows);
  let max = Math.max(...revHighs);
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

  let line = `M ${x(0)} ${y(closes[0])}`;
  for (let i = 1; i <= last; i++) line += ` L ${x(i)} ${y(closes[i])}`;
  line += ` L ${curX} ${curY}`;
  const area = `${line} L ${curX} ${baseline} L ${x(0)} ${baseline} Z`;

  const up = curClose >= closes[0];
  const lineColor = up ? theme.positive : theme.negative;

  const gridVals = [hi - pad, (hi + lo) / 2, lo + pad];

  return (
    <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
      <defs>
        <linearGradient id="priceArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity={0.35} />
          <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
        </linearGradient>
      </defs>

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

      {/* area + line */}
      <path d={area} fill="url(#priceArea)" />
      <path d={line} fill="none" stroke={lineColor} strokeWidth={6} strokeLinejoin="round" strokeLinecap="round" />

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
