import { getTradersForAgent } from "@/lib/sanity/trader-link";

/**
 * The disclaimer that matters most on these pages.
 *
 * Every agent is named after a real, living or recently-living investor, and the
 * page around it is laid out like an athlete's record — a finishing position, a
 * career table, a win rate. That combination is exactly how a reader ends up
 * believing they are looking at Michael Burry's returns. They are not.
 *
 * It names the real person when the trader profile exists, because the reader
 * who most needs this line is the one who arrived searching for that name.
 *
 * Kept as prose in the muted register rather than a warning banner: it is a
 * statement of what the thing is, not a legal notice, and a yellow box would
 * read as boilerplate to be skipped.
 */
export async function NotTheTrader({
  agentName,
  agentSlug,
}: {
  agentName: string;
  agentSlug: string;
}) {
  const traders = await getTradersForAgent(agentSlug);
  // An agent can be modelled on more than one person, and the disclaimer has to
  // name all of them — the reader who most needs this line arrived searching for
  // one of those names, and a line that clears only the first is worse than
  // useless to whoever searched the second.
  const names = traders.map((t) => t.name);
  const listed =
    names.length === 0
      ? null
      : names.length === 1
        ? names[0]
        : `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
  // Each name carries its OWN possessive. "Fisher or O'Neil's record" reads as
  // only O'Neil's, which is exactly the misattribution this paragraph exists to
  // prevent.
  const owned = names.map((n) => `${n}\u2019s`);
  const possessive =
    owned.length === 0
      ? "any real investor\u2019s"
      : owned.length === 1
        ? owned[0]
        : `${owned.slice(0, -1).join(", ")} or ${owned[owned.length - 1]}`;

  return (
    <div className="border-l-2 border-l-border py-4 pl-5">
      <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        This is not {listed ?? "that investor"}
      </p>
      <p className="mt-2 max-w-[70ch] text-sm leading-relaxed text-muted-foreground">
        {/* Explicit space: JSX drops the one that follows an element when the
            text then wraps to the next line. */}
        <strong className="font-medium text-foreground">{agentName}</strong>{" "}
        is a cheap knock-off: a general-purpose language model handed a caricature of a
        public method and a narrow slice of one website&rsquo;s data. Nothing on
        this page reflects {possessive} actual record, holdings, opinions or
        skill, and none of it is endorsed by or connected to them. The
        resemblance stops at the name and a rough idea.
      </p>
      <p className="mt-2 max-w-[70ch] text-sm leading-relaxed text-muted-foreground">
        Treat every number here as an experiment in whether a model can use one
        particular dataset — not as a track record, a strategy, or evidence that
        the method it borrows from works.
      </p>
    </div>
  );
}
