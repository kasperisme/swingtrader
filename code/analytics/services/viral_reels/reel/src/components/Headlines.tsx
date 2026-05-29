import React from 'react';
import {interpolate} from 'remotion';
import {Theme} from '../theme';
import {HeadlineItem} from '../types';
import {ArticleCard} from './ArticleCard';

/**
 * Cycles the real headlines behind the trend, one card at a time. Timing is
 * driven by the caller (`localFrame` over `spanFrames`) so it only runs during
 * the detailed replay — not during the fast reward "peek".
 */
export const Headlines: React.FC<{
  items: HeadlineItem[];
  theme: Theme;
  width: number;
  height: number;
  localFrame: number;
  spanFrames: number;
}> = ({items, theme, width, height, localFrame, spanFrames}) => {
  if (!items.length || localFrame < 0) return null;

  const slot = spanFrames / items.length;
  const idx = Math.min(items.length - 1, Math.floor(localFrame / slot));
  const local = localFrame - idx * slot;

  const fade = 8;
  const opacity = interpolate(local, [0, fade, slot - fade, slot], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const y = interpolate(local, [0, fade], [18, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const item = items[idx];
  return (
    <div style={{opacity, transform: `translateY(${y}px)`}}>
      <ArticleCard
        title={item.title}
        source={item.source}
        imageUrl={item.imageUrl}
        age={item.age}
        theme={theme}
        width={width}
        height={height}
      />
    </div>
  );
};
