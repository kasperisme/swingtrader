import React from 'react';
import {Theme} from '../theme';

export const Footer: React.FC<{sources: string[]; theme: Theme; width: number}> = ({
  sources,
  theme,
  width,
}) => {
  return (
    <div
      style={{
        position: 'absolute',
        bottom: 36,
        left: 56,
        width: width - 112,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        color: theme.textMuted,
        fontFamily: theme.fontFamily,
        fontWeight: 600,
        fontSize: 24,
      }}
    >
      <span>Source: {sources.join(' · ')}</span>
      <span style={{fontWeight: 800, color: theme.text}}>newsimpactscreener.com</span>
    </div>
  );
};
