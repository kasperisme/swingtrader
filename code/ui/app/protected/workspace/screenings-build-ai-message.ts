import type { ScreeningRow } from "./screenings-types";

/** User message for the row-level AI analysis panel. */
export function buildScreeningsAiMessage(r: ScreeningRow): string {
  const parts: string[] = [];
  if (r.RS_Rank != null) parts.push(`RS Rank: ${r.RS_Rank}`);
  if (r.adr_pct != null) parts.push(`ADR: ${r.adr_pct.toFixed(1)}%`);
  if (r.vol_ratio_today != null)
    parts.push(`Vol ratio: ${r.vol_ratio_today.toFixed(2)}`);
  if (r.up_down_vol_ratio != null)
    parts.push(`Up/down vol ratio: ${r.up_down_vol_ratio.toFixed(2)}`);
  if (r.within_buy_range != null)
    parts.push(`In buy range: ${r.within_buy_range}`);
  if (r.extended != null) parts.push(`Extended: ${r.extended}`);
  if (r.accumulation != null) parts.push(`Accumulation: ${r.accumulation}`);
  if (r.rs_line_new_high != null)
    parts.push(`RS line new high: ${r.rs_line_new_high}`);
  if (r.PriceOverSMA150And200) parts.push(`Price > SMA150 & SMA200: true`);
  if (r.SMA150AboveSMA200) parts.push(`SMA150 > SMA200: true`);
  if (r.SMA50AboveSMA150And200) parts.push(`SMA50 > SMA150 & SMA200: true`);
  if (r.SMA200Slope) parts.push(`SMA200 slope up: true`);
  if (r.PriceAbove25Percent52WeekLow)
    parts.push(`Price > 25% above 52w low: true`);
  if (r.PriceWithin25Percent52WeekHigh)
    parts.push(`Price within 25% of 52w high: true`);
  if (r.RSOver70) parts.push(`RS > 70: true`);
  if (r.eps_growth_yoy != null)
    parts.push(`EPS growth YoY: ${r.eps_growth_yoy.toFixed(0)}%`);
  if (r.rev_growth_yoy != null)
    parts.push(`Revenue growth YoY: ${r.rev_growth_yoy.toFixed(0)}%`);
  if (r.eps_accelerating != null)
    parts.push(`EPS accelerating: ${r.eps_accelerating}`);
  if (r.roe != null) parts.push(`ROE: ${r.roe.toFixed(1)}%`);
  if (r.inst_pct_accumulating != null)
    parts.push(`Inst. accumulating: ${r.inst_pct_accumulating.toFixed(0)}%`);
  if (r.sector) parts.push(`Sector: ${r.sector}`);
  if (r.industry) parts.push(`Industry: ${r.industry}`);
  if (r.sector_rank != null && r.total_sectors != null)
    parts.push(`Sector rank: ${r.sector_rank}/${r.total_sectors}`);

  return `Analyse this stock as a potential swing trade setup:\n\nSymbol: ${r.symbol}\n${parts.join("\n")}\n\nGive a concise assessment: setup quality, entry criteria, key risks, and whether this is worth acting on now.`;
}
