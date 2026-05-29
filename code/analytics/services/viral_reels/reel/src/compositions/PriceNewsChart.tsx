import React, {useMemo} from 'react';
import {AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {PriceNewsProps} from '../types';
import {getTheme} from '../theme';
import {Background} from '../components/Background';
import {PriceChart} from '../components/PriceChart';
import {ArticleCard} from '../components/ArticleCard';
import {clamp, lerp, bump} from '../util/interp';

const indexForDate = (points: {t: string}[], t: string): number => {
  let best = 0;
  let bestDiff = Infinity;
  const target = new Date(t).getTime();
  points.forEach((p, i) => {
    const diff = Math.abs(new Date(p.t).getTime() - target);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = i;
    }
  });
  return best;
};

const ChartSection: React.FC<PriceNewsProps & {mainFrames: number}> = ({spec, mainFrames}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const theme = getTheme(spec.theme);
  const {points, events, ticker, label, valuePrefix} = spec.chart;

  const closes = points.map((p) => p.close);
  const n = points.length;

  // Each event's pass-frame is when the line reaches its date (linear draw).
  const eventsWithIndex = useMemo(
    () => events.map((e, i) => ({e, i, idx: indexForDate(points, e.t)})),
    [events, points],
  );
  const lastF = Math.max(1, mainFrames - 1);

  const progress = clamp(frame / lastF, 0, 1);
  const reveal = progress * (n - 1);
  const last = Math.floor(reveal);
  const frac = reveal - last;
  const curClose = lerp(closes[last], closes[Math.min(last + 1, n - 1)], frac);
  const startClose = closes[0];
  const pct = ((curClose - startClose) / startClose) * 100;
  const up = curClose >= startClose;
  const moveColor = up ? theme.positive : theme.negative;

  const holdFrames = Math.min(3.2 * fps, lastF / Math.max(1, events.length));
  let active: {e: (typeof events)[number]; i: number} | null = null;
  let activeOpacity = 0;
  for (const {e, i, idx} of eventsWithIndex) {
    const passFrame = (idx / Math.max(1, n - 1)) * lastF;
    if (frame >= passFrame && frame <= passFrame + holdFrames) {
      active = {e, i};
      activeOpacity = interpolate(
        frame,
        [passFrame, passFrame + 8, passFrame + holdFrames - 12, passFrame + holdFrames],
        [0, 1, 1, 0],
        {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
      );
    }
  }

  const chartTop = 300;
  const chartHeight = height - chartTop - 120; // dates live on the chart's x-axis
  const cardHeight = 176;

  // Catch beat: entrance, then a spotlight pulse on the live price edge ~1.5–3.7s.
  const enter = spring({frame, fps, config: {damping: 200}});
  const spotlight = bump(frame, 1.5 * fps, 2.5 * fps, 3.7 * fps);

  return (
    <AbsoluteFill style={{opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [28, 0])}px)`}}>
      {/* header — ticker + live price + % (date now lives on the x-axis) */}
      <div style={{position: 'absolute', top: 66, left: 56, right: 56}}>
        <div style={{transform: `scale(${1 + 0.05 * spotlight})`, transformOrigin: 'left center'}}>
          <div style={{color: theme.textMuted, fontFamily: theme.fontFamily, fontWeight: 800, fontSize: 30, letterSpacing: 5, textTransform: 'uppercase'}}>
            {label || ticker}
          </div>
          <div style={{display: 'flex', alignItems: 'baseline', gap: 18, marginTop: 8}}>
            <div style={{color: theme.text, fontFamily: theme.numberFontFamily, fontWeight: 900, fontSize: 84, letterSpacing: -1, fontVariantNumeric: 'tabular-nums'}}>
              {(valuePrefix ?? '') + curClose.toFixed(2)}
            </div>
            <div style={{color: moveColor, fontFamily: theme.numberFontFamily, fontWeight: 800, fontSize: 40, fontVariantNumeric: 'tabular-nums'}}>
              {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
            </div>
          </div>
        </div>
      </div>

      {/* chart (with date ticks along its x-axis) */}
      <div style={{position: 'absolute', top: chartTop, left: 40, width: width - 80, height: chartHeight}}>
        <PriceChart
          spec={spec.chart}
          progress={progress}
          activeEventIndex={active ? active.i : null}
          pulse={spotlight}
          theme={theme}
          width={width - 80}
          height={chartHeight}
        />
      </div>

      {/* article callout — floats OVER the graph (upper area, usually clear) */}
      {active ? (
        <div style={{position: 'absolute', top: chartTop + 28, left: 56, width: width - 112, opacity: activeOpacity}}>
          <ArticleCard
            title={active.e.title}
            source={active.e.source}
            imageUrl={active.e.imageUrl}
            sentiment={active.e.sentiment ?? 0}
            move={active.e.move}
            theme={theme}
            width={width - 112}
            height={cardHeight}
          />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export const PriceNewsChart: React.FC<PriceNewsProps> = ({spec}) => {
  const {durationInFrames} = useVideoConfig();
  const theme = getTheme(spec.theme);

  // No editorial text slides — the chart draws for the full runtime. Hook /
  // takeaway text is added afterwards (Instagram / edits).
  return (
    <AbsoluteFill>
      <Background theme={theme} />
      <Sequence from={0} durationInFrames={durationInFrames}>
        <ChartSection spec={spec} mainFrames={durationInFrames} />
      </Sequence>
    </AbsoluteFill>
  );
};
