import React from 'react';
import {Theme} from '../theme';
import {EntityState} from '../util/interp';
import {ArenaAgent} from '../types';
import {ClubChip, fmtPct, tint} from './ArenaBits';

interface Props {
  states: EntityState[];
  agents: Map<string, ArenaAgent>;
  /** Fixed axis bounds for the whole race — see the note below. */
  axisMin: number;
  axisMax: number;
  theme: Theme;
  width: number;
  height: number;
  scale: number;
  /** 0..1 pulse on the current leader. */
  spotlight?: number;
}

// Wide enough for the longest name on the roster at the rail's own font size;
// a truncated competitor name is worse than a slightly shorter bar.
const NAME_W = 384;
const VALUE_W = 158;

/**
 * The racing league table: rows reorder by rank, bars diverge from a zero line.
 *
 * Two decisions that make this readable where a normal bar-chart race is not:
 *
 * **Diverging bars, not zero-based ones.** The metric is cumulative return, and
 * half the field is usually negative. A zero-based race would draw a losing
 * agent as an absent bar; a zero line draws it as a bar going the *other way*,
 * which is the actual fact.
 *
 * **The axis is fixed for the whole video**, computed from the global min/max
 * across every keyframe rather than from the current frame. A rescaling axis
 * makes every bar appear to move even on a session where nothing happened, and
 * the viewer cannot tell a real overtake from a change of scale.
 */
export const ArenaRaceBoard: React.FC<Props> = ({
  states,
  agents,
  axisMin,
  axisMax,
  theme,
  width,
  height,
  scale,
  spotlight = 0,
}) => {
  const rowH = height / Math.max(1, states.length);
  const barH = rowH * 0.5;

  const nameW = NAME_W * scale;
  const valueW = VALUE_W * scale;
  const trackL = nameW;
  const trackW = width - nameW - valueW;

  const span = Math.max(1e-9, axisMax - axisMin);
  const xFor = (v: number) => trackL + ((v - axisMin) / span) * trackW;
  const zeroX = xFor(0);

  return (
    <div style={{position: 'relative', width, height}}>
      {/* the zero line — "break even", and the only reference the viewer needs */}
      <div
        style={{
          position: 'absolute',
          left: zeroX,
          top: -10 * scale,
          bottom: -10 * scale,
          width: Math.max(1, 2 * scale),
          background: 'rgba(255,255,255,0.28)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: zeroX + 8 * scale,
          top: -34 * scale,
          color: theme.textMuted,
          fontFamily: theme.numberFontFamily,
          fontSize: 20 * scale,
          letterSpacing: 1,
        }}
      >
        BREAK EVEN
      </div>

      {states.map((s) => {
        const a = agents.get(s.id);
        if (!a) return null;
        const top = s.rank * rowH;
        const isLeader = s.rank < 0.5;
        const x = xFor(s.value);
        const barL = Math.min(zeroX, x);
        const barW = Math.max(2 * scale, Math.abs(x - zeroX));
        const positive = s.value >= 0;

        return (
          <div
            key={s.id}
            style={{
              position: 'absolute',
              top,
              left: 0,
              width,
              height: rowH,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            {/* left rail: position, club chip, name */}
            <div
              style={{
                width: nameW,
                display: 'flex',
                alignItems: 'center',
                gap: 14 * scale,
                paddingRight: 18 * scale,
              }}
            >
              <div
                style={{
                  width: 46 * scale,
                  color: theme.textMuted,
                  fontFamily: theme.numberFontFamily,
                  fontWeight: 800,
                  fontSize: 30 * scale,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {Math.round(s.rank) + 1}
              </div>
              <ClubChip row={a} size={22 * scale} theme={theme} />
              <div
                style={{
                  color: isLeader ? theme.text : 'rgba(245,247,255,0.82)',
                  fontFamily: theme.fontFamily,
                  fontWeight: 700,
                  fontSize: 26 * scale,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {a.name}
              </div>
            </div>

            {/* the diverging bar */}
            <div
              style={{
                position: 'absolute',
                left: barL,
                top: (rowH - barH) / 2,
                width: barW,
                height: barH,
                background: a.color,
                borderRadius: 6 * scale,
                // The controls read as pale steel; a leading control should not
                // look like a branded strategy winning.
                opacity: a.isControl ? 0.82 : 1,
                boxShadow: isLeader
                  ? `0 0 ${(18 + spotlight * 34) * scale}px ${tint(a.color, 0.35 + spotlight * 0.4)}`
                  : 'none',
              }}
            />

            {/* the number, always outside the bar on the growth side */}
            <div
              style={{
                position: 'absolute',
                left: positive ? barL + barW + 14 * scale : barL - valueW - 4 * scale,
                width: valueW,
                textAlign: positive ? 'left' : 'right',
                color: positive ? theme.positive : theme.negative,
                fontFamily: theme.numberFontFamily,
                fontWeight: 800,
                fontSize: 28 * scale,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {fmtPct(s.value)}
            </div>
          </div>
        );
      })}
    </div>
  );
};
