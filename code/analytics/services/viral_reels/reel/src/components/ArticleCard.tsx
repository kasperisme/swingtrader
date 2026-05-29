import React from 'react';
import {Img} from 'remotion';
import {Theme} from '../theme';

/**
 * The single article-card design shared by both formats: thumbnail · amber
 * uppercase source · off-white title · right-side meta. The meta is either a
 * relative age (headline cards) or a sentiment arrow + price move (news events
 * on the price chart). When a sentiment is supplied the left edge is tinted.
 */
export const ArticleCard: React.FC<{
  title: string;
  source?: string;
  imageUrl?: string;
  age?: string;
  sentiment?: number;
  move?: string;
  theme: Theme;
  width: number;
  height: number;
}> = ({title, source, imageUrl, age, sentiment, move, theme, width, height}) => {
  const hasSentiment = typeof sentiment === 'number';
  // Sentiment toward the ticker drives the arrow + left-edge tint (and matches
  // the pin colour on the price line): green bullish, red bearish, amber ~flat.
  const color = !hasSentiment
    ? theme.accent
    : sentiment! > 0.05
      ? theme.positive
      : sentiment! < -0.05
        ? theme.negative
        : theme.accent;
  const arrow = !hasSentiment ? '' : sentiment! > 0.05 ? '▲' : sentiment! < -0.05 ? '▼' : '◆';
  // The price move is coloured by its OWN sign, not by sentiment — so a bullish
  // headline that preceded a drop reads honestly (green ▲ sentiment, red move).
  const moveNum = move ? parseFloat(move.replace('+', '')) : NaN;
  const moveColor = Number.isNaN(moveNum)
    ? theme.textMuted
    : moveNum > 0
      ? theme.positive
      : moveNum < 0
        ? theme.negative
        : theme.textMuted;
  // Sizes scale with the card height so a bigger card gets a bigger image,
  // larger type, and more title lines.
  const thumb = height - 36;
  const big = height >= 210;
  const titleSize = big ? 42 : 36;
  const sourceSize = big ? 27 : 24;
  const titleLines = big ? 3 : 2;

  return (
    <div
      style={{
        width,
        height,
        boxSizing: 'border-box',
        display: 'flex',
        alignItems: 'center',
        gap: 24,
        // opaque panel so it reads cleanly when floated over the chart
        background: theme.bgAccent,
        border: `1px solid ${theme.grid}`,
        borderLeft: hasSentiment ? `8px solid ${color}` : `1px solid ${theme.grid}`,
        borderRadius: 22,
        padding: 18,
        boxShadow: '0 16px 48px rgba(0,0,0,0.45)',
      }}
    >
      {/* thumbnail — real article image with a graceful fallback behind it */}
      <div
        style={{
          width: thumb * 1.25,
          height: thumb,
          flex: 'none',
          borderRadius: 14,
          overflow: 'hidden',
          position: 'relative',
          background: `linear-gradient(135deg, ${theme.bgAccent}, ${theme.bg})`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span style={{color: theme.textMuted, fontFamily: theme.numberFontFamily, fontSize: 40}}>▦</span>
        {imageUrl ? (
          <Img
            src={imageUrl}
            onError={() => undefined}
            style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}}
          />
        ) : null}
      </div>

      {/* source + title */}
      <div style={{flex: 1, minWidth: 0}}>
        {source ? (
          <div
            style={{
              color: theme.accent,
              fontFamily: theme.numberFontFamily,
              fontWeight: 700,
              fontSize: sourceSize,
              letterSpacing: 2.5,
              textTransform: 'uppercase',
              marginBottom: 10,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {source}
          </div>
        ) : null}
        <div
          style={{
            color: theme.text,
            fontFamily: theme.fontFamily,
            fontWeight: 700,
            fontSize: titleSize,
            lineHeight: 1.18,
            display: '-webkit-box',
            WebkitLineClamp: titleLines,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {title}
        </div>
      </div>

      {/* right meta: sentiment + move (events) or age (headlines) */}
      {hasSentiment ? (
        <div style={{flex: 'none', textAlign: 'right'}}>
          <div style={{color, fontFamily: theme.numberFontFamily, fontWeight: 800, fontSize: 40}}>{arrow}</div>
          {move ? (
            <div
              style={{
                color: moveColor,
                fontFamily: theme.numberFontFamily,
                fontWeight: 800,
                fontSize: 28,
                fontVariantNumeric: 'tabular-nums',
                whiteSpace: 'nowrap',
                marginTop: 2,
              }}
            >
              {move}
            </div>
          ) : null}
        </div>
      ) : age ? (
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
          {age}
        </div>
      ) : null}
    </div>
  );
};
