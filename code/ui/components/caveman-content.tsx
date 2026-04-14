"use client";

import { PortableText } from "@portabletext/react";
import { portableTextComponents } from "@/lib/sanity/portable-text-components";
import { useCavemanMode } from "@/lib/caveman-mode";

type Props = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  body: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  cavemanBody?: any[];
  emptyFallback?: string;
};

export function CavemanContent({ body, cavemanBody, emptyFallback }: Props) {
  const { isCaveman } = useCavemanMode();
  const hasCavemanVersion = Array.isArray(cavemanBody) && cavemanBody.length > 0;
  const activeBody = isCaveman && hasCavemanVersion ? cavemanBody : body;

  return (
    <>
      {isCaveman && (
        <div className="mb-6 flex items-start gap-2.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm">
          <span className="mt-0.5 shrink-0 text-base leading-none">🪨</span>
          {hasCavemanVersion ? (
            <span className="text-amber-700 dark:text-amber-400">
              <strong>UGH. CAVEMAN MODE ON.</strong> Less word. More understand.
            </span>
          ) : (
            <span className="text-amber-700 dark:text-amber-400">
              <strong>Caveman version not written yet.</strong> Showing full content.
            </span>
          )}
        </div>
      )}

      {activeBody?.length > 0 ? (
        <PortableText value={activeBody} components={portableTextComponents} />
      ) : (
        <p className="text-muted-foreground">{emptyFallback ?? "Content coming soon."}</p>
      )}
    </>
  );
}
