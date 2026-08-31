"use client";

import { createContext, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { Lock } from "lucide-react";

import { quotesGetPricedInMembers } from "@/app/actions/quotes";
import type { PricedInVote } from "@/lib/quote/priced-in-vote";
import {
  PricedInClaimByClaim,
  PricedInDeclines,
} from "./priced-in-deep-dive";
import { SECTION_LABEL } from "./priced-in-ui";

/**
 * The members-only wall on the public quote page, starting immediately after
 * "The price pays for".
 *
 * Free: the distribution, where the price sits in it, the counts, and the
 * reconstruction down to what the price pays for. Members: what it declines to
 * pay for, and the claim-by-claim evidence underneath.
 *
 * Two things shape the implementation. The quote page is statically prerendered
 * and never reads auth during render, so the gate resolves after mount — the
 * same trick the chart workspace uses. And the gated half is FETCHED here
 * rather than rendered by the server and hidden: markup that ships to everyone
 * behind a lock is not gated, and shipping it to a crawler while a reader sees
 * a lock is cloaking.
 *
 * The wall has two slots in different places on the page — the second column of
 * the pays-for grid, and the section below it — so access is resolved once in a
 * provider and read by both, rather than fetched twice.
 */

type MembersState = {
  loading: boolean;
  signedIn: boolean;
  vote: PricedInVote | null;
};

const MembersContext = createContext<MembersState>({
  loading: true,
  signedIn: false,
  vote: null,
});

export function PricedInMembersProvider({
  symbol,
  children,
}: {
  symbol: string;
  children: React.ReactNode;
}) {
  const [state, setState] = useState<MembersState>({
    loading: true,
    signedIn: false,
    vote: null,
  });

  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, signedIn: false, vote: null });
    void quotesGetPricedInMembers(symbol)
      .then((res) => {
        if (!cancelled) setState({ loading: false, ...res });
      })
      .catch(() => {
        if (!cancelled)
          setState({ loading: false, signedIn: false, vote: null });
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return (
    <MembersContext.Provider value={state}>{children}</MembersContext.Provider>
  );
}

/** A shimmer the size of what is coming, so the panel does not jump on resolve. */
function Placeholder({ lines }: { lines: number }) {
  return (
    <div className="animate-pulse space-y-2 motion-reduce:animate-none" aria-busy>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-3 rounded bg-muted"
          style={{ width: `${92 - (i % 3) * 14}%` }}
        />
      ))}
    </div>
  );
}

/**
 * The second column of the reconstruction grid, locked.
 *
 * Its ask is a text link, not a second button: the full CTA sits a few inches
 * below in the claim-by-claim slot, and two identical button pairs on one panel
 * read as a pop-up rather than an offer. Same destination either way.
 */
export function MembersDeclinesSlot({ price }: { price: number | null }) {
  const { loading, signedIn, vote } = useContext(MembersContext);

  if (loading) {
    return (
      <div>
        <p className={`mb-1.5 ${SECTION_LABEL}`}>It declines to pay for</p>
        <Placeholder lines={3} />
      </div>
    );
  }

  if (signedIn && vote) return <PricedInDeclines vote={vote} price={price} />;

  // self-start: the card hugs its own copy instead of stretching to the height
  // of the free column beside it, which reads as a broken cell.
  return (
    <div className="self-start rounded-lg border border-dashed border-border bg-muted/20 p-3">
      <p className={`mb-1.5 flex items-center gap-1.5 ${SECTION_LABEL}`}>
        <Lock className="h-3 w-3" aria-hidden />
        It declines to pay for
      </p>
      <p className="text-sm leading-snug text-muted-foreground">
        The other half of the reconstruction — the arguments the market is
        refusing to pay for — is for members.
      </p>
      <Link
        href="/auth/sign-up"
        className="mt-2 inline-flex items-center text-xs font-medium text-foreground underline decoration-border underline-offset-4 transition-colors hover:decoration-foreground"
      >
        Create a free account →
      </Link>
    </div>
  );
}

/**
 * The claim-by-claim deep dive, locked.
 *
 * This is where the ask goes: it is the most expensive thing behind the panel
 * to produce and the clearest reason to have an account, so the CTA names what
 * is on the other side rather than the plan.
 */
export function MembersClaimByClaimSlot({
  symbol,
  price,
  priceAtAsOf,
}: {
  symbol: string;
  price: number | null;
  priceAtAsOf: number | null;
}) {
  const { loading, signedIn, vote } = useContext(MembersContext);

  if (loading) {
    return (
      <div className="mt-4 border-t border-border pt-4">
        <p className={`mb-3 ${SECTION_LABEL}`}>Claim by claim</p>
        <Placeholder lines={5} />
      </div>
    );
  }

  if (signedIn && vote)
    return (
      <PricedInClaimByClaim
        vote={vote}
        price={price}
        priceAtAsOf={priceAtAsOf}
      />
    );

  return (
    <div className="mt-4 border-t border-border pt-4">
      <p className={`mb-3 ${SECTION_LABEL}`}>Claim by claim</p>
      <div className="rounded-lg border border-border bg-muted/20 px-4 py-5 text-center">
        <div className="mx-auto flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card">
          <Lock className="h-4 w-4 text-amber-500" aria-hidden />
        </div>
        <p className="mt-3 text-sm font-medium text-foreground">
          The assumptions behind {symbol}&rsquo;s price are for members
        </p>
        <p className="mx-auto mt-1 max-w-[52ch] text-xs leading-relaxed text-muted-foreground">
          Every claim the price is built on, ordered by how little of it the
          market has paid for yet — with the coverage for and against each one,
          and whether anything outside the news can settle it. Free account.
        </p>
        <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
          <Link
            href="/auth/sign-up"
            className="inline-flex items-center rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-90"
          >
            Create a free account
          </Link>
          <Link
            href="/auth/login"
            className="inline-flex items-center rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
          >
            Sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
