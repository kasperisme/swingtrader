import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Theme} from '../theme';
import {IntroSpec} from '../types';

/**
 * The hook as an on-reel text caption (replaces the old full-screen hero slide).
 * Overlays the upper area while the chart/race runs underneath from frame 0,
 * then fades out so the animation gets the full runtime. `durationInSeconds`
 * controls how long it holds before fading.
 */
export const TitleCaption: React.FC<{intro: IntroSpec; theme: Theme}> = ({intro, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const hold = Math.round((intro.durationInSeconds ?? 2.5) * fps);
  const fadeOut = 22;
  if (frame > hold + fadeOut) return null;

  const enter = spring({frame, fps, config: {damping: 200}});
  const y = interpolate(enter, [0, 1], [40, 0]);
  const opacity =
    enter *
    interpolate(frame, [hold, hold + fadeOut], [1, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });

  const shadow = '0 4px 26px rgba(0,0,0,0.65)';

  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      {/* scrim to mask whatever is animating behind the caption */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: '20%',
          height: '36%',
          opacity,
          background: `linear-gradient(180deg, transparent, ${theme.bg}F2 22%, ${theme.bg}F2 78%, transparent)`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 56,
          right: 56,
          top: '27%',
          transform: `translateY(${y}px)`,
          opacity,
        }}
      >
        {intro.kicker ? (
          <div
            style={{
              color: theme.accent,
              fontFamily: theme.fontFamily,
              fontWeight: 800,
              fontSize: 30,
              letterSpacing: 5,
              textTransform: 'uppercase',
              marginBottom: 18,
              textShadow: shadow,
            }}
          >
            {intro.kicker}
          </div>
        ) : null}
        <div
          style={{
            color: theme.text,
            fontFamily: theme.fontFamily,
            fontWeight: 900,
            fontSize: 78,
            lineHeight: 1.04,
            letterSpacing: -1.5,
            textShadow: shadow,
          }}
        >
          {intro.title}
        </div>
        {intro.subtitle ? (
          <div
            style={{
              color: theme.text,
              fontFamily: theme.fontFamily,
              fontWeight: 600,
              fontSize: 34,
              marginTop: 20,
              opacity: 0.88,
              textShadow: shadow,
            }}
          >
            {intro.subtitle}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
