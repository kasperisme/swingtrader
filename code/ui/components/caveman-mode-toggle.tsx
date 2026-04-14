"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

export function CavemanModeToggle() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isActive = searchParams.get("caveman") === "1";

  const toggle = () => {
    const params = new URLSearchParams(searchParams.toString());
    if (isActive) {
      params.delete("caveman");
    } else {
      params.set("caveman", "1");
    }
    const query = params.toString();
    router.push(`${pathname}${query ? `?${query}` : ""}`);
  };

  return (
    <button
      onClick={toggle}
      title={isActive ? "Exit caveman mode" : "Enable caveman mode"}
      className={[
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        isActive
          ? "border-amber-500/50 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 dark:text-amber-400"
          : "border-border bg-background text-muted-foreground hover:border-amber-500/50 hover:text-amber-600 dark:hover:text-amber-400",
      ].join(" ")}
    >
      {isActive ? "🪨 Caveman mode ON" : "🪨 Caveman mode"}
    </button>
  );
}
