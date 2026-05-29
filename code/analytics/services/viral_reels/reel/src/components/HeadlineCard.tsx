import React from 'react';
import {Img} from 'remotion';
import {Theme} from '../theme';
import {HeadlineItem} from '../types';

/**
 * One article card, styled to match the app's news-feed card:
 * thumbnail · amber uppercase source · off-white title · muted time-ago.
 */
export const HeadlineCard: React.FC<{
  item: HeadlineItem;
  theme: Theme;
  width: number;
  height: number;
}> = ({item, theme, width, height}) => {
  const thumb = Math.min(height - 36, 150);
  return (
    <div
      style={{
        width,
        height,
        boxSizing: 'border-box',
        display: 'flex',
        alignItems: 'center',
        gap: 26,
        background: theme.trackBg,
        border: `1px solid ${theme.grid}`,
        borderRadius: 22,
        padding: 18,
        boxShadow: '0 12px 40px rgba(0,0,0,0.30)',
      }}
    >
      {/* thumbnail (4:3-ish), with graceful fallback */}
      <div
        style={{
          width: thumb * 1.25,
          height: thumb,
          flex: 'none',
          borderRadius: 14,
          overflow: 'hidden',
          background: `linear-gradient(135deg, ${theme.bgAccent}, ${theme.bg})`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {item.imageUrl ? (
          <Img src={item.imageUrl} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
        ) : (
          <span style={{color: theme.textMuted, fontFamily: theme.numberFontFamily, fontSize: 40}}>
            ▦
          </span>
        )}
      </div>

      {/* text column */}
      <div style={{flex: 1, minWidth: 0}}>
        {item.source ? (
          <div
            style={{
              color: theme.accent,
              fontFamily: theme.numberFontFamily,
              fontWeight: 700,
              fontSize: 25,
              letterSpacing: 2.5,
              textTransform: 'uppercase',
              marginBottom: 10,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {item.source}
          </div>
        ) : null}
        <div
          style={{
            color: theme.text,
            fontFamily: theme.fontFamily,
            fontWeight: 700,
            fontSize: 37,
            lineHeight: 1.18,
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {item.title}
        </div>
      </div>

      {/* time-ago */}
      {item.age ? (
        <div
          style={{
            alignSelf: 'flex-start',
            flex: 'none',
            color: theme.textMuted,
            fontFamily: theme.numberFontFamily,
            fontSize: 24,
            fontVariantNumeric: 'tabular-nums',
            whiteSpace: 'nowrap',
            paddingTop: 4,
          }}
        >
          {item.age}
        </div>
      ) : null}
    </div>
  );
};
