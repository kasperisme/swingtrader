/**
 * Shared screening Results filter state (REST-style keys, persisted in localStorage).
 */

export const NOTE_STAGE_NONE = "__none__";

export type NoteHighlightedFilter = "any" | "yes" | "no";
/** Row has a persisted workflow note row (any fields), vs no DB note yet. */
export type HasRowNoteFilter = "any" | "yes" | "no";
export type NoteCommentFilter = "any" | "with" | "without";
export type ActivePositionFilter = "any" | "yes" | "no";
/** Whether to constrain `note.stage` to being empty or non-empty. */
export type NoteStageEmptyFilter = "any" | "yes" | "no";

/** Concrete `ScanRowNote.status` values (no synthetic "all"). */
export type ScreeningStatusValue =
  | "active"
  | "dismissed"
  | "watchlist"
  | "pipeline";

export const SCREENING_STATUS_VALUES: ScreeningStatusValue[] = [
  "active",
  "dismissed",
  "watchlist",
  "pipeline",
];

export interface ScreeningsFilters {
  symbolContains: string;
  /** Allowed statuses; empty array = no constraint. Multi-select Equals. */
  statusIn: ScreeningStatusValue[];
  /** Rejected statuses; empty array = no constraint. Multi-select Not-equal. */
  statusNotIn: ScreeningStatusValue[];
  hasRowNote: HasRowNoteFilter;
  noteHighlighted: NoteHighlightedFilter;
  noteComment: NoteCommentFilter;
  activePosition: ActivePositionFilter;
  /** Allowed stages; empty array = no constraint. */
  noteStageIn: string[];
  /** Rejected stages; empty array = no constraint. */
  noteStageNotIn: string[];
  /** Constrain whether the stage is empty (no value) — independent of in/notIn. */
  noteStageEmpty: NoteStageEmptyFilter;
  notePriorityMin: string;
  notePriorityMax: string;
  notePriorityGt: string;
  notePriorityLt: string;
  notePriorityEq: string;
  /** Reject rows where note priority equals this value. */
  notePriorityNeq: string;
  /** Include rows whose tags contain ANY of these (OR-match). */
  noteTagsAny: string[];
  /** Reject rows whose tags contain ANY of these (OR-match). */
  noteTagsNone: string[];
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
  symbolContains: "",
  statusIn: [],
  statusNotIn: [],
  hasRowNote: "any",
  noteHighlighted: "any",
  noteComment: "any",
  activePosition: "any",
  noteStageIn: [],
  noteStageNotIn: [],
  noteStageEmpty: "any",
  notePriorityMin: "",
  notePriorityMax: "",
  notePriorityGt: "",
  notePriorityLt: "",
  notePriorityEq: "",
  notePriorityNeq: "",
  noteTagsAny: [],
  noteTagsNone: [],
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

/**
 * Normalize a raw (possibly legacy) filters payload into the current shape.
 * Handles localStorage and `user_scheduled_screenings.scan_filters` rows
 * that were written before the multi-select model.
 */
export function normalizeScreeningsFilters(
  raw: unknown,
): ScreeningsFilters {
  const r = (raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {});
  const out: ScreeningsFilters = { ...DEFAULT_SCREENINGS_FILTERS };

  const str = (v: unknown): string => (typeof v === "string" ? v : "");
  const strArr = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  const strRec = (v: unknown): Record<string, string> => {
    if (!v || typeof v !== "object") return {};
    const out: Record<string, string> = {};
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      if (typeof val === "string") out[k] = val;
    }
    return out;
  };
  const boolRec = (v: unknown): Record<string, boolean> => {
    if (!v || typeof v !== "object") return {};
    const out: Record<string, boolean> = {};
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      if (typeof val === "boolean") out[k] = val;
    }
    return out;
  };
  const strArrRec = (v: unknown): Record<string, string[]> => {
    if (!v || typeof v !== "object") return {};
    const out: Record<string, string[]> = {};
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      const arr = strArr(val);
      if (arr.length) out[k] = arr;
    }
    return out;
  };

  out.symbolContains = str(r.symbolContains);

  // Legacy: single `status` field with optional "all" sentinel.
  const legacyStatus = str(r.status);
  const statusIn = strArr(r.statusIn).filter((s): s is ScreeningStatusValue =>
    SCREENING_STATUS_VALUES.includes(s as ScreeningStatusValue),
  );
  if (statusIn.length) {
    out.statusIn = statusIn;
  } else if (
    legacyStatus &&
    legacyStatus !== "all" &&
    SCREENING_STATUS_VALUES.includes(legacyStatus as ScreeningStatusValue)
  ) {
    out.statusIn = [legacyStatus as ScreeningStatusValue];
  }
  out.statusNotIn = strArr(r.statusNotIn).filter((s): s is ScreeningStatusValue =>
    SCREENING_STATUS_VALUES.includes(s as ScreeningStatusValue),
  );

  out.hasRowNote =
    r.hasRowNote === "yes" || r.hasRowNote === "no" ? r.hasRowNote : "any";
  out.noteHighlighted =
    r.noteHighlighted === "yes" || r.noteHighlighted === "no"
      ? r.noteHighlighted
      : "any";
  out.noteComment =
    r.noteComment === "with" || r.noteComment === "without"
      ? r.noteComment
      : "any";
  out.activePosition =
    r.activePosition === "yes" || r.activePosition === "no"
      ? r.activePosition
      : "any";

  // Legacy: single `noteStage` (or NOTE_STAGE_NONE sentinel for "is empty").
  const legacyStage = str(r.noteStage);
  const stageIn = strArr(r.noteStageIn);
  if (stageIn.length) {
    out.noteStageIn = stageIn;
  } else if (legacyStage && legacyStage !== NOTE_STAGE_NONE) {
    out.noteStageIn = [legacyStage];
  }
  out.noteStageNotIn = strArr(r.noteStageNotIn);
  if (
    r.noteStageEmpty === "yes" ||
    r.noteStageEmpty === "no" ||
    r.noteStageEmpty === "any"
  ) {
    out.noteStageEmpty = r.noteStageEmpty;
  } else if (legacyStage === NOTE_STAGE_NONE) {
    out.noteStageEmpty = "yes";
  }

  out.notePriorityMin = str(r.notePriorityMin);
  out.notePriorityMax = str(r.notePriorityMax);
  out.notePriorityGt = str(r.notePriorityGt);
  out.notePriorityLt = str(r.notePriorityLt);
  out.notePriorityEq = str(r.notePriorityEq);
  out.notePriorityNeq = str(r.notePriorityNeq);

  out.noteTagsAny = strArr(r.noteTagsAny);
  out.noteTagsNone = strArr(r.noteTagsNone);

  out.boolRequire = boolRec(r.boolRequire);
  out.boolReject = boolRec(r.boolReject);
  out.numMin = strRec(r.numMin);
  out.numMax = strRec(r.numMax);
  out.numGt = strRec(r.numGt);
  out.numLt = strRec(r.numLt);
  out.numNeq = strRec(r.numNeq);
  out.stringOneOf = strArrRec(r.stringOneOf);
  out.stringNoneOf = strArrRec(r.stringNoneOf);
  out.stringContains = strRec(r.stringContains);
  out.stringEquals = strRec(r.stringEquals);
  out.stringNotEquals = strRec(r.stringNotEquals);

  return out;
}

export function countScreeningsFilterRules(f: ScreeningsFilters): number {
  let n = 0;
  if (f.symbolContains?.trim()) n++;
  if (f.statusIn.length > 0) n++;
  if (f.statusNotIn.length > 0) n++;
  if (f.hasRowNote !== "any") n++;
  if (f.noteHighlighted !== "any") n++;
  if (f.noteComment !== "any") n++;
  if (f.activePosition !== "any") n++;
  if (f.noteStageIn.length > 0) n++;
  if (f.noteStageNotIn.length > 0) n++;
  if (f.noteStageEmpty !== "any") n++;
  if (f.notePriorityMin.trim()) n++;
  if (f.notePriorityMax.trim()) n++;
  if (f.notePriorityGt.trim()) n++;
  if (f.notePriorityLt.trim()) n++;
  if (f.notePriorityEq.trim()) n++;
  if (f.notePriorityNeq?.trim()) n++;
  if (f.noteTagsAny.length > 0) n++;
  if (f.noteTagsNone.length > 0) n++;
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
