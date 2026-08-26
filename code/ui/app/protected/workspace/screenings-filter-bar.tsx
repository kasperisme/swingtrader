"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, Plus, Search, X } from "lucide-react";
import {
  DEFAULT_SCREENINGS_FILTERS,
  SCREENING_STATUS_VALUES,
  type ScreeningStatusValue,
  type ScreeningsFilters,
  countScreeningsFilterRules,
  type ActivePositionFilter,
} from "./screenings-filters-model";
import { MAX_CATEGORICAL_STRING_OPTIONS } from "./screenings-row-data";

type SetFilters = (f: ScreeningsFilters | ((prev: ScreeningsFilters) => ScreeningsFilters)) => void;

type FieldKind =
  | { kind: "wf_symbol" }
  | { kind: "wf_status" }
  | { kind: "wf_has_row_note" }
  | { kind: "wf_highlighted" }
  | { kind: "wf_comment" }
  | { kind: "wf_stage"; options: string[] }
  | { kind: "wf_priority" }
  | { kind: "wf_tags"; options: string[] }
  | { kind: "wf_active_position" }
  | { kind: "row_bool"; key: string }
  | { kind: "row_num"; key: string }
  | { kind: "row_str_cat"; key: string; options: string[] }
  | { kind: "row_str_free"; key: string };

type CatalogEntry = { group: string; id: string; label: string; sub?: string; field: FieldKind };

type WizardStep = "fields" | "ops" | "value";

function catalogEntries(
  noteStageOptions: string[],
  noteTagOptions: string[],
  boolKeys: string[],
  numKeys: string[],
  categoricalStringCols: { key: string; options: string[] }[],
  freeStringKeys: string[],
): CatalogEntry[] {
  const out: CatalogEntry[] = [];
  out.push({ group: "Symbol", id: "wf.symbol", label: "symbol", sub: "text", field: { kind: "wf_symbol" } });
  const wf = "Workflow notes";
  out.push({ group: wf, id: "wf.status", label: "status", sub: "varchar", field: { kind: "wf_status" } });
  out.push({
    group: wf,
    id: "wf.hasRowNote",
    label: "saved note",
    sub: "bool",
    field: { kind: "wf_has_row_note" },
  });
  out.push({ group: wf, id: "wf.highlighted", label: "highlighted", sub: "bool", field: { kind: "wf_highlighted" } });
  out.push({ group: wf, id: "wf.activePosition", label: "active position", sub: "bool", field: { kind: "wf_active_position" } });
  out.push({ group: wf, id: "wf.comment", label: "comment", sub: "text", field: { kind: "wf_comment" } });
  out.push({
    group: wf,
    id: "wf.stage",
    label: "stage",
    sub: "varchar",
    field: { kind: "wf_stage", options: noteStageOptions },
  });
  out.push({ group: wf, id: "wf.priority", label: "priority", sub: "number", field: { kind: "wf_priority" } });
  out.push({
    group: wf,
    id: "wf.tags",
    label: "tags",
    sub: "array",
    field: { kind: "wf_tags", options: noteTagOptions },
  });

  const rb = "Row data · boolean";
  for (const k of boolKeys) {
    out.push({ group: rb, id: `rb.${k}`, label: k, sub: "bool", field: { kind: "row_bool", key: k } });
  }
  const rn = "Row data · number";
  for (const k of numKeys) {
    out.push({ group: rn, id: `rn.${k}`, label: k, sub: "number", field: { kind: "row_num", key: k } });
  }
  const rs = "Row data · text";
  for (const { key, options } of categoricalStringCols) {
    out.push({
      group: rs,
      id: `rsc.${key}`,
      label: key,
      sub: `≤${MAX_CATEGORICAL_STRING_OPTIONS} values`,
      field: { kind: "row_str_cat", key, options },
    });
  }
  for (const key of freeStringKeys) {
    out.push({ group: rs, id: `rsf.${key}`, label: key, sub: "text", field: { kind: "row_str_free", key } });
  }
  return out;
}

type OpDef = { id: string; label: string; sym?: string };

function opsForField(f: FieldKind): OpDef[] {
  switch (f.kind) {
    case "wf_symbol":
      return [
        { id: "contains", label: "Contains", sym: "~~" },
        { id: "eq", label: "Equals", sym: "=" },
      ];
    case "wf_status":
      return [
        { id: "eq", label: "Equals", sym: "=" },
        { id: "neq", label: "Not equal", sym: "≠" },
      ];
    case "wf_has_row_note":
      return [
        { id: "true", label: "Is true", sym: "=" },
        { id: "false", label: "Is false", sym: "=" },
      ];
    case "wf_active_position":
      return [
        { id: "true", label: "Has active position", sym: "=" },
        { id: "false", label: "No active position", sym: "=" },
      ];
    case "wf_highlighted":
      return [
        { id: "true", label: "Is true", sym: "=" },
        { id: "false", label: "Is false", sym: "=" },
      ];
    case "wf_comment":
      return [
        { id: "with", label: "Has comment", sym: "≠" },
        { id: "without", label: "No comment", sym: "=" },
      ];
    case "wf_stage":
      return [
        { id: "eq", label: "Equals", sym: "=" },
        { id: "neq", label: "Not equal", sym: "≠" },
        { id: "empty", label: "Is empty", sym: "∅" },
        { id: "not_empty", label: "Is not empty", sym: "≠∅" },
      ];
    case "wf_priority":
      return [
        { id: "eq", label: "Equals", sym: "=" },
        { id: "neq", label: "Not equal", sym: "≠" },
        { id: "gt", label: "Greater than", sym: ">" },
        { id: "gte", label: "Greater or equal", sym: "≥" },
        { id: "lt", label: "Less than", sym: "<" },
        { id: "lte", label: "Less or equal", sym: "≤" },
      ];
    case "wf_tags":
      return [
        { id: "any", label: "Includes any of…", sym: "∋" },
        { id: "none", label: "Includes none of…", sym: "∌" },
      ];
    case "row_bool":
      return [
        { id: "true", label: "Is true", sym: "=" },
        { id: "false", label: "Is false", sym: "=" },
      ];
    case "row_num":
      return [
        { id: "eq", label: "Equals", sym: "=" },
        { id: "neq", label: "Not equal", sym: "≠" },
        { id: "gt", label: "Greater than", sym: ">" },
        { id: "gte", label: "Greater or equal", sym: "≥" },
        { id: "lt", label: "Less than", sym: "<" },
        { id: "lte", label: "Less or equal", sym: "≤" },
      ];
    case "row_str_cat":
      return [
        { id: "eq", label: "Equals", sym: "=" },
        { id: "neq", label: "Not equal", sym: "≠" },
      ];
    case "row_str_free":
      return [
        { id: "contains", label: "Contains", sym: "~~" },
        { id: "eq", label: "Equals", sym: "=" },
        { id: "neq", label: "Not equal", sym: "≠" },
      ];
    default:
      return [];
  }
}

/** True for ops whose value step is a multi-select checkbox list of options. */
function isMultiSelectOp(field: FieldKind, opId: string): boolean {
  if (field.kind === "wf_status" && (opId === "eq" || opId === "neq")) return true;
  if (field.kind === "wf_stage" && (opId === "eq" || opId === "neq")) return true;
  if (field.kind === "wf_tags" && (opId === "any" || opId === "none")) return true;
  if (field.kind === "row_str_cat" && (opId === "eq" || opId === "neq")) return true;
  return false;
}

/** Options list to render in the checkbox step for a multi-select op. */
function multiSelectOptions(field: FieldKind): string[] {
  if (field.kind === "wf_status") return [...SCREENING_STATUS_VALUES];
  if (field.kind === "wf_stage") return field.options;
  if (field.kind === "wf_tags") return field.options;
  if (field.kind === "row_str_cat") return field.options;
  return [];
}

function summarizeList(vals: string[]): string {
  if (vals.length === 1) return vals[0]!;
  return `(${vals.length} values)`;
}

function buildPills(filters: ScreeningsFilters, setFilters: SetFilters) {
  type Pill = { id: string; text: string; title?: string; remove: () => void };
  const pills: Pill[] = [];
  const patch = (fn: (p: ScreeningsFilters) => ScreeningsFilters) => setFilters(fn);

  if (filters.symbolContains?.trim()) {
    const v = filters.symbolContains.trim();
    pills.push({
      id: "sym",
      text: `symbol ~ ${v}`,
      remove: () => patch((p) => ({ ...p, symbolContains: "" })),
    });
  }
  if (filters.statusIn.length > 0) {
    pills.push({
      id: "st-in",
      text: `status = ${summarizeList(filters.statusIn)}`,
      title: filters.statusIn.join(", "),
      remove: () => patch((p) => ({ ...p, statusIn: [] })),
    });
  }
  if (filters.statusNotIn.length > 0) {
    pills.push({
      id: "st-nin",
      text: `status ≠ ${summarizeList(filters.statusNotIn)}`,
      title: filters.statusNotIn.join(", "),
      remove: () => patch((p) => ({ ...p, statusNotIn: [] })),
    });
  }
  if (filters.hasRowNote === "yes") {
    pills.push({
      id: "hrn-y",
      text: "saved note = true",
      title: "Only rows with a saved workflow note",
      remove: () => patch((p) => ({ ...p, hasRowNote: "any" })),
    });
  } else if (filters.hasRowNote === "no") {
    pills.push({
      id: "hrn-n",
      text: "saved note = false",
      title: "Only rows with no saved workflow note yet",
      remove: () => patch((p) => ({ ...p, hasRowNote: "any" })),
    });
  }
  if (filters.noteHighlighted === "yes") {
    pills.push({
      id: "hl-y",
      text: "highlighted = true",
      remove: () => patch((p) => ({ ...p, noteHighlighted: "any" })),
    });
  } else if (filters.noteHighlighted === "no") {
    pills.push({
      id: "hl-n",
      text: "highlighted = false",
      remove: () => patch((p) => ({ ...p, noteHighlighted: "any" })),
    });
  }
  if (filters.activePosition === "yes") {
    pills.push({
      id: "ap-y",
      text: "active position = true",
      remove: () => patch((p) => ({ ...p, activePosition: "any" })),
    });
  } else if (filters.activePosition === "no") {
    pills.push({
      id: "ap-n",
      text: "active position = false",
      remove: () => patch((p) => ({ ...p, activePosition: "any" })),
    });
  }
  if (filters.noteComment === "with") {
    pills.push({
      id: "cm-w",
      text: "comment is not empty",
      remove: () => patch((p) => ({ ...p, noteComment: "any" })),
    });
  } else if (filters.noteComment === "without") {
    pills.push({
      id: "cm-o",
      text: "comment is empty",
      remove: () => patch((p) => ({ ...p, noteComment: "any" })),
    });
  }
  if (filters.noteStageEmpty === "yes") {
    pills.push({
      id: "sg-empty",
      text: "stage is empty",
      remove: () => patch((p) => ({ ...p, noteStageEmpty: "any" })),
    });
  } else if (filters.noteStageEmpty === "no") {
    pills.push({
      id: "sg-nonempty",
      text: "stage is not empty",
      remove: () => patch((p) => ({ ...p, noteStageEmpty: "any" })),
    });
  }
  if (filters.noteStageIn.length > 0) {
    pills.push({
      id: "sg-in",
      text: `stage = ${summarizeList(filters.noteStageIn)}`,
      title: filters.noteStageIn.join(", "),
      remove: () => patch((p) => ({ ...p, noteStageIn: [] })),
    });
  }
  if (filters.noteStageNotIn.length > 0) {
    pills.push({
      id: "sg-nin",
      text: `stage ≠ ${summarizeList(filters.noteStageNotIn)}`,
      title: filters.noteStageNotIn.join(", "),
      remove: () => patch((p) => ({ ...p, noteStageNotIn: [] })),
    });
  }
  const pq = (s: string) => s.trim();
  if (pq(filters.notePriorityEq)) {
    pills.push({
      id: "pr-eq",
      text: `priority = ${pq(filters.notePriorityEq)}`,
      remove: () =>
        patch((p) => ({ ...p, notePriorityEq: "", notePriorityMin: "", notePriorityMax: "" })),
    });
  } else {
    if (pq(filters.notePriorityGt)) {
      pills.push({
        id: "pr-gt",
        text: `priority > ${pq(filters.notePriorityGt)}`,
        remove: () => patch((p) => ({ ...p, notePriorityGt: "" })),
      });
    }
    if (pq(filters.notePriorityLt)) {
      pills.push({
        id: "pr-lt",
        text: `priority < ${pq(filters.notePriorityLt)}`,
        remove: () => patch((p) => ({ ...p, notePriorityLt: "" })),
      });
    }
    if (pq(filters.notePriorityMin)) {
      pills.push({
        id: "pr-ge",
        text: `priority ≥ ${pq(filters.notePriorityMin)}`,
        remove: () => patch((p) => ({ ...p, notePriorityMin: "" })),
      });
    }
    if (pq(filters.notePriorityMax)) {
      pills.push({
        id: "pr-le",
        text: `priority ≤ ${pq(filters.notePriorityMax)}`,
        remove: () => patch((p) => ({ ...p, notePriorityMax: "" })),
      });
    }
  }
  // Not-equal renders alongside range filters since they compose (e.g.
  // "1 ≤ priority ≤ 10 AND priority ≠ 5"). Skipped only when an exact-eq
  // is set, since neq can't coexist with eq (the apply handler clears it).
  if (!pq(filters.notePriorityEq) && pq(filters.notePriorityNeq ?? "")) {
    pills.push({
      id: "pr-neq",
      text: `priority ≠ ${pq(filters.notePriorityNeq ?? "")}`,
      remove: () => patch((p) => ({ ...p, notePriorityNeq: "" })),
    });
  }
  if (filters.noteTagsAny.length > 0) {
    pills.push({
      id: "tag-any",
      text:
        filters.noteTagsAny.length === 1
          ? `tags includes ${filters.noteTagsAny[0]}`
          : `tags includes any (${filters.noteTagsAny.length})`,
      title: filters.noteTagsAny.join(", "),
      remove: () => patch((p) => ({ ...p, noteTagsAny: [] })),
    });
  }
  if (filters.noteTagsNone.length > 0) {
    pills.push({
      id: "tag-none",
      text:
        filters.noteTagsNone.length === 1
          ? `tags excludes ${filters.noteTagsNone[0]}`
          : `tags excludes (${filters.noteTagsNone.length})`,
      title: filters.noteTagsNone.join(", "),
      remove: () => patch((p) => ({ ...p, noteTagsNone: [] })),
    });
  }
  for (const [k, on] of Object.entries(filters.boolRequire)) {
    if (on) {
      pills.push({
        id: `br-${k}`,
        text: `${k} = true`,
        remove: () =>
          patch((p) => {
            const { [k]: _, ...rest } = p.boolRequire;
            return { ...p, boolRequire: rest };
          }),
      });
    }
  }
  for (const [k, on] of Object.entries(filters.boolReject)) {
    if (on) {
      pills.push({
        id: `brj-${k}`,
        text: `${k} = false`,
        remove: () =>
          patch((p) => {
            const { [k]: _, ...rest } = p.boolReject;
            return { ...p, boolReject: rest };
          }),
      });
    }
  }
  for (const [k, v] of Object.entries(filters.numGt)) {
    if (!pq(v)) continue;
    pills.push({
      id: `ngt-${k}`,
      text: `${k} > ${pq(v)}`,
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.numGt;
          return { ...p, numGt: rest };
        }),
    });
  }
  for (const [k, v] of Object.entries(filters.numLt)) {
    if (!pq(v)) continue;
    pills.push({
      id: `nlt-${k}`,
      text: `${k} < ${pq(v)}`,
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.numLt;
          return { ...p, numLt: rest };
        }),
    });
  }
  for (const [k, v] of Object.entries(filters.numMin)) {
    if (!pq(v)) continue;
    const maxV = pq(filters.numMax[k] ?? "");
    if (maxV && maxV === pq(v)) continue;
    pills.push({
      id: `nge-${k}`,
      text: `${k} ≥ ${pq(v)}`,
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.numMin;
          return { ...p, numMin: rest };
        }),
    });
  }
  for (const [k, v] of Object.entries(filters.numMax)) {
    if (!pq(v)) continue;
    const minV = pq(filters.numMin[k] ?? "");
    if (minV && minV === pq(v)) continue;
    pills.push({
      id: `nle-${k}`,
      text: `${k} ≤ ${pq(v)}`,
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.numMax;
          return { ...p, numMax: rest };
        }),
    });
  }
  for (const [k, minS] of Object.entries(filters.numMin)) {
    const maxS = filters.numMax[k];
    if (!pq(minS) || !maxS || pq(minS) !== pq(maxS)) continue;
    pills.push({
      id: `neq-${k}`,
      text: `${k} = ${pq(minS)}`,
      remove: () =>
        patch((p) => {
          const { [k]: r1, ...restMin } = p.numMin;
          const { [k]: r2, ...restMax } = p.numMax;
          return { ...p, numMin: restMin, numMax: restMax };
        }),
    });
  }
  for (const [k, v] of Object.entries(filters.numNeq ?? {})) {
    if (!pq(v)) continue;
    pills.push({
      id: `nne-${k}`,
      text: `${k} ≠ ${pq(v)}`,
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.numNeq;
          return { ...p, numNeq: rest };
        }),
    });
  }
  for (const [k, vals] of Object.entries(filters.stringOneOf)) {
    if (!vals.length) continue;
    const label = vals.length === 1 ? `${k} = ${vals[0]}` : `${k} = (${vals.length} values)`;
    pills.push({
      id: `so-${k}`,
      text: label,
      title: vals.join(", "),
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.stringOneOf;
          return { ...p, stringOneOf: rest };
        }),
    });
  }
  for (const [k, v] of Object.entries(filters.stringContains)) {
    if (!pq(v)) continue;
    pills.push({
      id: `sc-${k}`,
      text: `${k} contains "${pq(v).slice(0, 24)}${pq(v).length > 24 ? "…" : ""}"`,
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.stringContains;
          return { ...p, stringContains: rest };
        }),
    });
  }
  for (const [k, v] of Object.entries(filters.stringEquals)) {
    if (!pq(v)) continue;
    pills.push({
      id: `se-${k}`,
      text: `${k} = "${pq(v).slice(0, 20)}${pq(v).length > 20 ? "…" : ""}"`,
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.stringEquals;
          return { ...p, stringEquals: rest };
        }),
    });
  }
  for (const [k, vals] of Object.entries(filters.stringNoneOf ?? {})) {
    if (!vals.length) continue;
    const label = vals.length === 1 ? `${k} ≠ ${vals[0]}` : `${k} ≠ (${vals.length} values)`;
    pills.push({
      id: `sno-${k}`,
      text: label,
      title: vals.join(", "),
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.stringNoneOf;
          return { ...p, stringNoneOf: rest };
        }),
    });
  }
  for (const [k, v] of Object.entries(filters.stringNotEquals ?? {})) {
    if (!pq(v)) continue;
    pills.push({
      id: `sne-${k}`,
      text: `${k} ≠ "${pq(v).slice(0, 20)}${pq(v).length > 20 ? "…" : ""}"`,
      remove: () =>
        patch((p) => {
          const { [k]: _, ...rest } = p.stringNotEquals;
          return { ...p, stringNotEquals: rest };
        }),
    });
  }
  return pills;
}

// Pills-only bar — shown inside the collapsible filters panel
export function ScreeningsFilterBar({
  filters,
  setFilters,
}: {
  filters: ScreeningsFilters;
  setFilters: SetFilters;
}) {
  const pills = useMemo(() => buildPills(filters, setFilters), [filters, setFilters]);
  const activeCount = countScreeningsFilterRules(filters);

  if (pills.length === 0) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/25 dark:bg-muted/15 px-2 py-2 min-h-[2.75rem] transition-colors"
      role="status"
      aria-label="Active filters"
    >
      <Search className="w-4 h-4 text-muted-foreground shrink-0" aria-hidden />
      <div className="flex flex-wrap items-center gap-1.5 flex-1 min-w-0">
        {pills.map((pill) => (
          <span
            key={pill.id}
            className="inline-flex items-center gap-0.5 max-w-full rounded-full border border-border bg-background px-2 py-0.5 text-xs text-foreground shadow-sm"
            title={pill.title}
          >
            <span className="truncate max-w-[min(20rem,85vw)]">{pill.text}</span>
            <button
              type="button"
              onClick={() => pill.remove()}
              className="shrink-0 rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={`Remove filter ${pill.text}`}
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </span>
        ))}
      </div>
      {activeCount > 0 && (
        <button
          type="button"
          onClick={() => setFilters(() => ({ ...DEFAULT_SCREENINGS_FILTERS }))}
          className="shrink-0 text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2"
        >
          Clear all
        </button>
      )}
    </div>
  );
}

type AddFilterWidgetProps = {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  filters: ScreeningsFilters;
  setFilters: SetFilters;
  noteStageOptions: string[];
  noteTagOptions: string[];
  boolKeys: string[];
  numKeys: string[];
  categoricalStringCols: { key: string; options: string[] }[];
  freeStringKeys: string[];
};

// Compact trigger button (open=false) or full-width inline wizard (open=true).
// Place inside the tabs flex row with ml-auto; parent must conditionally hide
// sibling tabs when open so the wizard fills the entire row.
export function AddFilterWidget({
  open,
  onOpen,
  onClose,
  filters,
  setFilters,
  noteStageOptions,
  noteTagOptions,
  boolKeys,
  numKeys,
  categoricalStringCols,
  freeStringKeys,
}: AddFilterWidgetProps) {
  const [step, setStep] = useState<WizardStep>("fields");
  const [fieldQuery, setFieldQuery] = useState("");
  const [selectedEntry, setSelectedEntry] = useState<CatalogEntry | null>(null);
  const [selectedOp, setSelectedOp] = useState<OpDef | null>(null);
  const [valueDraft, setValueDraft] = useState("");
  const [catDraft, setCatDraft] = useState<Set<string>>(() => new Set());
  const rootRef = useRef<HTMLDivElement>(null);
  const portalRef = useRef<HTMLDivElement>(null);
  const [portalStyle, setPortalStyle] = useState<React.CSSProperties>({});

  const catalog = useMemo(
    () => catalogEntries(noteStageOptions, noteTagOptions, boolKeys, numKeys, categoricalStringCols, freeStringKeys),
    [noteStageOptions, noteTagOptions, boolKeys, numKeys, categoricalStringCols, freeStringKeys],
  );

  const filteredCatalog = useMemo(() => {
    const q = fieldQuery.trim().toLowerCase();
    if (!q) return catalog;
    return catalog.filter(
      (e) =>
        e.label.toLowerCase().includes(q) ||
        e.id.toLowerCase().includes(q) ||
        (e.sub?.toLowerCase().includes(q) ?? false),
    );
  }, [catalog, fieldQuery]);

  const grouped = useMemo(() => {
    const m = new Map<string, CatalogEntry[]>();
    for (const e of filteredCatalog) {
      const g = e.group;
      if (!m.has(g)) m.set(g, []);
      m.get(g)!.push(e);
    }
    return m;
  }, [filteredCatalog]);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      const t = e.target as Node;
      const insideRoot = rootRef.current?.contains(t);
      const insidePortal = portalRef.current?.contains(t);
      if (!insideRoot && !insidePortal) {
        onClose();
        resetWizard();
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open, onClose]);

  useLayoutEffect(() => {
    if (!open) return;
    const el = rootRef.current;
    if (!el) return;
    function measure() {
      if (!el) return;
      const r = el.getBoundingClientRect();
      setPortalStyle({
        position: "fixed",
        left: r.left,
        top: r.bottom + 1,
        width: Math.min(r.width, 448),
        zIndex: 50,
        // A modal Radix Dialog (e.g. the agent form) sets pointer-events:none on
        // everything outside its content. This portal lives on <body>, so without
        // re-enabling here the option buttons would be unclickable inside a dialog.
        pointerEvents: "auto",
      });
    }
    measure();
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open, step]);

  const resetWizard = useCallback(() => {
    setStep("fields");
    setFieldQuery("");
    setSelectedEntry(null);
    setSelectedOp(null);
    setValueDraft("");
    setCatDraft(new Set());
  }, []);

  const closeMenu = useCallback(() => {
    onClose();
    resetWizard();
  }, [onClose, resetWizard]);

  const applyFilter = useCallback(
    (apply: (p: ScreeningsFilters) => ScreeningsFilters) => {
      setFilters(apply);
      closeMenu();
    },
    [setFilters, closeMenu],
  );

  function onPickField(e: CatalogEntry) {
    const ops = opsForField(e.field);
    setSelectedEntry(e);
    setValueDraft("");
    setCatDraft(new Set());
    if (ops.length === 1) {
      setSelectedOp(ops[0]);
      setStep("value");
      return;
    }
    setSelectedOp(null);
    setStep("ops");
  }

  function onPickOp(op: OpDef) {
    if (!selectedEntry) return;
    if (selectedEntry.field.kind === "wf_stage" && op.id === "empty") {
      applyFilter((p) => ({ ...p, noteStageEmpty: "yes" }));
      return;
    }
    if (selectedEntry.field.kind === "wf_stage" && op.id === "not_empty") {
      applyFilter((p) => ({ ...p, noteStageEmpty: "no" }));
      return;
    }
    setSelectedOp(op);
    setStep("value");
    setValueDraft("");
    setCatDraft(new Set());
  }

  function commitValue() {
    if (!selectedEntry || !selectedOp) return;
    const f = selectedEntry.field;
    const op = selectedOp.id;

    if (f.kind === "wf_symbol") {
      const v = valueDraft.trim().toUpperCase();
      if (!v) return;
      applyFilter((p) => ({ ...p, symbolContains: v }));
      return;
    }
    if (f.kind === "wf_status") {
      if (catDraft.size === 0) return;
      const vals = [...catDraft].filter((s): s is ScreeningStatusValue =>
        SCREENING_STATUS_VALUES.includes(s as ScreeningStatusValue),
      );
      if (op === "neq") {
        applyFilter((p) => ({ ...p, statusNotIn: vals }));
      } else {
        applyFilter((p) => ({ ...p, statusIn: vals }));
      }
      return;
    }
    if (f.kind === "wf_has_row_note") {
      if (op === "true") applyFilter((p) => ({ ...p, hasRowNote: "yes" }));
      else applyFilter((p) => ({ ...p, hasRowNote: "no" }));
      return;
    }
    if (f.kind === "wf_active_position") {
      const v: ActivePositionFilter = op === "true" ? "yes" : "no";
      applyFilter((p) => ({ ...p, activePosition: v }));
      return;
    }
    if (f.kind === "wf_highlighted") {
      if (op === "true") applyFilter((p) => ({ ...p, noteHighlighted: "yes" }));
      else applyFilter((p) => ({ ...p, noteHighlighted: "no" }));
      return;
    }
    if (f.kind === "wf_comment") {
      applyFilter((p) => ({
        ...p,
        noteComment: op === "with" ? "with" : "without",
      }));
      return;
    }
    if (f.kind === "wf_stage") {
      if (catDraft.size === 0) return;
      const vals = [...catDraft];
      if (op === "neq") {
        applyFilter((p) => ({ ...p, noteStageNotIn: vals }));
      } else {
        applyFilter((p) => ({ ...p, noteStageIn: vals }));
      }
      return;
    }
    if (f.kind === "wf_priority") {
      const n = valueDraft.trim();
      if (!n || !Number.isFinite(parseFloat(n))) return;
      if (op === "eq") {
        applyFilter((p) => ({
          ...p,
          notePriorityEq: n,
          notePriorityMin: n,
          notePriorityMax: n,
          notePriorityGt: "",
          notePriorityLt: "",
          notePriorityNeq: "",
        }));
        return;
      }
      if (op === "neq") {
        // Not-equal can coexist with range filters (e.g. "1 ≤ priority ≤ 5
        // but not 3"), but obviously contradicts an exact-equal — so clear
        // the eq fields when setting neq.
        applyFilter((p) => ({
          ...p,
          notePriorityNeq: n,
          notePriorityEq: "",
        }));
        return;
      }
      if (op === "gt") applyFilter((p) => ({ ...p, notePriorityGt: n, notePriorityEq: "", notePriorityMin: "" }));
      if (op === "lt") applyFilter((p) => ({ ...p, notePriorityLt: n, notePriorityEq: "", notePriorityMax: "" }));
      if (op === "gte") applyFilter((p) => ({ ...p, notePriorityMin: n, notePriorityEq: "", notePriorityGt: "" }));
      if (op === "lte") applyFilter((p) => ({ ...p, notePriorityMax: n, notePriorityEq: "", notePriorityLt: "" }));
      return;
    }
    if (f.kind === "wf_tags") {
      if (catDraft.size === 0) return;
      const vals = [...catDraft];
      if (op === "none") {
        applyFilter((p) => ({ ...p, noteTagsNone: vals }));
      } else {
        applyFilter((p) => ({ ...p, noteTagsAny: vals }));
      }
      return;
    }
    if (f.kind === "row_bool") {
      const k = f.key;
      if (op === "true") {
        applyFilter((p) => {
          const { [k]: _r, ...br } = p.boolReject;
          return { ...p, boolRequire: { ...p.boolRequire, [k]: true }, boolReject: br };
        });
      } else {
        applyFilter((p) => {
          const { [k]: _q, ...bq } = p.boolRequire;
          return { ...p, boolReject: { ...p.boolReject, [k]: true }, boolRequire: bq };
        });
      }
      return;
    }
    if (f.kind === "row_num") {
      const k = f.key;
      const n = valueDraft.trim();
      if (!n || !Number.isFinite(parseFloat(n))) return;
      const strip = (rec: Record<string, string>, key: string) => {
        const { [key]: _, ...rest } = rec;
        return rest;
      };
      if (op === "eq") {
        applyFilter((p) => ({
          ...p,
          numMin: { ...strip(p.numMin, k), [k]: n },
          numMax: { ...strip(p.numMax, k), [k]: n },
          numGt: strip(p.numGt, k),
          numLt: strip(p.numLt, k),
          numNeq: strip(p.numNeq ?? {}, k),
        }));
        return;
      }
      if (op === "neq") {
        applyFilter((p) => ({
          ...p,
          numNeq: { ...strip(p.numNeq ?? {}, k), [k]: n },
          // Drop a contradictory exact-equal (eq is encoded as min==max).
          numMin:
            p.numMin[k] === p.numMax[k]
              ? strip(p.numMin, k)
              : p.numMin,
          numMax:
            p.numMin[k] === p.numMax[k]
              ? strip(p.numMax, k)
              : p.numMax,
        }));
        return;
      }
      if (op === "gt") {
        applyFilter((p) => ({
          ...p,
          numGt: { ...strip(p.numGt, k), [k]: n },
          numMin: strip(p.numMin, k),
          numMax: strip(p.numMax, k),
          numLt: strip(p.numLt, k),
        }));
      }
      if (op === "lt") {
        applyFilter((p) => ({
          ...p,
          numLt: { ...strip(p.numLt, k), [k]: n },
          numMin: strip(p.numMin, k),
          numMax: strip(p.numMax, k),
          numGt: strip(p.numGt, k),
        }));
      }
      if (op === "gte") {
        applyFilter((p) => ({
          ...p,
          numMin: { ...strip(p.numMin, k), [k]: n },
          numGt: strip(p.numGt, k),
        }));
      }
      if (op === "lte") {
        applyFilter((p) => ({
          ...p,
          numMax: { ...strip(p.numMax, k), [k]: n },
          numLt: strip(p.numLt, k),
        }));
      }
      return;
    }
    if (f.kind === "row_str_cat") {
      const k = f.key;
      if (catDraft.size === 0) return;
      const vals = [...catDraft];
      if (op === "neq") {
        applyFilter((p) => ({
          ...p,
          stringNoneOf: { ...p.stringNoneOf, [k]: vals },
        }));
        return;
      }
      applyFilter((p) => ({ ...p, stringOneOf: { ...p.stringOneOf, [k]: vals } }));
      return;
    }
    if (f.kind === "row_str_free") {
      const k = f.key;
      const v = valueDraft.trim();
      if (!v) return;
      if (op === "contains") {
        applyFilter((p) => ({ ...p, stringContains: { ...p.stringContains, [k]: v } }));
      } else if (op === "neq") {
        applyFilter((p) => ({
          ...p,
          stringNotEquals: { ...p.stringNotEquals, [k]: v },
        }));
      } else {
        applyFilter((p) => ({ ...p, stringEquals: { ...p.stringEquals, [k]: v } }));
      }
    }
  }

  const activeCount = countScreeningsFilterRules(filters);

  // Compact trigger button
  if (!open) {
    return (
      <button
        type="button"
        onClick={onOpen}
        className="ml-auto inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px rounded-t-md border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/30"
      >
        <Plus className="w-3.5 h-3.5" />
        {activeCount > 0 ? `Filters (${activeCount})` : "Add filter"}
      </button>
    );
  }

  // Expanded inline wizard — fills the entire tabs row
  return (
    <div ref={rootRef} className="relative flex-1 min-w-0 flex flex-col pb-px">
      {/* Inline header row — same height as tab buttons */}
      <div className="flex items-center gap-1.5 px-1 py-1 min-w-0">
        {step !== "fields" && (
          <button
            type="button"
            onClick={() => {
              if (selectedEntry && opsForField(selectedEntry.field).length > 1 && step === "value") {
                setStep("ops");
                setSelectedOp(null);
              } else {
                setStep("fields");
                setSelectedEntry(null);
                setSelectedOp(null);
              }
            }}
            className="shrink-0 rounded-md p-1 hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Back"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        )}

        {step === "fields" ? (
          <div className="flex-1 min-w-0 flex items-center gap-1.5 flex-wrap rounded-md border border-input bg-background pl-2.5 pr-2 py-1 focus-within:ring-1 focus-within:ring-ring">
            <Search className="w-3.5 h-3.5 text-muted-foreground pointer-events-none shrink-0" />
            {buildPills(filters, setFilters).map((pill) => (
              <span
                key={pill.id}
                title={pill.title}
                className="inline-flex items-center gap-0.5 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-foreground shrink-0"
              >
                <span className="truncate max-w-[8rem]">{pill.text}</span>
                <button
                  type="button"
                  onClick={() => pill.remove()}
                  className="shrink-0 rounded-full p-0.5 text-muted-foreground hover:text-foreground"
                  aria-label={`Remove filter ${pill.text}`}
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
            <input
              autoFocus
              placeholder="Add filter…"
              value={fieldQuery}
              onChange={(e) => setFieldQuery(e.target.value)}
              className="flex-1 min-w-[8rem] bg-transparent text-sm focus:outline-none"
            />
          </div>
        ) : (
          <span className="flex-1 text-sm font-medium truncate min-w-0">
            {selectedEntry?.label}
            {selectedOp && (
              <span className="text-muted-foreground font-normal"> · {selectedOp.label}</span>
            )}
          </span>
        )}

        <button
          type="button"
          onClick={closeMenu}
          className="shrink-0 rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Close filter"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {typeof document !== "undefined" && createPortal(
        // data-filter-portal lets a surrounding Radix overlay (e.g. the agent
        // form Dialog) recognise clicks in this body-level portal as "inside",
        // so picking a filter option doesn't dismiss the overlay.
        <div ref={portalRef} data-filter-portal="" style={portalStyle}>
          <div className="rounded-lg border border-border bg-popover text-popover-foreground shadow-lg ring-1 ring-black/5 dark:ring-white/10">
          {step === "fields" && (
            <div className="flex flex-col max-h-80">
              <div className="overflow-y-auto p-1">
                {filteredCatalog.length === 0 ? (
                  <p className="px-2 py-4 text-sm text-muted-foreground text-center">No matching fields</p>
                ) : (
                  [...grouped.entries()].map(([group, entries]) => (
                    <div key={group} className="mb-2 last:mb-0">
                      <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                        {group}
                      </p>
                      <ul className="space-y-0.5">
                        {entries.map((e) => (
                          <li key={e.id}>
                            <button
                              type="button"
                              onClick={() => onPickField(e)}
                              className="w-full flex items-baseline justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted/80 focus:outline-none focus-visible:bg-muted"
                            >
                              <span className="font-medium">{e.label}</span>
                              {e.sub && (
                                <span className="text-[11px] text-muted-foreground shrink-0">{e.sub}</span>
                              )}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {step === "ops" && selectedEntry && (
            <div className="flex flex-col max-h-80">
              <div className="p-1">
                <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Comparison
                </p>
                <ul className="space-y-0.5">
                  {opsForField(selectedEntry.field).map((op) => (
                    <li key={op.id}>
                      <button
                        type="button"
                        onClick={() => onPickOp(op)}
                        className="w-full flex items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted/80 focus:outline-none focus-visible:bg-muted"
                      >
                        <span>{op.label}</span>
                        {op.sym && (
                          <span className="text-[11px] font-mono text-muted-foreground bg-muted/50 px-1 rounded">
                            {op.sym}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {step === "value" && selectedEntry && selectedOp && (
            <div className="flex flex-col max-h-96">
              <div className="p-3 flex flex-col gap-3">
                {selectedEntry.field.kind === "wf_symbol" && (
                  <input
                    autoFocus
                    type="text"
                    className="w-full rounded-md border border-input bg-background px-2 py-2 text-sm uppercase focus:outline-none focus:ring-1 focus:ring-ring"
                    placeholder="e.g. AAPL"
                    value={valueDraft}
                    onChange={(e) => setValueDraft(e.target.value.toUpperCase())}
                  />
                )}
                {selectedEntry.field.kind === "wf_priority" && (
                  <input
                    autoFocus
                    type="number"
                    className="w-full rounded-md border border-input bg-background px-2 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                    placeholder="Value"
                    value={valueDraft}
                    onChange={(e) => setValueDraft(e.target.value)}
                  />
                )}
                {/* Multi-select checkbox list for option fields (status / stage / tags / row categorical). */}
                {isMultiSelectOp(selectedEntry.field, selectedOp.id) && (
                  multiSelectOptions(selectedEntry.field).length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      {selectedEntry.field.kind === "wf_tags"
                        ? "No tags in this run yet."
                        : "No options available."}
                    </p>
                  ) : (
                    <div className="max-h-48 overflow-y-auto space-y-1 border border-border rounded-md p-2">
                      {multiSelectOptions(selectedEntry.field).map((opt) => (
                        <label key={opt} className="flex items-center gap-2 text-sm cursor-pointer">
                          <input
                            type="checkbox"
                            checked={catDraft.has(opt)}
                            onChange={(e) => {
                              const n = new Set(catDraft);
                              if (e.target.checked) n.add(opt);
                              else n.delete(opt);
                              setCatDraft(n);
                            }}
                            className="rounded"
                          />
                          <span className="truncate">{opt}</span>
                        </label>
                      ))}
                    </div>
                  )
                )}
                {(selectedEntry.field.kind === "row_num" ||
                  selectedEntry.field.kind === "row_str_free") && (
                  <input
                    autoFocus
                    type={selectedEntry.field.kind === "row_num" ? "number" : "text"}
                    className="w-full rounded-md border border-input bg-background px-2 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                    placeholder="Value"
                    value={valueDraft}
                    onChange={(e) => setValueDraft(e.target.value)}
                  />
                )}
                {(selectedEntry.field.kind === "wf_has_row_note" ||
                  selectedEntry.field.kind === "wf_highlighted" ||
                  selectedEntry.field.kind === "wf_active_position" ||
                  selectedEntry.field.kind === "wf_comment" ||
                  selectedEntry.field.kind === "row_bool") && (
                  <p className="text-xs text-muted-foreground">Apply this constraint with the button below.</p>
                )}

                <div className="flex justify-end gap-2 pt-1">
                  <button
                    type="button"
                    onClick={closeMenu}
                    className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => commitValue()}
                    className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Apply
                  </button>
                </div>
              </div>
            </div>
          )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
