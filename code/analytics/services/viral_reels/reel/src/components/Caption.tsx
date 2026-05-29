import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {Theme} from '../theme';
import {Caption as CaptionType} from '../types';

/**
 * Timed lower-third caption beats. Rendered at the video level so they overlay
 * the race; each appears at its atSeconds and fades over a short window.
 */
export const Captions: React.FC<{captions: CaptionType[]; theme: Theme}> = ({captions, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const HOLD = 3.4; // seconds visible

  return (
    <AbsoluteFill>
      {captions.map((c, i) => {
        const start = c.atSeconds * fps;
        const end = (c.atSeconds + HOLD) * fps;
        if (frame < start - 8 || frame > end + 8) return null;
        const opacity = interpolate(
          frame,
          [start - 8, start + 8, end - 12, end + 8],
          [0, 1, 1, 0],
          {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
        );
        const y = interpolate(frame, [start - 8, start + 12], [24, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        return (
          <div
            key={i}
            // Anchored in the reserved bottom band (above the source footer),
            // clear of the racing bars.
            style={{
              position: 'absolute',
              left: 56,
              right: 56,
              bottom: 110,
              opacity,
              transform: `translateY(${y}px)`,
            }}
          >
            <div
              style={{
                display: 'inline-block',
                background: theme.text,
                color: theme.bg,
                fontFamily: theme.fontFamily,
                fontWeight: 800,
                fontSize: 44,
                lineHeight: 1.18,
                padding: '20px 28px',
                borderRadius: 18,
                boxShadow: '0 12px 40px rgba(0,0,0,0.35)',
              }}
            >
              {c.text}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
