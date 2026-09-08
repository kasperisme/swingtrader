import React, {useMemo} from 'react';
import {AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {ArenaRaceProps, ArenaAgent, Keyframe} from '../types';
import {getTheme} from '../theme';
import {Background} from '../components/Background';
import {Captions} from '../components/Caption';
import {ArenaRaceBoard} from '../components/ArenaRaceBoard';
import {
  ClubChip,
  FooterBlock,
  HeaderBlock,
  Strap,
  fmtPct,
  toneFor,
} from '../components/ArenaBits';
import {bump, clamp, collectIds, labelMap, prepareKeyframes, stateAtProgress} from '../util/interp';

/** Seconds of the runtime given to each act. The race gets whatever is left. */
const INTRO_S = 2.2;
// Kept in step with OUTRO_S in services/arena_creatives/commentary.py — the
// commentary places its closing beat from these constants, so a change here
// that is not mirrored there puts the result line over the wrong picture.
const OUTRO_S = 5.0;

const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/**
 * Ease WITHIN each session step instead of sliding linearly across it.
 *
 * A season is ~47 sessions inside ~16 seconds, so a linear playhead is
 * permanently mid-transition: rank is lerped between two keyframes, and with
 * nine agents swapping most days, any given frame catches two or three rows
 * stacked on top of each other at the same y. Easing the fraction makes rows
 * settle at whole ranks and cross quickly — which is both readable and how an
 * overtake actually feels.
 */
const settleProgress = (p: number): number => {
  const i = Math.floor(p);
  return i + easeInOutCubic(p - i);
};

/* ── Act 1: the title card ────────────────────────────────────────────────── */

const Intro: React.FC<ArenaRaceProps> = ({spec}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const theme = getTheme(spec.theme);
  const scale = width / 1080;
  const enter = spring({frame, fps, config: {damping: 200}});

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        padding: 90 * scale,
        opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [30, 0])}px)`,
      }}
    >
      <HeaderBlock header={spec.header} theme={theme} scale={scale * 1.35} />
      {spec.hook ? (
        <div style={{marginTop: 54 * scale}}>
          <Strap text={spec.hook} theme={theme} scale={scale * 1.15} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/* ── Act 2: the race ──────────────────────────────────────────────────────── */

/** Bottom reserve under the board: the footer alone, or the footer plus the
 *  caption band when the reel is captioned. Without the larger reserve a
 *  two-line caption sits on top of the ninth row — and the bottom of this table
 *  is the half people came to read. */
const BOTTOM_RESERVE = 300;
const BOTTOM_RESERVE_CAPTIONED = 480;

const Race: React.FC<ArenaRaceProps & {raceFrames: number}> = ({spec, raceFrames}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const theme = getTheme(spec.theme);
  const scale = width / 1080;

  const agents = useMemo(
    () => new Map<string, ArenaAgent>(spec.agents.map((a) => [a.slug, a])),
    [spec.agents],
  );

  // The interpolation helpers take the reel Keyframe shape (entries carry a
  // label). Arena keyframes carry only ids — the display name lives on the
  // agent, not repeated on every session — so the label is filled in here.
  const keyframes = useMemo<Keyframe[]>(
    () =>
      spec.keyframes.map((kf) => ({
        t: kf.t,
        label: kf.label,
        entries: kf.entries.map((e) => ({
          id: e.id,
          label: agents.get(e.id)?.name ?? e.id,
          value: e.value,
        })),
      })),
    [spec.keyframes, agents],
  );

  const prepared = useMemo(() => prepareKeyframes(keyframes), [keyframes]);
  const allIds = useMemo(() => collectIds(prepared), [prepared]);
  const labels = useMemo(() => labelMap(keyframes), [keyframes]);

  // Fixed axis across the whole race, with a little headroom so the leading bar
  // never touches the value column.
  const [axisMin, axisMax] = useMemo(() => {
    let lo = 0;
    let hi = 0;
    for (const kf of spec.keyframes) {
      for (const e of kf.entries) {
        lo = Math.min(lo, e.value);
        hi = Math.max(hi, e.value);
      }
    }
    const padding = Math.max(0.004, (hi - lo) * 0.08);
    return [lo - padding, hi + padding];
  }, [spec.keyframes]);

  const K = keyframes.length;
  const rawP = clamp(frame / Math.max(1, raceFrames - 1), 0, 1) * (K - 1);
  const p = settleProgress(rawP);
  const states = stateAtProgress(prepared, allIds, labels, p);
  const dateLabel = keyframes[Math.round(clamp(p, 0, K - 1))].label;
  const session = Math.round(clamp(p, 0, K - 1)) + 1;

  const spotlight = bump(frame, 1.0 * fps, 2.0 * fps, 3.4 * fps);
  const enter = spring({frame, fps, config: {damping: 200}});

  const pad = 56 * scale;
  const headTop = 74 * scale;
  const boardTop = 300 * scale;
  const reserve = spec.captions && spec.captions.length ? BOTTOM_RESERVE_CAPTIONED : BOTTOM_RESERVE;
  const boardH = height - boardTop - reserve * scale;

  return (
    <AbsoluteFill style={{opacity: enter}}>
      {/* the score bug: metric on the left, the session clock on the right */}
      <div
        style={{
          position: 'absolute',
          top: headTop,
          left: pad,
          right: pad,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
        }}
      >
        <div>
          <div
            style={{
              color: theme.accent,
              fontFamily: theme.numberFontFamily,
              fontWeight: 700,
              fontSize: 24 * scale,
              letterSpacing: 5 * scale,
              textTransform: 'uppercase',
            }}
          >
            {spec.header.kicker}
          </div>
          <div
            style={{
              color: theme.text,
              fontFamily: theme.fontFamily,
              fontWeight: 900,
              fontSize: 62 * scale,
              letterSpacing: -1.5 * scale,
              marginTop: 10 * scale,
            }}
          >
            {spec.metricLabel} since day one
          </div>
        </div>
        <div style={{textAlign: 'right'}}>
          <div
            style={{
              color: theme.textMuted,
              fontFamily: theme.numberFontFamily,
              fontSize: 20 * scale,
              letterSpacing: 3 * scale,
            }}
          >
            MATCHDAY
          </div>
          <div
            style={{
              color: theme.text,
              fontFamily: theme.numberFontFamily,
              fontWeight: 900,
              fontSize: 58 * scale,
              fontVariantNumeric: 'tabular-nums',
              lineHeight: 1.05,
            }}
          >
            {session}
          </div>
          <div
            style={{
              color: theme.textMuted,
              fontFamily: theme.numberFontFamily,
              fontSize: 26 * scale,
              marginTop: 4 * scale,
            }}
          >
            {dateLabel}
          </div>
        </div>
      </div>

      <div style={{position: 'absolute', top: boardTop, left: pad, width: width - pad * 2, height: boardH}}>
        <ArenaRaceBoard
          states={states}
          agents={agents}
          axisMin={axisMin}
          axisMax={axisMax}
          theme={theme}
          width={width - pad * 2}
          height={boardH}
          scale={scale}
          spotlight={spotlight}
        />
      </div>

      <div style={{position: 'absolute', left: pad, right: pad, bottom: 54 * scale}}>
        <FooterBlock footer={spec.footer} theme={theme} scale={scale} />
      </div>
    </AbsoluteFill>
  );
};

/* ── Act 3: the result ────────────────────────────────────────────────────── */

const Outro: React.FC<ArenaRaceProps> = ({spec}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const theme = getTheme(spec.theme);
  const scale = width / 1080;
  const enter = spring({frame, fps, config: {damping: 200}});

  // The whole result, not a podium and an ellipsis. A results round-up that
  // hides two thirds of the table sends the viewer looking for the rest
  // somewhere other than the page we are pointing them at — and the bottom of
  // this particular table is the most interesting part of it.
  const podium = spec.finalRows.slice(0, 3);
  const rest = spec.finalRows.slice(3);

  return (
    <AbsoluteFill style={{padding: 74 * scale, justifyContent: 'center', opacity: enter}}>
      {spec.hook ? <Strap text={spec.hook} theme={theme} scale={scale * 1.25} reveal={enter} /> : null}

      <div style={{marginTop: 44 * scale}}>
        {podium.map((r, i) => (
          <div
            key={r.slug}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 22 * scale,
              padding: `${22 * scale}px 0`,
              borderBottom: `1px solid ${theme.grid}`,
              transform: `translateX(${interpolate(enter, [0, 1], [-24 - i * 12, 0])}px)`,
            }}
          >
            <div
              style={{
                width: 52 * scale,
                color: theme.textMuted,
                fontFamily: theme.numberFontFamily,
                fontWeight: 900,
                fontSize: 54 * scale,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {r.rank}
            </div>
            <ClubChip row={r} size={30 * scale} theme={theme} />
            <div
              style={{
                flex: 1,
                color: theme.text,
                fontFamily: theme.fontFamily,
                fontWeight: 800,
                fontSize: 46 * scale,
                whiteSpace: 'nowrap',
              }}
            >
              {r.name}
            </div>
            <div
              style={{
                color: toneFor(r.return, theme),
                fontFamily: theme.numberFontFamily,
                fontWeight: 800,
                fontSize: 50 * scale,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {fmtPct(r.return)}
            </div>
          </div>
        ))}

        {rest.map((r) => (
          <div
            key={r.slug}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 18 * scale,
              padding: `${11 * scale}px 0`,
              opacity: 0.72,
            }}
          >
            <div
              style={{
                width: 52 * scale,
                color: theme.textMuted,
                fontFamily: theme.numberFontFamily,
                fontWeight: 700,
                fontSize: 28 * scale,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {r.rank}
            </div>
            <ClubChip row={r} size={19 * scale} theme={theme} />
            <div
              style={{
                flex: 1,
                color: theme.text,
                fontFamily: theme.fontFamily,
                fontWeight: 600,
                fontSize: 30 * scale,
                whiteSpace: 'nowrap',
              }}
            >
              {r.name}
            </div>
            <div
              style={{
                color: toneFor(r.return, theme),
                fontFamily: theme.numberFontFamily,
                fontWeight: 700,
                fontSize: 30 * scale,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {fmtPct(r.return)}
            </div>
          </div>
        ))}
      </div>

      {spec.outro?.takeaway ? (
        <div
          style={{
            marginTop: 40 * scale,
            color: theme.textMuted,
            fontFamily: theme.fontFamily,
            fontSize: 31 * scale,
            lineHeight: 1.35,
          }}
        >
          {spec.outro.takeaway}
        </div>
      ) : null}

      <div
        style={{
          marginTop: 40 * scale,
          color: theme.accent,
          fontFamily: theme.fontFamily,
          fontWeight: 900,
          fontSize: 48 * scale,
        }}
      >
        {spec.outro?.cta ?? spec.footer.cta}
      </div>
      <div
        style={{
          marginTop: 16 * scale,
          color: theme.textMuted,
          fontFamily: theme.numberFontFamily,
          fontSize: 23 * scale,
        }}
      >
        {spec.footer.disclaimer}
      </div>
    </AbsoluteFill>
  );
};

/* ── The reel ─────────────────────────────────────────────────────────────── */

export const ArenaRace: React.FC<ArenaRaceProps> = ({spec}) => {
  const {durationInFrames, fps} = useVideoConfig();
  const theme = getTheme(spec.theme);

  const introF = Math.round(INTRO_S * fps);
  const outroF = Math.round(OUTRO_S * fps);
  const raceF = Math.max(fps, durationInFrames - introF - outroF);

  return (
    <AbsoluteFill>
      <Background theme={theme} />
      <Sequence from={0} durationInFrames={introF}>
        <Intro spec={spec} />
      </Sequence>
      <Sequence from={introF} durationInFrames={raceF}>
        <Race spec={spec} raceFrames={raceF} />
      </Sequence>
      <Sequence from={introF + raceF} durationInFrames={outroF}>
        <Outro spec={spec} />
      </Sequence>
      {/* Commentary, burned in. Most social video is watched muted, so the
          voice-over beats are also captions — same beats, same seconds. They
          sit in the band the race act reserves between the board and the
          footer, which is why they do not use the default caption position. */}
      {spec.captions && spec.captions.length ? (
        <Captions captions={spec.captions} theme={theme} bottom={185} />
      ) : null}
    </AbsoluteFill>
  );
};
