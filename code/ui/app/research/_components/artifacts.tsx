import { Download, Lock } from "lucide-react";
import type { ResearchArtifact } from "@/app/actions/research";

function fmtBytes(n: number | null) {
  if (n == null) return null;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * The files behind the write-up.
 *
 * Rendered whether or not each one can be downloaded. An artifact that cannot
 * be shared is listed with the reason, because "the panel is built from
 * licensed vendor data" is something a replicator needs before they start —
 * and silently omitting it would leave the note citing a path that resolves to
 * nothing.
 */
export function Artifacts({ artifacts }: { artifacts: ResearchArtifact[] }) {
  if (artifacts.length === 0) return null;

  return (
    <section className="mt-16" aria-labelledby="artifacts">
      <h2
        id="artifacts"
        className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground"
      >
        Artifacts
      </h2>
      <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
        The files this write-up was computed from.
      </p>

      <ul className="mt-6 grid gap-5">
        {artifacts.map((a) => {
          const size = fmtBytes(a.bytes);
          return (
            <li
              key={a.name}
              className={`border-l-2 py-1 pl-5 ${
                a.available ? "border-l-amber-500/70" : "border-l-border"
              }`}
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                {a.available && a.public_url ? (
                  <a
                    href={a.public_url}
                    className="group inline-flex items-center gap-1.5 font-mono text-sm text-foreground underline decoration-amber-500/50 underline-offset-4 transition-colors hover:decoration-amber-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
                    download
                  >
                    <Download className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    {a.name}
                  </a>
                ) : (
                  <span className="inline-flex items-center gap-1.5 font-mono text-sm text-muted-foreground">
                    <Lock className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    {a.name}
                  </span>
                )}
                {size && (
                  <span className="font-mono text-[11px] tabular-nums text-muted-foreground/70">
                    {size}
                  </span>
                )}
              </div>

              <p className="mt-1.5 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
                {a.description}
              </p>
              {!a.available && a.reason && (
                <p className="mt-1.5 max-w-[68ch] text-sm leading-relaxed text-muted-foreground/80">
                  {a.reason}
                </p>
              )}
              {a.sha256 && (
                <p className="mt-1.5 break-all font-mono text-[11px] text-muted-foreground/60">
                  sha256 {a.sha256.slice(0, 32)}…
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
