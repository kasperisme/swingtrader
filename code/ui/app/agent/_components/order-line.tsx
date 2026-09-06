import Link from "next/link";
import type { ArenaOrder } from "@/app/actions/arena";
import {
  ORDER_TONE,
  fmtDate,
  fmtMoney,
  fmtSignedMoney,
  orderVerb,
  toneFor,
} from "./format";

/**
 * One order on the tape.
 *
 * Refused orders are shown with their reason rather than hidden: what an agent
 * TRIED to do and was not allowed to do is part of the record, and a log that
 * quietly drops them reads as if every intent became a trade.
 *
 * `showDate` is off inside a session block, where the date is already the
 * heading, and on in a flat log where it is the only anchor.
 */
export function OrderLine({
  order: o,
  showDate = true,
}: {
  order: ArenaOrder;
  showDate?: boolean;
}) {
  const verb = orderVerb(o);
  return (
    <div className="py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-xs tabular-nums">
        {showDate && (
          // The SESSION the order belongs to, not when the row was written. In a
          // replay `submitted_at` is the wall-clock time the backtest ran, so
          // using it would stamp 46 sessions of trades with the same evening.
          <span className="text-muted-foreground">
            {fmtDate(o.intended_for ?? o.submitted_at.slice(0, 10))}
          </span>
        )}
        <span className={`font-medium ${verb.tone}`}>{verb.label}</span>
        <Link
          href={`/quote/${o.ticker}`}
          className="font-medium hover:text-amber-600 dark:hover:text-amber-500"
        >
          {o.ticker}
        </Link>
        <span className="text-muted-foreground">
          ×{Math.round(o.quantity).toLocaleString()}
        </span>
        {o.fill_price != null && (
          <span className="text-muted-foreground">@ {fmtMoney(o.fill_price, 2)}</span>
        )}
        <span className={`uppercase tracking-wide ${ORDER_TONE[o.status]}`}>
          {o.status}
        </span>
        {o.realized_pnl != null && (
          <span className={`font-medium ${toneFor(o.realized_pnl)}`}>
            {fmtSignedMoney(o.realized_pnl)}
          </span>
        )}
        {o.conviction != null && (
          <span className="text-muted-foreground/70">
            conviction {o.conviction}
          </span>
        )}
      </div>
      {o.reject_reason ? (
        <p className="mt-1.5 max-w-[72ch] text-xs leading-relaxed text-rose-600/90 dark:text-rose-500/90">
          {o.reject_reason}
        </p>
      ) : (
        o.thesis && (
          <p className="mt-1.5 max-w-[72ch] text-xs leading-relaxed text-muted-foreground">
            {o.thesis}
          </p>
        )
      )}
    </div>
  );
}
