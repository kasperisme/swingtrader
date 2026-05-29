import React from 'react';
import {PriceNewsChartSpec} from '../types';
import {Theme} from '../theme';
import {clamp, lerp} from '../util/interp';

interface Props {
  spec: PriceNewsChartSpec;
  progress: number; // 0..1 line-draw progress
  activeEventIndex: number | null; // pin to emphasize
  pulse?: number; // 0..1 catch-beat glow on the leading edge
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
  theme,
  width,
  height,
}) => {
  const {points, events} = spec;
  if (points.length < 2) return null;

  const closes = points.map((p) => p.close);
  const lows = points.map((p) => (p.low ?? p.close));
  const highs = points.map((p) => (p.high ?? p.close));
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const pad = (max - min) * 0.12 || 1;
  const lo = min - pad;
  const hi = max + pad;

  const innerW = width - PAD_L - PAD_R;
  const innerH = height - PAD_T - PAD_B;
  const baseline = PAD_T + innerH;

  const x = (i: number) => PAD_L + (i / (points.length - 1)) * innerW;
  const y = (v: number) => PAD_T + (1 - (v - lo) / (hi - lo)) * innerH;

  const reveal = clamp(progress, 0, 1) * (points.length - 1);
  const last = Math.floor(reveal);
  const frac = reveal - last;
  const nextIdx = Math.min(last + 1, points.length - 1);
  const curX = lerp(x(last), x(nextIdx), frac);
  const curY = lerp(y(closes[last]), y(closes[nextIdx]), frac);
  const curClose = lerp(closes[last], closes[nextIdx], frac);

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

      {/* horizontal gridlines + price labels */}
      {gridVals.map((v, i) => (
        <g key={i}>
          <line x1={PAD_L} y1={y(v)} x2={width - PAD_R} y2={y(v)} stroke={theme.grid} strokeWidth={1} />
          <text
            x={width - PAD_R}
            y={y(v) - 8}
            textAnchor="end"
            fill={theme.textMuted}
            fontFamily={theme.numberFontFamily}
            fontSize={22}
          >
            {(spec.valuePrefix ?? '') + v.toFixed(0)}
          </text>
        </g>
      ))}

      {/* x-axis date ticks — each fades in as the line draws past its date */}
      {Array.from({length: Math.min(5, points.length)}).map((_, i, arr) => {
        const idx = Math.round((i * (points.length - 1)) / Math.max(1, arr.length - 1));
        const anchor = i === 0 ? 'start' : i === arr.length - 1 ? 'end' : 'middle';
        const tickOpacity = clamp((reveal - idx + 0.5) * 2, 0, 1);
        if (tickOpacity <= 0) return null;
        return (
          <text
            key={i}
            x={x(idx)}
            y={baseline + 46}
            textAnchor={anchor}
            fill={theme.textMuted}
            fillOpacity={tickOpacity}
            fontFamily={theme.numberFontFamily}
            fontSize={24}
          >
            {dateLabel(points[idx].t)}
          </text>
        );
      })}

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
    </svg>
  );
};
