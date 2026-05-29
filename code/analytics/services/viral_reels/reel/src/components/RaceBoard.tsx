import React from 'react';
import {Theme, colorForId} from '../theme';
import {EntityState} from '../util/interp';
import {formatValue} from '../util/format';
import {ValueFormat} from '../types';

interface Props {
  states: EntityState[];
  allIds: string[];
  maxValue: number;
  barsVisible: number;
  valueFormat: ValueFormat;
  theme: Theme;
  width: number;
  height: number;
}

const LEFT_PAD = 56;
const VALUE_RESERVE = 200;

export const RaceBoard: React.FC<Props> = ({
  states,
  allIds,
  maxValue,
  barsVisible,
  valueFormat,
  theme,
  width,
  height,
}) => {
  const rowHeight = height / barsVisible;
  const barHeight = rowHeight * 0.62;
  const trackWidth = width - LEFT_PAD - VALUE_RESERVE;
  const safeMax = maxValue > 0 ? maxValue : 1;
  const labelFontSize = Math.min(40, rowHeight * 0.3);

  return (
    <div style={{position: 'relative', width, height}}>
      {states.map((s) => {
        // Bars beyond the visible window fade out as they leave the board.
        if (s.rank > barsVisible) return null;
        const opacity =
          s.rank <= barsVisible - 1
            ? 1
            : Math.max(0, 1 - (s.rank - (barsVisible - 1)));
        const top = s.rank * rowHeight + (rowHeight - barHeight) / 2;
        const barLen = Math.max(8, (s.value / safeMax) * trackWidth);
        const color = colorForId(theme, s.id, allIds.indexOf(s.id));

        const estLabelWidth = s.label.length * labelFontSize * 0.62 + 48;
        const labelInside = barLen > estLabelWidth;
        const valueStr = formatValue(s.value, valueFormat);
        const valueWidth = valueStr.length * labelFontSize * 0.92 * 0.6;

        return (
          <div
            key={s.id}
            style={{
              position: 'absolute',
              top,
              left: LEFT_PAD,
              height: barHeight,
              width: trackWidth + VALUE_RESERVE,
              opacity,
            }}
          >
            {/* bar */}
            <div
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                height: barHeight,
                width: barLen,
                background: `linear-gradient(90deg, ${color} 0%, ${color}D9 100%)`,
                borderRadius: barHeight / 4,
                boxShadow: `0 6px 24px ${color}40`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: labelInside ? 'flex-start' : 'flex-end',
              }}
            >
              {labelInside ? (
                <span
                  style={{
                    color: '#0B1020',
                    fontFamily: theme.fontFamily,
                    fontWeight: 800,
                    fontSize: labelFontSize,
                    paddingLeft: 28,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {s.label}
                </span>
              ) : null}
            </div>

            {/* value — always pinned just past the bar tip so the number is
                never pushed off-screen by a long label */}
            <span
              style={{
                position: 'absolute',
                left: barLen + 20,
                top: (barHeight - labelFontSize) / 2 - 2,
                color: theme.textMuted,
                fontFamily: theme.numberFontFamily,
                fontWeight: 700,
                fontSize: labelFontSize * 0.92,
                fontVariantNumeric: 'tabular-nums',
                whiteSpace: 'nowrap',
              }}
            >
              {valueStr}
            </span>

            {/* label outside (short bars) — after the value: [bar] value name */}
            {!labelInside ? (
              <span
                style={{
                  position: 'absolute',
                  left: barLen + 20 + valueWidth + 22,
                  top: (barHeight - labelFontSize) / 2 - 4,
                  color: theme.text,
                  fontFamily: theme.fontFamily,
                  fontWeight: 800,
                  fontSize: labelFontSize,
                  whiteSpace: 'nowrap',
                }}
              >
                {s.label}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
};
