// Themes inspired by r/dataisbeautiful staples: high-contrast backgrounds,
// a confident categorical palette, and bold tabular numerals.

export interface Theme {
  bg: string;
  bgAccent: string; // subtle radial/edge tint
  grid: string;
  text: string;
  textMuted: string;
  trackBg: string;
  accent: string; // amber-ish, matches the app's article-card source label
  palette: string[]; // categorical, cycled by stable entity index
  positive: string;
  negative: string;
  fontFamily: string;
  numberFontFamily: string;
}

const SYSTEM_SANS =
  '"Inter", "Helvetica Neue", Helvetica, "Segoe UI", Roboto, Arial, sans-serif';
const SYSTEM_MONO =
  '"SF Mono", "Roboto Mono", "DejaVu Sans Mono", Menlo, Consolas, monospace';

// A vivid, well-separated categorical palette (Tableau-10 adjacent, punched up).
const VIVID = [
  '#5B8FF9',
  '#FF6B6B',
  '#3DD68C',
  '#FFB454',
  '#9D7BFF',
  '#2BC4D9',
  '#FF8FB1',
  '#C2E05B',
  '#E0709B',
  '#7A8CFF',
  '#FFD166',
  '#4CC9A0',
];

export const THEMES: Record<string, Theme> = {
  midnight: {
    bg: '#0B1020',
    bgAccent: '#141B33',
    grid: 'rgba(255,255,255,0.06)',
    text: '#F5F7FF',
    textMuted: 'rgba(245,247,255,0.55)',
    trackBg: 'rgba(255,255,255,0.05)',
    accent: '#F5A623',
    palette: VIVID,
    positive: '#3DD68C',
    negative: '#FF6B6B',
    fontFamily: SYSTEM_SANS,
    numberFontFamily: SYSTEM_MONO,
  },
  paper: {
    bg: '#F4F1EA',
    bgAccent: '#ECE7DB',
    grid: 'rgba(0,0,0,0.06)',
    text: '#1B1B1B',
    textMuted: 'rgba(27,27,27,0.55)',
    trackBg: 'rgba(0,0,0,0.05)',
    accent: '#B45309',
    palette: VIVID,
    positive: '#1B9E5A',
    negative: '#D6453C',
    fontFamily: SYSTEM_SANS,
    numberFontFamily: SYSTEM_MONO,
  },
  neon: {
    bg: '#06070D',
    bgAccent: '#0E1330',
    grid: 'rgba(120,200,255,0.08)',
    text: '#EAF6FF',
    textMuted: 'rgba(234,246,255,0.6)',
    trackBg: 'rgba(120,200,255,0.06)',
    accent: '#00E5FF',
    palette: [
      '#00E5FF',
      '#FF2D9B',
      '#7CFF6B',
      '#FFC83D',
      '#B388FF',
      '#36F1CD',
      '#FF7AC6',
      '#A0FF3D',
    ],
    positive: '#7CFF6B',
    negative: '#FF2D9B',
    fontFamily: SYSTEM_SANS,
    numberFontFamily: SYSTEM_MONO,
  },
};

export const getTheme = (name: string | undefined): Theme =>
  THEMES[name ?? 'midnight'] ?? THEMES.midnight;

// Stable colour for an entity: hash its id into the palette so colour is
// consistent regardless of its current rank.
export const colorForId = (theme: Theme, id: string, fallbackIndex: number): string => {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  const idx = id.length ? hash % theme.palette.length : fallbackIndex % theme.palette.length;
  return theme.palette[idx];
};
