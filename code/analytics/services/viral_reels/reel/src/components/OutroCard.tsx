import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Theme} from '../theme';
import {OutroSpec} from '../types';

export const OutroCard: React.FC<{outro: OutroSpec; theme: Theme}> = ({outro, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 200}});
  const y = interpolate(enter, [0, 1], [50, 0]);

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'flex-start',
        padding: '0 90px',
        opacity: enter,
        transform: `translateY(${y}px)`,
      }}
    >
      <div
        style={{
          width: 120,
          height: 10,
          borderRadius: 6,
          background: theme.positive,
          marginBottom: 44,
        }}
      />
      <div
        style={{
          color: theme.text,
          fontFamily: theme.fontFamily,
          fontWeight: 900,
          fontSize: 88,
          lineHeight: 1.04,
          letterSpacing: -2,
        }}
      >
        {outro.title}
      </div>
      {outro.takeaway ? (
        <div
          style={{
            color: theme.textMuted,
            fontFamily: theme.fontFamily,
            fontWeight: 600,
            fontSize: 42,
            marginTop: 32,
            lineHeight: 1.25,
          }}
        >
          {outro.takeaway}
        </div>
      ) : null}
      {outro.cta ? (
        <div
          style={{
            marginTop: 70,
            color: theme.text,
            fontFamily: theme.numberFontFamily,
            fontWeight: 700,
            fontSize: 38,
            padding: '18px 30px',
            borderRadius: 16,
            border: `2px solid ${theme.textMuted}`,
          }}
        >
          {outro.cta}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
