import React, {useMemo} from 'react';
import {AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {PriceNewsProps} from '../types';
import {getTheme} from '../theme';
import {Background} from '../components/Background';
import {PriceChart} from '../components/PriceChart';
import {ArticleCard} from '../components/ArticleCard';
import {clamp, bump} from '../util/interp';

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
  const {points, events} = spec.chart;
  const n = points.length;

  // Each event's pass-frame is when the line reaches its date (linear draw).
  const eventsWithIndex = useMemo(
    () => events.map((e, i) => ({e, i, idx: indexForDate(points, e.t)})),
    [events, points],
  );
  const lastF = Math.max(1, mainFrames - 1);
  const progress = clamp(frame / lastF, 0, 1);

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

  // No top header — the ticker now lives in the price tag, freeing space for a
  // taller chart and a bigger article card.
  const chartTop = 120;
  const chartHeight = height - chartTop - 120; // dates live on the chart's x-axis
  const cardHeight = 250;
  const cardTopOffset = 24;

  // Catch beat: entrance, then a spotlight pulse on the live price edge ~1.5–3.7s.
  const enter = spring({frame, fps, config: {damping: 200}});
  const spotlight = bump(frame, 1.5 * fps, 2.5 * fps, 3.7 * fps);

  return (
    <AbsoluteFill style={{opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [28, 0])}px)`}}>
      {/* chart (date ticks on the x-axis, live price+ticker tag on the right) */}
      <div style={{position: 'absolute', top: chartTop, left: 40, width: width - 80, height: chartHeight}}>
        <PriceChart
          spec={spec.chart}
          progress={progress}
          activeEventIndex={active ? active.i : null}
          pulse={spotlight}
          topInset={events.length ? cardTopOffset + cardHeight + 16 : 0}
          rightInset={200}
          theme={theme}
          width={width - 80}
          height={chartHeight}
        />
      </div>

      {/* article callout — floats OVER the graph (bigger, upper area) */}
      {active ? (
        <div style={{position: 'absolute', top: chartTop + cardTopOffset, left: 44, width: width - 88, opacity: activeOpacity}}>
          <ArticleCard
            title={active.e.title}
            source={active.e.source}
            imageUrl={active.e.imageUrl}
            sentiment={active.e.sentiment ?? 0}
            move={active.e.move}
            theme={theme}
            width={width - 88}
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
