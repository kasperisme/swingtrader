import React, {useMemo} from 'react';
import {AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {PriceNewsProps} from '../types';
import {getTheme} from '../theme';
import {Background} from '../components/Background';
import {PriceChart} from '../components/PriceChart';
import {ArticleCard} from '../components/ArticleCard';
import {Footer} from '../components/Footer';
import {clamp, lerp, bump} from '../util/interp';

const dateLabel = (t: string): string => {
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return t;
  return d.toLocaleDateString('en-US', {month: 'short', day: 'numeric', timeZone: 'UTC'});
};

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

  // Event timing: each event's pass-frame is when the line reaches its date.
  const eventsWithIndex = useMemo(
    () => events.map((e, i) => ({e, i, idx: indexForDate(points, e.t)})),
    [events, points],
  );

  // Guarantee an article is on the chart within the first ~3s: ease the line to
  // the FIRST event by ~2.6s (compressing only the empty pre-news lead-in), then
  // draw the news-rich remainder at a steady pace. No event ⇒ plain linear draw.
  const firstIdx = eventsWithIndex.length ? Math.min(...eventsWithIndex.map((x) => x.idx)) : 0;
  const lastF = Math.max(1, mainFrames - 1);
  const introF = Math.min(Math.round(2.6 * fps), Math.floor(lastF * 0.35));
  const firstProg = n > 1 ? firstIdx / (n - 1) : 0;
  const remapped = firstIdx > 0 && firstProg > 0;
  const smooth = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
  const progAt = (f: number): number => {
    if (!remapped) return clamp(f / lastF, 0, 1);
    if (f <= introF) return firstProg * smooth(clamp(f / introF, 0, 1));
    return firstProg + (1 - firstProg) * clamp((f - introF) / Math.max(1, lastF - introF), 0, 1);
  };
  const passFrameFor = (idx: number): number => {
    const tp = n > 1 ? idx / (n - 1) : 0;
    if (!remapped) return tp * lastF;
    if (tp <= firstProg) return introF;
    return introF + ((tp - firstProg) / (1 - firstProg)) * (lastF - introF);
  };

  const progress = progAt(frame);
  const reveal = progress * (n - 1);
  const last = Math.floor(reveal);
  const frac = reveal - last;
  const curClose = lerp(closes[last], closes[Math.min(last + 1, n - 1)], frac);
  const startClose = closes[0];
  const pct = ((curClose - startClose) / startClose) * 100;
  const up = curClose >= startClose;
  const moveColor = up ? theme.positive : theme.negative;
  const curDate = dateLabel(points[Math.round(clamp(reveal, 0, n - 1))].t);

  const holdFrames = Math.min(3.2 * fps, lastF / Math.max(1, events.length));
  let active: {e: (typeof events)[number]; i: number} | null = null;
  let activeOpacity = 0;
  for (const {e, i, idx} of eventsWithIndex) {
    const passFrame = passFrameFor(idx);
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
  const chartHeight = 1000;
  const calloutTop = chartTop + chartHeight + 40;
  const calloutHeight = 172;

  // Catch beat: entrance, then a spotlight pulse on the live price edge ~1.5–3.7s.
  const enter = spring({frame, fps, config: {damping: 200}});
  const spotlight = bump(frame, 1.5 * fps, 2.5 * fps, 3.7 * fps);

  return (
    <AbsoluteFill style={{opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [28, 0])}px)`}}>
      {/* header */}
      <div style={{position: 'absolute', top: 66, left: 56, right: 56, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start'}}>
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
        <div style={{color: theme.text, fontFamily: theme.numberFontFamily, fontWeight: 900, fontSize: 44, fontVariantNumeric: 'tabular-nums', paddingTop: 8}}>
          {curDate}
        </div>
      </div>

      {/* chart */}
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

      {/* event callout (the headline currently being passed) */}
      {active ? (
        <div style={{position: 'absolute', top: calloutTop, left: 56, width: width - 112, opacity: activeOpacity}}>
          <ArticleCard
            title={active.e.title}
            source={active.e.source}
            imageUrl={active.e.imageUrl}
            sentiment={active.e.sentiment ?? 0}
            move={active.e.move}
            theme={theme}
            width={width - 112}
            height={calloutHeight}
          />
        </div>
      ) : null}

      <Footer sources={spec.sources ?? ['News Impact Screener', 'Financial Modeling Prep']} theme={theme} width={width} />
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
