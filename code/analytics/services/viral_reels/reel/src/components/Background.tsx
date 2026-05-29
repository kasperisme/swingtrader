import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Theme} from '../theme';

export const Background: React.FC<{theme: Theme}> = ({theme}) => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme.bg,
        backgroundImage: `radial-gradient(120% 80% at 50% -10%, ${theme.bgAccent} 0%, ${theme.bg} 60%)`,
      }}
    >
      {/* faint horizontal grid for the data-viz feel */}
      <AbsoluteFill
        style={{
          backgroundImage: `repeating-linear-gradient(0deg, ${theme.grid} 0px, ${theme.grid} 1px, transparent 1px, transparent 96px)`,
          opacity: 0.7,
        }}
      />
    </AbsoluteFill>
  );
};
