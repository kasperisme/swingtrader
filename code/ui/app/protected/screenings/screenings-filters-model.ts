/**
 * Shared screening Results filter state (REST-style keys, persisted in localStorage).
 */

export const NOTE_STAGE_NONE = "__none__";

export type NoteHighlightedFilter = "any" | "yes" | "no";
/** Row has a persisted workflow note row (any fields), vs no DB note yet. */
export type HasRowNoteFilter = "any" | "yes" | "no";
export type NoteCommentFilter = "any" | "with" | "without";

/** Matches `ScanRowNote.status` plus "all". */
export type ScreeningStatusFilter =
  | "active"
  | "dismissed"
  | "watchlist"
  | "pipeline"
  | "all";

export interface ScreeningsFilters {
  status: ScreeningStatusFilter;
  hasRowNote: HasRowNoteFilter;
  noteHighlighted: NoteHighlightedFilter;
  noteComment: NoteCommentFilter;
  noteStage: string;
  notePriorityMin: string;
  notePriorityMax: string;
  notePriorityGt: string;
  notePriorityLt: string;
  notePriorityEq: string;
  noteTagsAny: string[];
  boolRequire: Record<string, boolean>;
  /** When true, row value must be falsy (boolean columns). */
  boolReject: Record<string, boolean>;
  numMin: Record<string, string>;
  numMax: Record<string, string>;
  numGt: Record<string, string>;
  numLt: Record<string, string>;
  stringOneOf: Record<string, string[]>;
  stringContains: Record<string, string>;
  /** Exact match on `stringifyRowDataValueForFilter` (row string columns). */
  stringEquals: Record<string, string>;
}

export const DEFAULT_SCREENINGS_FILTERS: ScreeningsFilters = {
  status: "active",
  hasRowNote: "any",
  noteHighlighted: "any",
  noteComment: "any",
  noteStage: "",
  notePriorityMin: "",
  notePriorityMax: "",
  notePriorityGt: "",
  notePriorityLt: "",
  notePriorityEq: "",
  noteTagsAny: [],
  boolRequire: {},
  boolReject: {},
  numMin: {},
  numMax: {},
  numGt: {},
  numLt: {},
  stringOneOf: {},
  stringContains: {},
  stringEquals: {},
};

export function countScreeningsFilterRules(f: ScreeningsFilters): number {
  let n = 0;
  if (f.status !== "active") n++;
  if (f.hasRowNote !== "any") n++;
  if (f.noteHighlighted !== "any") n++;
  if (f.noteComment !== "any") n++;
  if (f.noteStage) n++;
  if (f.notePriorityMin.trim()) n++;
  if (f.notePriorityMax.trim()) n++;
  if (f.notePriorityGt.trim()) n++;
  if (f.notePriorityLt.trim()) n++;
  if (f.notePriorityEq.trim()) n++;
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
  for (const arr of Object.values(f.stringOneOf)) {
    if (arr && arr.length > 0) n++;
  }
  for (const s of Object.values(f.stringContains)) {
    if (s && String(s).trim()) n++;
  }
  for (const s of Object.values(f.stringEquals)) {
    if (s && String(s).trim()) n++;
  }
  return n;
}
