import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Theme} from '../theme';
import {IntroSpec} from '../types';

export const TitleCard: React.FC<{intro: IntroSpec; theme: Theme}> = ({intro, theme}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  const enter = spring({frame, fps, config: {damping: 200}});
  const y = interpolate(enter, [0, 1], [60, 0]);
  // ease out near the end of the intro to hand off to the race
  const exit = interpolate(frame, [durationInFrames - 12, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'flex-start',
        padding: '0 90px',
        opacity: enter * exit,
        transform: `translateY(${y}px)`,
      }}
    >
      {intro.kicker ? (
        <div
          style={{
            color: theme.positive,
            fontFamily: theme.fontFamily,
            fontWeight: 800,
            fontSize: 34,
            letterSpacing: 6,
            textTransform: 'uppercase',
            marginBottom: 28,
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
          fontSize: 96,
          lineHeight: 1.02,
          letterSpacing: -2,
        }}
      >
        {intro.title}
      </div>
      {intro.subtitle ? (
        <div
          style={{
            color: theme.textMuted,
            fontFamily: theme.fontFamily,
            fontWeight: 600,
            fontSize: 40,
            marginTop: 32,
          }}
        >
          {intro.subtitle}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
