import React from 'react';
import {AbsoluteFill, Img, useVideoConfig} from 'remotion';
import {StockCardProps} from '../types';
import {getTheme} from '../theme';

/**
 * Stock card — a still poster in the style of eyeball.football's player cards:
 * a big hero portrait (the CEO; falls back to the company logo on a branded
 * gradient), a headline hook top-left, a rating badge top-right, and a frosted
 * panel of identity + stat cards across the bottom. Rendered as a single PNG
 * via Remotion `still`, so there is no animation — only layout.
 */
export const StockCard: React.FC<StockCardProps> = ({spec}) => {
  const {width, height} = useVideoConfig();
  const theme = getTheme(spec.theme);
  const card = spec.card;
  const hero = card.heroImageUrl || card.logoUrl || null;
  const heroIsLogo = !card.heroImageUrl && !!card.logoUrl;

  const badgeTone =
    card.badge?.tone === 'positive'
      ? theme.positive
      : card.badge?.tone === 'negative'
        ? theme.negative
        : theme.accent;

  // Frosted card surface used by the identity row + stat grid (white over the
  // photo, like the eyeball cards) for legibility regardless of theme/photo.
  const surface = 'rgba(255,255,255,0.95)';
  const surfaceText = '#15151B';
  const surfaceMuted = 'rgba(21,21,27,0.55)';

  const PAD = 56;
  const stats = (card.stats || []).slice(0, 4);

  return (
    <AbsoluteFill style={{backgroundColor: theme.bg, fontFamily: theme.fontFamily}}>
      {/* ---- hero layer ---- */}
      {hero && !heroIsLogo ? (
        <Img
          src={hero}
          onError={() => undefined}
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width,
            height: Math.round(height * 0.72),
            objectFit: 'cover',
            objectPosition: 'center 22%',
          }}
        />
      ) : (
        // Logo-as-hero: branded gradient with the logo centred.
        <AbsoluteFill
          style={{
            height: Math.round(height * 0.72),
            backgroundImage: `radial-gradient(90% 70% at 50% 30%, ${theme.bgAccent} 0%, ${theme.bg} 70%)`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {hero ? (
            <Img
              src={hero}
              onError={() => undefined}
              style={{width: 420, height: 420, objectFit: 'contain', filter: 'drop-shadow(0 24px 64px rgba(0,0,0,0.5))'}}
            />
          ) : (
            <div style={{color: theme.textMuted, fontFamily: theme.numberFontFamily, fontSize: 220, fontWeight: 800}}>
              {card.ticker}
            </div>
          )}
        </AbsoluteFill>
      )}

      {/* top scrim — keeps the headline legible over a bright photo */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width,
          height: Math.round(height * 0.42),
          backgroundImage: 'linear-gradient(180deg, rgba(0,0,0,0.72) 0%, rgba(0,0,0,0.28) 45%, rgba(0,0,0,0) 100%)',
        }}
      />
      {/* bottom scrim — fade the photo into the panel zone */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: Math.round(height * 0.48),
          width,
          height: Math.round(height * 0.52),
          backgroundImage: `linear-gradient(180deg, rgba(0,0,0,0) 0%, ${theme.bg} 62%)`,
        }}
      />

      {/* ---- headline (top-left) ---- */}
      <div style={{position: 'absolute', top: PAD, left: PAD, width: width - PAD - 280}}>
        <div
          style={{
            color: '#FFFFFF',
            fontWeight: 800,
            fontStyle: 'italic',
            fontSize: 84,
            lineHeight: 0.96,
            letterSpacing: -1,
            textTransform: 'uppercase',
            textShadow: '0 4px 24px rgba(0,0,0,0.55)',
          }}
        >
          {card.headline}
        </div>
        {card.tag ? (
          <div
            style={{
              display: 'inline-block',
              marginTop: 22,
              padding: '12px 26px',
              borderRadius: 999,
              background: `linear-gradient(135deg, ${badgeTone}, ${theme.accent})`,
              color: '#0B0B0F',
              fontWeight: 800,
              fontSize: 30,
              letterSpacing: 1.5,
              textTransform: 'uppercase',
              boxShadow: '0 10px 28px rgba(0,0,0,0.4)',
            }}
          >
            {card.tag}
          </div>
        ) : null}
      </div>

      {/* ---- rating badge (top-right) ---- */}
      {card.badge ? (
        <div
          style={{
            position: 'absolute',
            top: PAD,
            right: PAD,
            width: 210,
            borderRadius: 26,
            overflow: 'hidden',
            background: `linear-gradient(160deg, ${badgeTone}, ${theme.accent})`,
            boxShadow: '0 16px 40px rgba(0,0,0,0.45)',
            textAlign: 'center',
          }}
        >
          {card.badge.label ? (
            <div
              style={{
                padding: '14px 8px 6px',
                color: '#0B0B0F',
                fontWeight: 800,
                fontSize: 28,
                letterSpacing: 1,
                textTransform: 'uppercase',
              }}
            >
              {card.badge.label}
            </div>
          ) : null}
          <div
            style={{
              padding: card.badge.label ? '0 8px 16px' : '18px 8px',
              color: '#0B0B0F',
              fontFamily: theme.numberFontFamily,
              fontWeight: 800,
              fontSize: 92,
              lineHeight: 1,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {card.badge.value}
          </div>
        </div>
      ) : null}

      {/* ---- bottom panel: identity + stat grid + footer ---- */}
      <div style={{position: 'absolute', left: PAD, right: PAD, bottom: PAD}}>
        {/* identity row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 22,
            background: surface,
            borderRadius: 24,
            padding: '20px 26px',
            boxShadow: '0 18px 50px rgba(0,0,0,0.4)',
          }}
        >
          {card.logoUrl ? (
            <div
              style={{
                width: 76,
                height: 76,
                borderRadius: 16,
                flex: 'none',
                overflow: 'hidden',
                background: '#FFFFFF',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: 'inset 0 0 0 1px rgba(0,0,0,0.06)',
              }}
            >
              <Img src={card.logoUrl} onError={() => undefined} style={{width: '88%', height: '88%', objectFit: 'contain'}} />
            </div>
          ) : null}
          <div style={{flex: 1, minWidth: 0}}>
            <div
              style={{
                color: surfaceText,
                fontWeight: 800,
                fontSize: 44,
                lineHeight: 1.05,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {card.company}
            </div>
            <div style={{color: surfaceMuted, fontSize: 28, marginTop: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
              {[card.ceo, card.sector].filter(Boolean).join(' · ')}
            </div>
          </div>
          <div
            style={{
              flex: 'none',
              color: surfaceText,
              fontFamily: theme.numberFontFamily,
              fontWeight: 800,
              fontSize: 44,
              letterSpacing: 1,
            }}
          >
            {card.ticker}
          </div>
        </div>

        {/* stat grid (2 columns) */}
        {stats.length ? (
          <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16}}>
            {stats.map((s, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 16,
                  background: surface,
                  borderRadius: 22,
                  padding: '20px 26px',
                  boxShadow: '0 14px 40px rgba(0,0,0,0.35)',
                }}
              >
                <div style={{color: surfaceMuted, fontSize: 30, fontWeight: 700, lineHeight: 1.1, minWidth: 0}}>{s.label}</div>
                <div style={{textAlign: 'right', flex: 'none'}}>
                  <div
                    style={{
                      color: surfaceText,
                      fontFamily: theme.numberFontFamily,
                      fontWeight: 800,
                      fontSize: 46,
                      fontVariantNumeric: 'tabular-nums',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {s.value}
                  </div>
                  {s.sub ? <div style={{color: surfaceMuted, fontSize: 22, marginTop: 2}}>{s.sub}</div> : null}
                </div>
              </div>
            ))}
          </div>
        ) : null}

        {/* footer: brand left, CTA right */}
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 22}}>
          <div
            style={{
              color: theme.textMuted,
              fontWeight: 800,
              fontSize: 26,
              letterSpacing: 1.5,
              textTransform: 'uppercase',
            }}
          >
            {card.footer || 'newsimpactscreener.com'}
          </div>
          {card.cta ? (
            <div
              style={{
                padding: '14px 28px',
                borderRadius: 999,
                background: '#FFFFFF',
                color: '#0B0B0F',
                fontWeight: 800,
                fontSize: 28,
                boxShadow: '0 12px 30px rgba(0,0,0,0.4)',
              }}
            >
              {card.cta} →
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
