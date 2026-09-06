import Image from "next/image";

/**
 * A trader's portrait, or a designed mark when there is no licensable one.
 *
 * Most photographs of these people are Getty/Shutterstock stock; the only ones
 * we can lawfully use are the free-licensed portraits on Wikimedia Commons, and
 * they exist for five of the ten. So the fallback is not an error state — it is
 * the normal state for half the directory, and it has to look deliberate rather
 * than broken.
 *
 * The mark is the initials over a hue derived from the slug, so a given trader
 * is always the same colour on every surface and adding a new one needs no
 * decision. Deterministic rather than random: a mark that changes between the
 * card and the profile reads as a bug.
 */
function hueFor(slug: string): number {
  let h = 0;
  for (let i = 0; i < slug.length; i++) h = (h * 31 + slug.charCodeAt(i)) % 360;
  return h;
}

function initials(name: string): string {
  const parts = name.replace(/\(.*?\)/g, "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] ?? "" : "";
  return (first + last).toUpperCase();
}

export function Portrait({
  name,
  slug,
  url,
  alt,
  size = 56,
  className = "",
}: {
  name: string;
  slug: string;
  url?: string;
  alt?: string;
  size?: number;
  className?: string;
}) {
  const dim = { width: size, height: size };

  if (url) {
    return (
      <Image
        src={url}
        alt={alt || `Portrait of ${name}`}
        {...dim}
        className={`shrink-0 rounded-full object-cover ${className}`}
        // Sanity serves these; sizes are fixed and small, so no responsive set.
        unoptimized={false}
      />
    );
  }

  const hue = hueFor(slug);
  return (
    <span
      aria-hidden
      className={`flex shrink-0 select-none items-center justify-center rounded-full font-mono font-medium ${className}`}
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.34),
        // Low-chroma so nine of these in a column read as one family rather
        // than a paintbox, and legible on both themes without a second token.
        background: `hsl(${hue} 32% 92%)`,
        color: `hsl(${hue} 45% 32%)`,
        boxShadow: `inset 0 0 0 1px hsl(${hue} 30% 78%)`,
      }}
    >
      {initials(name)}
    </span>
  );
}
