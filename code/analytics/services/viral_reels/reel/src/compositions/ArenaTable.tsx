import React from 'react';
import {AbsoluteFill} from 'remotion';
import {ArenaTableProps, ArenaRow} from '../types';
import {getTheme} from '../theme';
import {Background} from '../components/Background';
import {
  ClubChip,
  ControlPill,
  FooterBlock,
  FormPills,
  HeaderBlock,
  MoveChevron,
  Strap,
  fmtNav,
  fmtPct,
  tint,
  toneFor,
} from '../components/ArenaBits';

/**
 * The still league table — the arena's weekly ritual asset.
 *
 * Everything here is football-table grammar rather than dashboard grammar:
 * a position number, a movement chevron, a form guide, and coloured promotion
 * and relegation bands. A dashboard asks the viewer to interpret; a table tells
 * them who is winning and who is in trouble before they have read a word.
 *
 * The row height is derived from the canvas rather than fixed, so the same
 * component fills 4:5, 9:16 and 1:1 without three sets of numbers to keep in
 * sync — and the extra vertical room in 9:16 goes into a secondary stat line
 * that the tighter crops drop.
 */
export const ArenaTable: React.FC<ArenaTableProps> = ({spec}) => {
  const theme = getTheme(spec.theme);
  const {width, height} = spec.format;
  const rows = spec.rows;

  const scale = width / 1080;

  // The chrome (header, strap, footer) is scaled by the canvas HEIGHT as well
  // as its width. Without this the 1:1 crop spends the same 550px on titles as
  // the 9:16 one and squeezes nine rows into what is left, which is the one way
  // a league table stops being readable.
  const vs = Math.min(1.2, height / 1350);
  const cs = scale * vs;
  const pad = 64 * cs;

  // Reserve the fixed chrome, then give what is left to the rows.
  const headerH = (spec.header.subtitle ? 200 : 160) * cs;
  const strapH = spec.hook ? 118 * cs : 0;
  const colHeadH = 46 * cs;
  const footerH = 118 * cs;
  const boardH = height - pad * 2 - headerH - strapH - colHeadH - footerH;
  const rowH = boardH / Math.max(1, rows.length);

  // The secondary stat line only earns its place when a row is tall enough to
  // carry it; below that it becomes noise stacked on the name.
  const dense = rowH >= 118 * scale;

  const nameSize = Math.min(36 * scale, rowH * 0.34);
  const rankSize = Math.min(40 * scale, rowH * 0.38);
  const retSize = Math.min(40 * scale, rowH * 0.38);
  const navSize = Math.min(25 * scale, rowH * 0.22);
  // Form pills get a floor as well as a cap: derived purely from row height
  // they vanish in the 1:1 crop, and an unreadable form guide is just noise.
  const pillSize = Math.max(15 * scale, Math.min(21 * scale, rowH * 0.20));

  const zoneFor = (r: ArenaRow) => {
    if (r.rank <= spec.zones.top) return tint(theme.positive, 0.10);
    if (r.rank > rows.length - spec.zones.bottom) return tint(theme.negative, 0.10);
    return 'transparent';
  };

  return (
    <AbsoluteFill style={{background: theme.bg}}>
      <Background theme={theme} />
      <AbsoluteFill style={{padding: pad, display: 'flex', flexDirection: 'column'}}>
        <div style={{height: headerH}}>
          <HeaderBlock header={spec.header} theme={theme} scale={cs} />
        </div>

        {spec.hook ? (
          <div style={{height: strapH, paddingBottom: 22 * cs}}>
            <Strap text={spec.hook} theme={theme} scale={cs} />
          </div>
        ) : null}

        {/* column header — the hairline that makes nine rows read as a table */}
        <div
          style={{
            height: colHeadH,
            display: 'flex',
            alignItems: 'center',
            borderBottom: `1px solid ${theme.grid}`,
            color: theme.textMuted,
            fontFamily: theme.numberFontFamily,
            fontSize: 18 * cs,
            letterSpacing: 2.5 * cs,
          }}
        >
          <div style={{width: rankSize * 2.4}}>#</div>
          <div style={{flex: 1}}>AGENT</div>
          <div style={{width: 190 * scale, textAlign: 'right'}}>FORM</div>
          <div style={{width: 220 * scale, textAlign: 'right'}}>RETURN</div>
        </div>

        <div style={{flex: 1, display: 'flex', flexDirection: 'column'}}>
          {rows.map((r) => (
            <div
              key={r.slug}
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                background: zoneFor(r),
                borderBottom: `1px solid ${theme.grid}`,
                paddingLeft: 14 * scale,
                position: 'relative',
              }}
            >
              {/* club colour — the constant that makes an agent recognisable */}
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: rowH * 0.16,
                  bottom: rowH * 0.16,
                  width: 5 * scale,
                  borderRadius: 3 * scale,
                  background: r.color,
                }}
              />

              <div
                style={{
                  width: rankSize * 1.5,
                  color: theme.text,
                  fontFamily: theme.numberFontFamily,
                  fontWeight: 800,
                  fontSize: rankSize,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {r.rank}
              </div>
              <div style={{width: rankSize * 0.9}}>
                <MoveChevron move={r.move} size={rankSize * 0.62} theme={theme} />
              </div>

              <div style={{marginLeft: 12 * scale, marginRight: 16 * scale}}>
                <ClubChip row={r} size={nameSize * 0.62} theme={theme} />
              </div>

              <div style={{flex: 1, minWidth: 0}}>
                <div style={{display: 'flex', alignItems: 'center', gap: 12 * scale}}>
                  <span
                    style={{
                      color: theme.text,
                      fontFamily: theme.fontFamily,
                      fontWeight: 700,
                      fontSize: nameSize,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {r.name}
                  </span>
                  {r.isControl ? <ControlPill size={pillSize} theme={theme} /> : null}
                </div>
                {dense ? (
                  <div
                    style={{
                      marginTop: 8 * scale,
                      color: theme.textMuted,
                      fontFamily: theme.numberFontFamily,
                      fontSize: navSize,
                      letterSpacing: 0.5,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {/* Kept to ONE line at every crop: a stat line that wraps
                        pushes the name off its own baseline and the row stops
                        scanning as a row. */}
                    {fmtNav(r.nav)} · DD {(r.drawdown * 100).toFixed(1)}% · {r.trades}T
                    {r.winRate === null ? '' : ` ${Math.round(r.winRate * 100)}%W`}
                  </div>
                ) : null}
              </div>

              <div style={{width: 190 * scale, display: 'flex', justifyContent: 'flex-end'}}>
                <FormPills form={r.form} size={pillSize * 1.15} theme={theme} />
              </div>

              <div
                style={{
                  width: 220 * scale,
                  textAlign: 'right',
                  color: toneFor(r.return, theme),
                  fontFamily: theme.numberFontFamily,
                  fontWeight: 800,
                  fontSize: retSize,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {fmtPct(r.return)}
                {!dense ? (
                  <div
                    style={{
                      color: theme.textMuted,
                      fontWeight: 500,
                      fontSize: navSize,
                      marginTop: 4 * scale,
                    }}
                  >
                    {fmtNav(r.nav)}
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>

        <div style={{height: footerH, display: 'flex', alignItems: 'flex-end'}}>
          <div style={{width: '100%'}}>
            <FooterBlock footer={spec.footer} theme={theme} scale={cs} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
