import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {Theme} from '../theme';
import {HeadlineItem} from '../types';
import {HeadlineCard} from './HeadlineCard';

/**
 * Cycles the real headlines behind the trend, one card at a time, across the
 * race. Rendered inside the race Sequence, so useCurrentFrame() is local
 * (0 .. raceFrames-1).
 */
export const Headlines: React.FC<{
  items: HeadlineItem[];
  theme: Theme;
  width: number;
  height: number;
  raceFrames: number;
}> = ({items, theme, width, height, raceFrames}) => {
  const frame = useCurrentFrame();
  if (!items.length) return null;

  const slot = raceFrames / items.length;
  const idx = Math.min(items.length - 1, Math.floor(frame / slot));
  const local = frame - idx * slot;

  // fade/slide in at the start of each slot, out at the end
  const fade = 8;
  const opacity = interpolate(
    local,
    [0, fade, slot - fade, slot],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const y = interpolate(local, [0, fade], [18, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div style={{opacity, transform: `translateY(${y}px)`}}>
      <HeadlineCard item={items[idx]} theme={theme} width={width} height={height} />
    </div>
  );
};
