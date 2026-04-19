"use client";

import { useEffect, useRef, useState } from "react";
import { PlusCircle, Check, AlertCircle, ChevronDown, Loader2, FolderPlus } from "lucide-react";
import {
  screeningsListRuns,
  screeningsAddTicker,
  screeningsCreateRun,
  type ScreeningRunSummary,
} from "@/app/actions/screenings";

interface AddToScreeningProps {
  ticker: string;
}

type Mode = "existing" | "new";
type Status = "idle" | "submitting" | "done" | "error";

function runLabel(r: ScreeningRunSummary): string {
  const date = r.scan_date.slice(0, 10);
  return r.source ? `${date} · ${r.source}` : date;
}

export function AddToScreening({ ticker }: AddToScreeningProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("existing");
  const [runs, setRuns] = useState<ScreeningRunSummary[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const popoverRef = useRef<HTMLDivElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);

  // Load runs when the popover opens.
  useEffect(() => {
    if (!open) return;
    setLoadingRuns(true);
    screeningsListRuns()
      .then((res) => {
        if (res.ok) {
          setRuns(res.data);
          if (res.data.length > 0 && selectedRunId === null) {
            setSelectedRunId(res.data[0]!.id);
          }
          // Default to "new" if there are no existing screenings.
          if (res.data.length === 0) setMode("new");
        }
      })
      .finally(() => setLoadingRuns(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Focus name input when switching to "new" mode.
  useEffect(() => {
    if (mode === "new" && open) {
      setTimeout(() => nameInputRef.current?.focus(), 50);
    }
  }, [mode, open]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (popoverRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [open]);

  // Reset transient state when ticker changes.
  useEffect(() => {
    setStatus("idle");
    setErrorMsg("");
  }, [ticker]);

  async function handleSubmit() {
    if (status === "submitting") return;
    setStatus("submitting");
    setErrorMsg("");

    let runId: number;

    if (mode === "new") {
      if (!newName.trim()) {
        setStatus("error");
        setErrorMsg("Enter a name for the new screening.");
        return;
      }
      const created = await screeningsCreateRun(newName.trim());
      if (!created.ok) {
        setStatus("error");
        setErrorMsg(created.error);
        setTimeout(() => setStatus("idle"), 3000);
        return;
      }
      runId = created.data.id;
      setRuns((prev) => [created.data, ...prev]);
      setSelectedRunId(runId);
      setNewName("");
      setMode("existing");
    } else {
      if (!selectedRunId) {
        setStatus("error");
        setErrorMsg("Select a screening first.");
        return;
      }
      runId = selectedRunId;
    }

    const res = await screeningsAddTicker(runId, ticker);
    if (res.ok) {
      setStatus("done");
      setTimeout(() => setStatus("idle"), 2000);
      setOpen(false);
    } else {
      setStatus("error");
      setErrorMsg(res.error);
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <div className="relative" ref={popoverRef}>
      <button
        type="button"
        onClick={() => { setOpen((o) => !o); setStatus("idle"); setErrorMsg(""); }}
        className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded border transition-colors ${
          status === "done"
            ? "border-emerald-500/50 text-emerald-500"
            : status === "error"
              ? "border-rose-400 text-rose-500"
              : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"
        }`}
        title="Add ticker to a screening"
      >
        {status === "done" ? (
          <Check className="w-3.5 h-3.5" />
        ) : status === "error" ? (
          <AlertCircle className="w-3.5 h-3.5" />
        ) : (
          <PlusCircle className="w-3.5 h-3.5" />
        )}
        {status === "done" ? "Added" : status === "error" ? "Failed" : "Add to screening"}
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-[60] min-w-[270px] rounded-md border border-border bg-popover p-3 shadow-md text-sm">
          <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-2.5">
            Add <span className="font-mono text-foreground">{ticker}</span> to screening
          </p>

          {/* Mode tabs */}
          <div className="flex rounded-md border border-border overflow-hidden mb-3 text-[11px]">
            <button
              type="button"
              onClick={() => setMode("existing")}
              className={`flex-1 py-1 transition-colors ${
                mode === "existing" ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:bg-muted/50"
              }`}
            >
              Existing
            </button>
            <button
              type="button"
              onClick={() => setMode("new")}
              className={`flex-1 py-1 border-l border-border transition-colors ${
                mode === "new" ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:bg-muted/50"
              }`}
            >
              New screening
            </button>
          </div>

          {mode === "existing" ? (
            loadingRuns ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground py-1 mb-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
              </div>
            ) : runs.length === 0 ? (
              <p className="text-xs text-muted-foreground py-1 mb-2">
                No screenings yet.{" "}
                <button type="button" onClick={() => setMode("new")} className="underline">
                  Create one
                </button>
              </p>
            ) : (
              <select
                value={selectedRunId ?? ""}
                onChange={(e) => setSelectedRunId(Number(e.target.value))}
                className="w-full px-2 py-1.5 text-xs rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring mb-3"
              >
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {runLabel(r)}
                  </option>
                ))}
              </select>
            )
          ) : (
            <input
              ref={nameInputRef}
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleSubmit(); }}
              placeholder="Screening name…"
              className="w-full px-2 py-1.5 text-xs rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring mb-3 placeholder:text-muted-foreground"
            />
          )}

          {status === "error" && (
            <p className="text-xs text-rose-500 mb-2">{errorMsg}</p>
          )}

          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={status === "submitting" || (mode === "existing" && !selectedRunId && !loadingRuns && runs.length === 0)}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-foreground text-background text-xs font-medium disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {status === "submitting" ? (
              <><Loader2 className="w-3.5 h-3.5 animate-spin" /> {mode === "new" ? "Creating…" : "Adding…"}</>
            ) : mode === "new" ? (
              <><FolderPlus className="w-3.5 h-3.5" /> Create &amp; add {ticker}</>
            ) : (
              <><PlusCircle className="w-3.5 h-3.5" /> Add {ticker}</>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
