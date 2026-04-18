/** Shared Tailwind classes for desktop dropdown nav (server + client). */
export const navDropdownTriggerClass =
  "inline-flex cursor-pointer list-none items-center rounded-md bg-transparent px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&::-webkit-details-marker]:hidden";

export const navDropdownPanelClass =
  "absolute left-0 top-full z-30 mt-2 hidden min-w-[180px] rounded-lg border border-border bg-background/95 p-1.5 shadow-lg backdrop-blur group-open:block";

export const navDropdownItemClass =
  "block rounded-md px-2.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground";
