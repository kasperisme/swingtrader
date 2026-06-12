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

// Piecewise-linear lookups over a variable-speed draw schedule (sorted by t).
// `idxAtSecond` drives the live draw; `secondAtIdx` (its inverse) tells us when
// a given candle is reached, so an event's card appears exactly on schedule.
const idxAtSecond = (kf: {t: number; idx: number}[], sec: number): number => {
  if (sec <= kf[0].t) return kf[0].idx;
  const last = kf[kf.length - 1];
  if (sec >= last.t) return last.idx;
  for (let i = 1; i < kf.length; i++) {
    if (sec <= kf[i].t) {
      const a = kf[i - 1];
      const b = kf[i];
      const f = (sec - a.t) / Math.max(1e-6, b.t - a.t);
      return a.idx + f * (b.idx - a.idx);
    }
  }
  return last.idx;
};

const secondAtIdx = (kf: {t: number; idx: number}[], idx: number): number => {
  if (idx <= kf[0].idx) return kf[0].t;
  const last = kf[kf.length - 1];
  if (idx >= last.idx) return last.t;
  for (let i = 1; i < kf.length; i++) {
    if (idx <= kf[i].idx) {
      const a = kf[i - 1];
      const b = kf[i];
      const f = (idx - a.idx) / Math.max(1e-6, b.idx - a.idx);
      return a.t + f * (b.t - a.t);
    }
  }
  return last.t;
};

const ChartSection: React.FC<PriceNewsProps & {mainFrames: number}> = ({spec, mainFrames}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const theme = getTheme(spec.theme);
  const {points, events} = spec.chart;
  const keyframes = spec.chart.keyframes;
  const n = points.length;

  // Each event's pass-frame is when the line reaches its date (linear draw).
  const eventsWithIndex = useMemo(
    () => events.map((e, i) => ({e, i, idx: indexForDate(points, e.t)})),
    [events, points],
  );
  const lastF = Math.max(1, mainFrames - 1);
  // Reserve a tail hold so the final event's card (usually the climax) gets
  // screen time: an event on the last point would otherwise land on the very
  // last frame and never be seen. The line finishes drawing at `drawF`, then
  // the chart holds on the final point for the remaining frames.
  const holdFrames = events.length ? Math.round(2.2 * fps) : 0;
  const drawF = Math.max(1, lastF - holdFrames);

  // With a keyframe schedule (dialog-reel), draw at a variable speed so each
  // candle is reached at its scheduled second; otherwise draw linearly.
  const hasSchedule = !!(keyframes && keyframes.length >= 2);
  const progress = hasSchedule
    ? clamp(idxAtSecond(keyframes!, frame / fps) / Math.max(1, n - 1), 0, 1)
    : clamp(frame / drawF, 0, 1);

  // A card appears when the line reaches its date and then STAYS — the next
  // event's card animates in on top of it. Cards are opaque, so the newest
  // fully covers the prior (which peeks out behind it). No fade-outs, so an
  // article is always on screen once the first one has landed.
  const passed = eventsWithIndex
    .map(({e, i, idx}) => ({
      e,
      i,
      passFrame: hasSchedule
        ? secondAtIdx(keyframes!, idx) * fps
        : (idx / Math.max(1, n - 1)) * drawF,
    }))
    .filter((x) => frame >= x.passFrame - 1e-3)
    .sort((a, b) => a.passFrame - b.passFrame);
  const current = passed.length ? passed[passed.length - 1] : null;
  const beneath = passed.length > 1 ? passed[passed.length - 2] : null;

  const FADE = 12; // frames for the incoming card to settle on top
  const tIn = current ? clamp((frame - current.passFrame) / FADE, 0, 1) : 0;

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
          activeEventIndex={current ? current.i : null}
          pulse={spotlight}
          topInset={events.length ? cardTopOffset + cardHeight + 16 : 0}
          rightInset={200}
          theme={theme}
          width={width - 80}
          height={chartHeight}
        />
      </div>

      {/* article callouts — float OVER the graph (upper area). The previous
          card stays put, offset behind; the current one settles on top of it,
          so headlines stack rather than blink in and out. */}
      {beneath ? (
        <div style={{position: 'absolute', top: chartTop + cardTopOffset + 14, left: 44 + 14, width: width - 88}}>
          <ArticleCard
            title={beneath.e.title}
            source={beneath.e.source}
            imageUrl={beneath.e.imageUrl}
            sentiment={beneath.e.sentiment ?? 0}
            move={beneath.e.move}
            theme={theme}
            width={width - 88}
            height={cardHeight}
          />
        </div>
      ) : null}
      {current ? (
        <div
          style={{
            position: 'absolute',
            top: chartTop + cardTopOffset,
            left: 44,
            width: width - 88,
            opacity: tIn,
            transform: `translateY(${interpolate(tIn, [0, 1], [-16, 0])}px)`,
          }}
        >
          <ArticleCard
            title={current.e.title}
            source={current.e.source}
            imageUrl={current.e.imageUrl}
            sentiment={current.e.sentiment ?? 0}
            move={current.e.move}
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
