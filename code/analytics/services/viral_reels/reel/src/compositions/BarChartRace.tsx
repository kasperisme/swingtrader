import React, {useMemo} from 'react';
import {AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BarChartRaceProps} from '../types';
import {getTheme} from '../theme';
import {Background} from '../components/Background';
import {RaceBoard} from '../components/RaceBoard';
import {PriceSpark} from '../components/PriceSpark';
import {Captions} from '../components/Caption';
import {Headlines} from '../components/Headlines';
import {Footer} from '../components/Footer';
import {
  prepareKeyframes,
  collectIds,
  labelMap,
  stateAtProgress,
  clamp,
  bump,
} from '../util/interp';

const RaceSection: React.FC<BarChartRaceProps & {raceFrames: number}> = ({spec, raceFrames}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const theme = getTheme(spec.theme);
  const {keyframes, metricLabel, valueFormat, barsVisible} = spec.race;

  const prepared = useMemo(() => prepareKeyframes(keyframes), [keyframes]);
  const allIds = useMemo(() => collectIds(prepared), [prepared]);
  const labels = useMemo(() => labelMap(keyframes), [keyframes]);

  const K = keyframes.length;
  // Natural pace, linear over the race.
  const progressFraction = clamp(frame / Math.max(1, raceFrames - 1), 0, 1);
  const p = progressFraction * (K - 1);

  const states = stateAtProgress(prepared, allIds, labels, p);
  const leader = states.length ? states[0].value : 1;
  const maxValue = leader * 1.08;
  const dateLabel = keyframes[Math.round(clamp(p, 0, K - 1))].label;

  // Catch beat: punchy entrance, then a spotlight pulse on the eventual winner
  // (the bar that ends on top) ~1.5–3.7s in — a moment that grabs the viewer.
  const enter = spring({frame, fps, config: {damping: 200}});
  const spotlight = bump(frame, 1.5 * fps, 2.5 * fps, 3.7 * fps);
  const heroId = useMemo(() => {
    const last = keyframes[keyframes.length - 1].entries;
    return last.reduce((a, b) => (b.value > a.value ? b : a), last[0]).id;
  }, [keyframes]);

  const hasOverlay = spec.overlay && spec.overlay.type === 'priceSpark';
  const sparkTop = 300;
  const sparkHeight = 230;
  const boardTop = hasOverlay ? sparkTop + sparkHeight + 60 : 320;
  // Reserve a bottom band so timed captions never collide with the bars.
  const boardHeight = height - boardTop - 250;

  return (
    <AbsoluteFill style={{opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [28, 0])}px)`}}>
      {/* header */}
      <div style={{position: 'absolute', top: 70, left: 56, right: 56}}>
        <div
          style={{
            color: theme.textMuted,
            fontFamily: theme.fontFamily,
            fontWeight: 800,
            fontSize: 30,
            letterSpacing: 5,
            textTransform: 'uppercase',
          }}
        >
          {metricLabel}
        </div>
        <div
          style={{
            color: theme.text,
            fontFamily: theme.numberFontFamily,
            fontWeight: 900,
            fontSize: 86,
            letterSpacing: -1,
            fontVariantNumeric: 'tabular-nums',
            marginTop: 8,
          }}
        >
          {dateLabel}
        </div>
      </div>

      {hasOverlay ? (
        <div style={{position: 'absolute', top: sparkTop, left: 56, width: width - 112}}>
          <PriceSpark
            overlay={spec.overlay!}
            progress={progressFraction}
            theme={theme}
            width={width - 112}
            height={sparkHeight}
          />
        </div>
      ) : null}

      <div style={{position: 'absolute', top: boardTop, left: 0, width, height: boardHeight}}>
        <RaceBoard
          states={states}
          allIds={allIds}
          maxValue={maxValue}
          barsVisible={barsVisible}
          valueFormat={valueFormat}
          theme={theme}
          width={width}
          height={boardHeight}
          heroId={heroId}
          spotlight={spotlight}
        />
      </div>

      {/* real headlines behind the trend, cycling in the reserved band */}
      {spec.headlines && spec.headlines.length ? (
        <div style={{position: 'absolute', left: 56, right: 56, bottom: 92, height: 156}}>
          <Headlines
            items={spec.headlines}
            theme={theme}
            width={width - 112}
            height={156}
            localFrame={frame}
            spanFrames={raceFrames}
          />
        </div>
      ) : null}

      <Footer sources={spec.sources ?? ['News Impact Screener']} theme={theme} width={width} />
    </AbsoluteFill>
  );
};

export const BarChartRace: React.FC<BarChartRaceProps> = ({spec}) => {
  const {durationInFrames} = useVideoConfig();
  const theme = getTheme(spec.theme);

  // No editorial text slides — the race runs for the full runtime. Hook /
  // takeaway text is added afterwards (Instagram / edits).
  return (
    <AbsoluteFill>
      <Background theme={theme} />

      <Sequence from={0} durationInFrames={durationInFrames}>
        <RaceSection spec={spec} raceFrames={durationInFrames} />
      </Sequence>

      {/* Optional timed narration beats (off by default; headlines take the band). */}
      {spec.captions && spec.captions.length && !(spec.headlines && spec.headlines.length) ? (
        <Captions captions={spec.captions} theme={theme} />
      ) : null}
    </AbsoluteFill>
  );
};
