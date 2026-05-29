import React, {useMemo} from 'react';
import {AbsoluteFill, Sequence, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {PriceNewsProps} from '../types';
import {getTheme} from '../theme';
import {Background} from '../components/Background';
import {TitleCard} from '../components/TitleCard';
import {OutroCard} from '../components/OutroCard';
import {PriceChart} from '../components/PriceChart';
import {EventCallout} from '../components/EventCallout';
import {Footer} from '../components/Footer';
import {clamp, lerp} from '../util/interp';

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
  const progress = clamp(frame / Math.max(1, mainFrames - 1), 0, 1);
  const reveal = progress * (n - 1);
  const last = Math.floor(reveal);
  const frac = reveal - last;
  const curClose = lerp(closes[last], closes[Math.min(last + 1, n - 1)], frac);
  const startClose = closes[0];
  const pct = ((curClose - startClose) / startClose) * 100;
  const up = curClose >= startClose;
  const moveColor = up ? theme.positive : theme.negative;
  const curDate = dateLabel(points[Math.round(clamp(reveal, 0, n - 1))].t);

  // Event timing: each event's pass-frame is when the line reaches its date.
  const eventsWithIndex = useMemo(
    () => events.map((e, i) => ({e, i, idx: indexForDate(points, e.t)})),
    [events, points],
  );
  const holdFrames = Math.min(3.2 * fps, mainFrames / Math.max(1, events.length));
  let active: {e: (typeof events)[number]; i: number} | null = null;
  let activeOpacity = 0;
  for (const {e, i, idx} of eventsWithIndex) {
    const passFrame = (idx / (n - 1)) * (mainFrames - 1);
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

  return (
    <AbsoluteFill>
      {/* header */}
      <div style={{position: 'absolute', top: 66, left: 56, right: 56, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start'}}>
        <div>
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
          theme={theme}
          width={width - 80}
          height={chartHeight}
        />
      </div>

      {/* event callout (the headline currently being passed) */}
      {active ? (
        <div style={{position: 'absolute', top: calloutTop, left: 56, width: width - 112, opacity: activeOpacity}}>
          <EventCallout event={active.e} theme={theme} width={width - 112} height={calloutHeight} />
        </div>
      ) : null}

      <Footer sources={spec.sources ?? ['News Impact Screener', 'Financial Modeling Prep']} theme={theme} width={width} />
    </AbsoluteFill>
  );
};

export const PriceNewsChart: React.FC<PriceNewsProps> = ({spec}) => {
  const {fps, durationInFrames} = useVideoConfig();
  const theme = getTheme(spec.theme);

  const introF = spec.intro ? Math.round(spec.intro.durationInSeconds * fps) : 0;
  const outroF = spec.outro ? Math.round(spec.outro.durationInSeconds * fps) : 0;
  const mainF = Math.max(1, durationInFrames - introF - outroF);

  return (
    <AbsoluteFill>
      <Background theme={theme} />

      {spec.intro ? (
        <Sequence from={0} durationInFrames={introF}>
          <TitleCard intro={spec.intro} theme={theme} />
        </Sequence>
      ) : null}

      <Sequence from={introF} durationInFrames={mainF}>
        <ChartSection spec={spec} mainFrames={mainF} />
      </Sequence>

      {spec.outro ? (
        <Sequence from={introF + mainF} durationInFrames={outroF}>
          <OutroCard outro={spec.outro} theme={theme} />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};
