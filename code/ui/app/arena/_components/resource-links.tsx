import Link from "next/link";
import type { ArenaResource, ArenaToolSurface } from "@/app/actions/arena";

/**
 * The provenance layer: what an agent actually read, linked to the page that
 * publishes it.
 *
 * This is the point of the arena. An agent that says "the NIS Momentum board
 * flagged LH on volume" is only interesting if you can open that board and that
 * quote page and check. Every chip here is a real resource resolved from the
 * agent's own tool calls — never inferred from its prose, which is exactly the
 * part that could be wrong.
 */

const KIND_LABEL: Record<ArenaResource["kind"], string> = {
  screening: "Screening",
  article: "Article",
  ticker: "Quote",
  topic: "Topic",
};

/** One accent per resource kind so the eye can group them without reading. */
const KIND_CLASS: Record<ArenaResource["kind"], string> = {
  screening:
    "border-emerald-600/30 text-emerald-700 hover:border-emerald-600/60 hover:bg-emerald-600/10 dark:text-emerald-500",
  article:
    "border-sky-600/30 text-sky-700 hover:border-sky-600/60 hover:bg-sky-600/10 dark:text-sky-400",
  ticker:
    "border-amber-600/30 text-amber-700 hover:border-amber-600/60 hover:bg-amber-600/10 dark:text-amber-500",
  topic:
    "border-violet-600/30 text-violet-700 hover:border-violet-600/60 hover:bg-violet-600/10 dark:text-violet-400",
};

const KIND_ORDER: ArenaResource["kind"][] = ["screening", "topic", "article", "ticker"];

export function ResourceChips({
  resources,
  max = 10,
}: {
  resources: ArenaResource[];
  max?: number;
}) {
  if (!resources?.length) return null;

  // Screenings and topics first: they are the boards a decision rests on, and a
  // wall of ticker chips would otherwise bury them.
  const ordered = [...resources].sort(
    (a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind),
  );
  const shown = ordered.slice(0, max);
  const hidden = ordered.length - shown.length;

  return (
    <div className="mt-3">
      <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground/70">
        Consulted
      </p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {shown.map((r) => (
          <li key={`${r.kind}:${r.key}`}>
            <Link
              href={r.href}
              title={r.detail ? `${KIND_LABEL[r.kind]} · ${r.detail}` : KIND_LABEL[r.kind]}
              className={`inline-flex max-w-[34ch] items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] transition-colors ${KIND_CLASS[r.kind]}`}
            >
              <span className="opacity-60">{KIND_LABEL[r.kind]}</span>
              <span className="truncate font-medium">{r.label}</span>
            </Link>
          </li>
        ))}
        {hidden > 0 && (
          <li className="self-center font-mono text-[11px] text-muted-foreground/70">
            +{hidden} more
          </li>
        )}
      </ul>
    </div>
  );
}

/**
 * An agent's declared data surface — what it is allowed to read at all, and
 * where on the site the same data is published.
 *
 * Distinct from the chips above, which are what it *did* read. Both matter: the
 * surface is the experiment's design (this is the slice of data this agent
 * gets), the chips are the evidence for one day's decision.
 */
export function ToolSurface({ tools }: { tools: ArenaToolSurface[] | null }) {
  if (!tools?.length) return null;

  return (
    <ul className="mt-5 grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-2">
      {tools.map((t) => {
        const body = (
          <>
            <span className="flex items-baseline gap-1.5 font-medium">
              {t.label}
              {t.href && (
                <span
                  aria-hidden
                  className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground/60 transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-500"
                >
                  {t.href}
                </span>
              )}
            </span>
            <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
              {t.reads}
            </span>
          </>
        );
        return (
          <li key={t.name} className="bg-background p-3.5 text-sm">
            {t.href ? (
              <Link
                href={t.href}
                className="group block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {body}
              </Link>
            ) : (
              // Account tools and the FMP set have no public page of their own.
              // Rendered as plain text rather than a dead link.
              <div>{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The agent's cited-resource backlinks: everything its recent decisions have
 * actually rested on, ranked by how often it came up.
 */
export function CitedResources({
  resources,
}: {
  resources: (ArenaResource & { citations: number })[];
}) {
  if (!resources?.length) {
    return (
      <p className="mt-4 max-w-[62ch] text-sm text-muted-foreground">
        Nothing cited yet — this agent&rsquo;s decisions will link the screening
        boards, quote pages and articles they rest on as it makes them.
      </p>
    );
  }

  const groups = KIND_ORDER.map((kind) => ({
    kind,
    items: resources.filter((r) => r.kind === kind),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="mt-5 grid gap-5">
      {groups.map((g) => (
        <div key={g.kind}>
          <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground/70">
            {KIND_LABEL[g.kind]}
            <span className="ml-1.5 text-muted-foreground/50">{g.items.length}</span>
          </p>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {g.items.map((r) => (
              <li key={r.href}>
                <Link
                  href={r.href}
                  title={r.detail ?? undefined}
                  className={`inline-flex max-w-[40ch] items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] transition-colors ${KIND_CLASS[r.kind]}`}
                >
                  <span className="truncate font-medium">{r.label}</span>
                  {r.citations > 1 && (
                    <span className="opacity-60">×{r.citations}</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
