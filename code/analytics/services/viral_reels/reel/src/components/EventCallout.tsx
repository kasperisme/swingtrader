import React from 'react';
import {Theme} from '../theme';
import {NewsEvent} from '../types';

/**
 * The news event currently being passed by the price line — a card matching the
 * app's article style, plus a sentiment-coloured edge and an optional price
 * reaction chip, so viewers connect the headline to the move.
 */
export const EventCallout: React.FC<{
  event: NewsEvent;
  theme: Theme;
  width: number;
  height: number;
}> = ({event, theme, width, height}) => {
  const sentiment = event.sentiment ?? 0;
  const color = sentiment > 0.05 ? theme.positive : sentiment < -0.05 ? theme.negative : theme.accent;
  const arrow = sentiment > 0.05 ? '▲' : sentiment < -0.05 ? '▼' : '◆';

  return (
    <div
      style={{
        width,
        height,
        boxSizing: 'border-box',
        display: 'flex',
        alignItems: 'center',
        gap: 22,
        background: theme.trackBg,
        border: `1px solid ${theme.grid}`,
        borderLeft: `8px solid ${color}`,
        borderRadius: 20,
        padding: '18px 24px',
        boxShadow: '0 12px 40px rgba(0,0,0,0.30)',
      }}
    >
      <div style={{flex: 1, minWidth: 0}}>
        {event.source ? (
          <div
            style={{
              color: theme.accent,
              fontFamily: theme.numberFontFamily,
              fontWeight: 700,
              fontSize: 24,
              letterSpacing: 2.5,
              textTransform: 'uppercase',
              marginBottom: 8,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {event.source}
          </div>
        ) : null}
        <div
          style={{
            color: theme.text,
            fontFamily: theme.fontFamily,
            fontWeight: 700,
            fontSize: 36,
            lineHeight: 1.18,
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {event.title}
        </div>
      </div>

      {/* reaction chip */}
      <div style={{flex: 'none', textAlign: 'right'}}>
        <div style={{color, fontFamily: theme.numberFontFamily, fontWeight: 800, fontSize: 40}}>
          {arrow}
        </div>
        {event.move ? (
          <div
            style={{
              color,
              fontFamily: theme.numberFontFamily,
              fontWeight: 800,
              fontSize: 30,
              fontVariantNumeric: 'tabular-nums',
              whiteSpace: 'nowrap',
              marginTop: 2,
            }}
          >
            {event.move}
          </div>
        ) : null}
      </div>
    </div>
  );
};
