import React from 'react';
import {Theme} from '../theme';
import {PriceSparkOverlay} from '../types';
import {clamp, lerp} from '../util/interp';
import {formatPrice} from '../util/format';

interface Props {
  overlay: PriceSparkOverlay;
  progress: number; // 0..1 across the race
  theme: Theme;
  width: number;
  height: number;
}

/**
 * External-source overlay: the highlighted ticker's price line drawn in sync
 * with the race timeline, so the "why" (price reaction) reveals alongside the
 * news-flow race.
 */
export const PriceSpark: React.FC<Props> = ({overlay, progress, theme, width, height}) => {
  const pts = overlay.points;
  if (pts.length < 2) return null;

  const padding = 24;
  const chartW = width - padding * 2;
  const chartH = height - 64 - padding;
  const closes = pts.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;

  const x = (i: number) => padding + (i / (pts.length - 1)) * chartW;
  const y = (v: number) => 64 + (1 - (v - min) / span) * chartH;

  const reveal = clamp(progress, 0, 1) * (pts.length - 1);
  const lastIdx = Math.floor(reveal);
  const frac = reveal - lastIdx;
  const curClose = lerp(closes[lastIdx], closes[Math.min(lastIdx + 1, pts.length - 1)], frac);
  const curX = lerp(x(lastIdx), x(Math.min(lastIdx + 1, pts.length - 1)), frac);
  const curY = lerp(y(closes[lastIdx]), y(closes[Math.min(lastIdx + 1, pts.length - 1)]), frac);

  let d = `M ${x(0)} ${y(closes[0])}`;
  for (let i = 1; i <= lastIdx; i++) d += ` L ${x(i)} ${y(closes[i])}`;
  d += ` L ${curX} ${curY}`;

  const up = curClose >= closes[0];
  const stroke = up ? theme.positive : theme.negative;

  return (
    <div
      style={{
        width,
        height,
        background: theme.trackBg,
        borderRadius: 22,
        border: `1px solid ${theme.grid}`,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 18,
          left: 24,
          color: theme.textMuted,
          fontFamily: theme.fontFamily,
          fontWeight: 700,
          fontSize: 26,
          letterSpacing: 1,
        }}
      >
        {overlay.label.toUpperCase()}
      </div>
      <div
        style={{
          position: 'absolute',
          top: 14,
          right: 24,
          color: theme.text,
          fontFamily: theme.numberFontFamily,
          fontWeight: 800,
          fontSize: 34,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {formatPrice(curClose)}
      </div>
      <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
        <path d={d} fill="none" stroke={stroke} strokeWidth={5} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={curX} cy={curY} r={9} fill={stroke} />
        <circle cx={curX} cy={curY} r={16} fill={stroke} opacity={0.25} />
      </svg>
    </div>
  );
};
