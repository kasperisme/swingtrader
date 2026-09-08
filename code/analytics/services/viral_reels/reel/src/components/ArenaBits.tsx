import React from 'react';
import {Theme} from '../theme';
import {ArenaFooter, ArenaHeader, ArenaRow, FormResult} from '../types';

/**
 * The shared vocabulary of the arena package — the pieces that must look
 * identical in the still table and in the race, because a broadcast graphic
 * that changes its own chrome between two assets in the same post reads as two
 * unrelated posts.
 */

export const fmtPct = (x: number, digits = 2) =>
  `${x >= 0 ? '+' : ''}${(x * 100).toFixed(digits)}%`;

export const fmtNav = (x: number) => `$${Math.round(x).toLocaleString('en-US')}`;

/** Return colour. Deliberately NOT the club colour — money is green or red. */
export const toneFor = (v: number, theme: Theme) =>
  v > 0 ? theme.positive : v < 0 ? theme.negative : theme.textMuted;

const hexToRgba = (hex: string, a: number) => {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
};

export const tint = hexToRgba;

/** The three-letter code on its club colour — the badge a viewer learns. */
export const ClubChip: React.FC<{row: Pick<ArenaRow, 'code' | 'color'>; size: number; theme: Theme}> = ({
  row,
  size,
  theme,
}) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: size * 2.1,
      height: size * 1.25,
      borderRadius: size * 0.28,
      background: tint(row.color, 0.16),
      border: `1px solid ${tint(row.color, 0.45)}`,
      color: row.color,
      fontFamily: theme.numberFontFamily,
      fontWeight: 800,
      fontSize: size * 0.72,
      letterSpacing: 1,
    }}
  >
    {row.code}
  </div>
);

/** ▲2 / ▼1 / — against the lookback session. */
export const MoveChevron: React.FC<{move: number | null; size: number; theme: Theme}> = ({
  move,
  size,
  theme,
}) => {
  if (move === null || move === undefined) {
    return <span style={{color: theme.textMuted, fontSize: size, opacity: 0.4}}>·</span>;
  }
  if (move === 0) {
    return (
      <span style={{color: theme.textMuted, fontSize: size * 0.9, opacity: 0.55}}>–</span>
    );
  }
  const up = move > 0;
  return (
    <span
      style={{
        color: up ? theme.positive : theme.negative,
        fontFamily: theme.numberFontFamily,
        fontWeight: 800,
        fontSize: size * 0.8,
        display: 'inline-flex',
        alignItems: 'center',
        gap: size * 0.12,
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      {up ? '▲' : '▼'}
      {Math.abs(move)}
    </span>
  );
};

/**
 * The football form guide: last five sessions, oldest left.
 *
 * The letters are not decoration. A row of five coloured squares is ambiguous
 * at feed size — red/green colour-blindness aside, the viewer cannot tell which
 * end is "most recent". W/L/D removes both problems, which is exactly why every
 * televised table prints them.
 */
export const FormPills: React.FC<{form: FormResult[]; size: number; theme: Theme}> = ({
  form,
  size,
  theme,
}) => (
  <div style={{display: 'flex', gap: size * 0.24, alignItems: 'center'}}>
    {form.map((f, i) => {
      const last = i === form.length - 1;
      const base = f === 'W' ? theme.positive : f === 'L' ? theme.negative : '#8A93A4';
      return (
        <div
          key={i}
          style={{
            width: size * 1.06,
            height: size * 1.06,
            borderRadius: size * 0.26,
            // The most recent result is solid; the history behind it is muted,
            // so the eye lands on "what happened last".
            background: last ? base : tint(base, 0.34),
            color: last ? '#0B1020' : tint(base, 0.95),
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: theme.numberFontFamily,
            fontWeight: 800,
            fontSize: size * 0.66,
            lineHeight: 1,
          }}
        >
          {f}
        </div>
      );
    })}
  </div>
);

/** The "CONTROL" pill. The single most important label on the board. */
export const ControlPill: React.FC<{size: number; theme: Theme}> = ({size, theme}) => (
  <span
    style={{
      fontFamily: theme.numberFontFamily,
      fontSize: size,
      fontWeight: 700,
      letterSpacing: 2,
      color: theme.textMuted,
      border: `1px solid rgba(255,255,255,0.18)`,
      borderRadius: size * 0.5,
      padding: `${size * 0.18}px ${size * 0.5}px`,
      whiteSpace: 'nowrap',
    }}
  >
    CONTROL
  </span>
);

export const HeaderBlock: React.FC<{
  header: ArenaHeader;
  theme: Theme;
  scale: number;
}> = ({header, theme, scale}) => (
  <div>
    <div
      style={{
        color: theme.accent,
        fontFamily: theme.numberFontFamily,
        fontWeight: 700,
        fontSize: 22 * scale,
        letterSpacing: 5 * scale,
        textTransform: 'uppercase',
      }}
    >
      {header.kicker}
    </div>
    <div
      style={{
        color: theme.text,
        fontFamily: theme.fontFamily,
        fontWeight: 900,
        fontSize: 84 * scale,
        letterSpacing: -2 * scale,
        lineHeight: 1,
        marginTop: 10 * scale,
      }}
    >
      {header.title}
    </div>
    {header.subtitle ? (
      <div
        style={{
          color: theme.textMuted,
          fontFamily: theme.fontFamily,
          fontWeight: 500,
          fontSize: 25 * scale,
          marginTop: 12 * scale,
        }}
      >
        {header.subtitle}
      </div>
    ) : null}
  </div>
);

/**
 * The strap — the sentence across the top of the table. A table with no
 * sentence on it is a report; the strap is what makes it a story.
 */
export const Strap: React.FC<{text: string; theme: Theme; scale: number; reveal?: number}> = ({
  text,
  theme,
  scale,
  reveal = 1,
}) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'stretch',
      gap: 20 * scale,
      background: 'rgba(255,255,255,0.045)',
      borderRadius: 14 * scale,
      padding: `${18 * scale}px ${22 * scale}px`,
      opacity: reveal,
      transform: `translateX(${(1 - reveal) * -24}px)`,
    }}
  >
    <div style={{width: 6 * scale, borderRadius: 3 * scale, background: theme.accent, flexShrink: 0}} />
    <div
      style={{
        color: theme.text,
        fontFamily: theme.fontFamily,
        fontWeight: 700,
        fontSize: 34 * scale,
        lineHeight: 1.25,
      }}
    >
      {text}
    </div>
  </div>
);

export const FooterBlock: React.FC<{footer: ArenaFooter; theme: Theme; scale: number}> = ({
  footer,
  theme,
  scale,
}) => (
  <div
    style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-end',
      borderTop: `1px solid ${theme.grid}`,
      paddingTop: 18 * scale,
      gap: 20 * scale,
    }}
  >
    <div
      style={{
        color: theme.textMuted,
        fontFamily: theme.numberFontFamily,
        fontSize: 20 * scale,
        letterSpacing: 1,
        whiteSpace: 'nowrap',
      }}
    >
      AS OF {footer.asOf}
      <div style={{marginTop: 6 * scale, opacity: 0.75}}>{footer.disclaimer}</div>
    </div>
    {footer.cta ? (
      <div
        style={{
          color: theme.accent,
          fontFamily: theme.fontFamily,
          fontWeight: 800,
          fontSize: 24 * scale,
          textAlign: 'right',
        }}
      >
        {footer.cta}
      </div>
    ) : null}
  </div>
);
