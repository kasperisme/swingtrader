"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { chartWorkspaceNoteSave } from "@/app/actions/chart-workspace";

interface TickerNoteEditorProps {
  ticker: string;
  initialNote: string;
  onNoteChange?: (note: string) => void;
}

export function TickerNoteEditor({ ticker, initialNote, onNoteChange }: TickerNoteEditorProps) {
  const [note, setNote] = useState(initialNote);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef(initialNote);

  useEffect(() => {
    setNote(initialNote);
    lastSavedRef.current = initialNote;
  }, [ticker, initialNote]);

  const save = useCallback(async (value: string) => {
    if (value === lastSavedRef.current) return;
    setSaving(true);
    setSaved(false);
    await chartWorkspaceNoteSave(ticker, value);
    lastSavedRef.current = value;
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }, [ticker]);

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const v = e.target.value;
    setNote(v);
    onNoteChange?.(v);
    setSaved(false);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => void save(v), 900);
  }

  function handleBlur() {
    if (timerRef.current) clearTimeout(timerRef.current);
    void save(note);
  }

  return (
    <div className="relative flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Note</span>
        {saving && <Loader2 className="w-2.5 h-2.5 animate-spin text-muted-foreground" />}
        {!saving && saved && <Check className="w-2.5 h-2.5 text-emerald-500" />}
      </div>
      <textarea
        value={note}
        onChange={handleChange}
        onBlur={handleBlur}
        placeholder={`Notes on ${ticker}…`}
        rows={3}
        className="w-full text-xs bg-muted/40 border border-input rounded-md px-2.5 py-2 placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring resize-none"
      />
    </div>
  );
}
