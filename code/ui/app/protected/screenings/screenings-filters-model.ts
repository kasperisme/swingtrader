/**
 * Shared screening Results filter state (REST-style keys, persisted in localStorage).
 */

export const NOTE_STAGE_NONE = "__none__";

export type NoteHighlightedFilter = "any" | "yes" | "no";
/** Row has a persisted workflow note row (any fields), vs no DB note yet. */
export type HasRowNoteFilter = "any" | "yes" | "no";
export type NoteCommentFilter = "any" | "with" | "without";
export type ActivePositionFilter = "any" | "yes" | "no";

/** Matches `ScanRowNote.status` plus "all". */
export type ScreeningStatusFilter =
  | "active"
  | "dismissed"
  | "watchlist"
  | "pipeline"
  | "all";

export interface ScreeningsFilters {
  status: ScreeningStatusFilter;
  symbolContains: string;
  hasRowNote: HasRowNoteFilter;
  noteHighlighted: NoteHighlightedFilter;
  noteComment: NoteCommentFilter;
  activePosition: ActivePositionFilter;
  noteStage: string;
  notePriorityMin: string;
  notePriorityMax: string;
  notePriorityGt: string;
  notePriorityLt: string;
  notePriorityEq: string;
  /** Reject rows where note priority equals this value. */
  notePriorityNeq: string;
  noteTagsAny: string[];
  boolRequire: Record<string, boolean>;
  /** When true, row value must be falsy (boolean columns). */
  boolReject: Record<string, boolean>;
  numMin: Record<string, string>;
  numMax: Record<string, string>;
  numGt: Record<string, string>;
  numLt: Record<string, string>;
  /** Reject rows where the numeric value equals this number. */
  numNeq: Record<string, string>;
  stringOneOf: Record<string, string[]>;
  /** Reject rows whose stringified value is in this list (categorical exclude). */
  stringNoneOf: Record<string, string[]>;
  stringContains: Record<string, string>;
  /** Exact match on `stringifyRowDataValueForFilter` (row string columns). */
  stringEquals: Record<string, string>;
  /** Reject rows whose stringified value matches this exactly. */
  stringNotEquals: Record<string, string>;
}

export const DEFAULT_SCREENINGS_FILTERS: ScreeningsFilters = {
  status: "all",
  symbolContains: "",
  hasRowNote: "any",
  noteHighlighted: "any",
  noteComment: "any",
  activePosition: "any",
  noteStage: "",
  notePriorityMin: "",
  notePriorityMax: "",
  notePriorityGt: "",
  notePriorityLt: "",
  notePriorityEq: "",
  notePriorityNeq: "",
  noteTagsAny: [],
  boolRequire: {},
  boolReject: {},
  numMin: {},
  numMax: {},
  numGt: {},
  numLt: {},
  numNeq: {},
  stringOneOf: {},
  stringNoneOf: {},
  stringContains: {},
  stringEquals: {},
  stringNotEquals: {},
};

export function countScreeningsFilterRules(f: ScreeningsFilters): number {
  let n = 0;
  if (f.status !== "all") n++;
  if (f.symbolContains?.trim()) n++;
  if (f.hasRowNote !== "any") n++;
  if (f.noteHighlighted !== "any") n++;
  if (f.noteComment !== "any") n++;
  if (f.activePosition !== "any") n++;
  if (f.noteStage) n++;
  if (f.notePriorityMin.trim()) n++;
  if (f.notePriorityMax.trim()) n++;
  if (f.notePriorityGt.trim()) n++;
  if (f.notePriorityLt.trim()) n++;
  if (f.notePriorityEq.trim()) n++;
  if (f.notePriorityNeq?.trim()) n++;
  if (f.noteTagsAny.length > 0) n++;
  for (const on of Object.values(f.boolRequire)) {
    if (on) n++;
  }
  for (const on of Object.values(f.boolReject)) {
    if (on) n++;
  }
  for (const s of Object.values(f.numMin)) {
    if (s && String(s).trim()) n++;
  }
  for (const s of Object.values(f.numMax)) {
    if (s && String(s).trim()) n++;
  }
  for (const s of Object.values(f.numGt)) {
    if (s && String(s).trim()) n++;
  }
  for (const s of Object.values(f.numLt)) {
    if (s && String(s).trim()) n++;
  }
  for (const s of Object.values(f.numNeq ?? {})) {
    if (s && String(s).trim()) n++;
  }
  for (const arr of Object.values(f.stringOneOf)) {
    if (arr && arr.length > 0) n++;
  }
  for (const arr of Object.values(f.stringNoneOf ?? {})) {
    if (arr && arr.length > 0) n++;
  }
  for (const s of Object.values(f.stringContains)) {
    if (s && String(s).trim()) n++;
  }
  for (const s of Object.values(f.stringEquals)) {
    if (s && String(s).trim()) n++;
  }
  for (const s of Object.values(f.stringNotEquals ?? {})) {
    if (s && String(s).trim()) n++;
  }
  return n;
}
