"use client";

import type { ReactNode } from "react";
import { Bot, ChevronDown } from "lucide-react";

interface MobileAiChatSheetProps {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  title: string;
  hasIndicator?: boolean;
  children: ReactNode;
}

export function MobileAiChatSheet({
  open,
  onOpen,
  onClose,
  title,
  hasIndicator = false,
  children,
}: MobileAiChatSheetProps) {
  return (
    <>
      <button
        type="button"
        onClick={onOpen}
        className={`sm:hidden fixed right-4 z-30 flex items-center justify-center w-14 h-14 rounded-full shadow-lg border border-border transition-colors ${
          hasIndicator
            ? "bg-foreground text-background"
            : "bg-background text-foreground hover:bg-muted"
        }`}
        style={{ bottom: "calc(1.5rem + env(safe-area-inset-bottom, 0px))" }}
        aria-label="Open AI chat"
      >
        <Bot className="w-6 h-6" />
        {hasIndicator && (
          <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-emerald-500 border-2 border-background" />
        )}
      </button>

      {open && (
        <div className="sm:hidden fixed inset-0 z-40 bg-black/50" onClick={onClose} />
      )}

      <div
        className={`sm:hidden fixed inset-x-0 bottom-0 z-50 bg-background border-t border-border rounded-t-2xl shadow-2xl flex flex-col transition-transform duration-300 ease-out ${
          open ? "translate-y-0" : "translate-y-full"
        }`}
        style={{ height: "88dvh" }}
      >
        <div className="flex items-center justify-center pt-2.5 pb-1 shrink-0">
          <div className="w-10 h-1 rounded-full bg-border" />
        </div>
        <div className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0">
          <span className="font-mono font-bold text-sm">{title}</span>
          <button
            type="button"
            onClick={onClose}
            className="flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            aria-label="Close chat"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-hidden">{children}</div>
      </div>
    </>
  );
}
