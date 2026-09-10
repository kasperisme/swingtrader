"use client";

import Link from "next/link";
import { useLinkStatus } from "next/link";

/**
 * A nav link that admits it has been clicked.
 *
 * Even with a `loading.tsx` on every route, a click is not free: the router has
 * to fetch the destination's payload before it can swap in the boundary, which
 * on production measures 200–350ms of round trip. During that window the old
 * page is still on screen and completely unchanged, which is the window people
 * read as "nothing happened" and click again.
 *
 * `useLinkStatus` reports the pending state of the ENCLOSING `<Link>`, so the
 * indicator has to be a child of it — hence a wrapper component rather than a
 * hook call in the header, which is a server component anyway.
 */
export function PendingDot() {
  const { pending } = useLinkStatus();
  if (!pending) return null;
  return (
    <span
      aria-hidden
      // The delay is the point. A navigation that resolves in 80ms would
      // otherwise flash a dot on and off, which reads as a glitch rather than
      // as progress — worse than showing nothing. Below the threshold the dot
      // is mounted but still fully transparent, so only a click that actually
      // waits ever becomes visible.
      className="ml-1.5 inline-block size-1.5 shrink-0 rounded-full bg-current opacity-0 [animation:nav-pending-in_120ms_ease-out_140ms_forwards,nav-pending-pulse_1s_ease-in-out_260ms_infinite]"
    />
  );
}

export function NavLink({
  href,
  className,
  children,
  onClick,
  prefetch,
}: {
  href: string;
  className?: string;
  children: React.ReactNode;
  onClick?: () => void;
  prefetch?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`${className ?? ""} inline-flex items-center`}
      onClick={onClick}
      prefetch={prefetch}
    >
      {children}
      <PendingDot />
    </Link>
  );
}
