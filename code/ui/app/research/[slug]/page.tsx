import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft } from "lucide-react";
import {
  getResearchNote,
  listArtifactsForNote,
  listChartsForNote,
  listResearchNotes,
} from "@/app/actions/research";
import { Artifacts } from "../_components/artifacts";
import { NoteBody } from "../_components/note-body";
import { ResearchFigure } from "../_components/research-figure";
import { SITE_URL } from "@/lib/site";

const SITE = SITE_URL;

export async function generateStaticParams() {
  const notes = await listResearchNotes();
  return notes.map((n) => ({ slug: n.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const note = await getResearchNote(slug);
  if (!note) return { title: "Research" };
  return {
    title: note.title,
    description: note.summary ?? undefined,
    alternates: { canonical: `${SITE}/research/${slug}` },
  };
}

async function NoteArtifacts({ slug }: { slug: string }) {
  const artifacts = await listArtifactsForNote(slug);
  return <Artifacts artifacts={artifacts} />;
}

async function Figures({ slug }: { slug: string }) {
  const charts = await listChartsForNote(slug);
  if (charts.length === 0) return null;

  return (
    <section className="mt-16" aria-labelledby="figures">
      <h2
        id="figures"
        className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground"
      >
        Figures
      </h2>
      <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
        Each figure states the window it was drawn on. An amber rail means the
        chart was produced on the same data the search optimised over.
      </p>
      <div className="mt-8 grid gap-12">
        {charts.map((c, i) => (
          <ResearchFigure key={c.slug} chart={c} index={i} />
        ))}
      </div>
    </section>
  );
}

export default async function ResearchNotePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const note = await getResearchNote(slug);
  if (!note) notFound();

  return (
    <main className="min-h-[100dvh] px-4 py-14 sm:py-20">
      <div className="mx-auto w-full max-w-3xl">
        <Link
          href="/research"
          className="group inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none"
        >
          <ArrowLeft
            className="h-3.5 w-3.5 transition-transform group-hover:-translate-x-0.5"
            aria-hidden
          />
          Research
        </Link>

        <header className="mb-12 mt-8">
          <h1 className="text-3xl font-bold leading-[1.05] tracking-tighter sm:text-5xl">
            {note.title}
          </h1>
          <p className="mt-5 border-t pt-4 font-mono text-[11px] uppercase tracking-widest tabular-nums text-muted-foreground">
            Updated {new Date(note.updated_at).toLocaleDateString("en-GB", {
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </p>
        </header>

        <article>
          <NoteBody markdown={note.body_md} />
        </article>

        <Suspense
          fallback={
            <div className="mt-16 grid gap-12" aria-hidden>
              {Array.from({ length: 2 }, (_, i) => (
                <div key={i} className="h-72 animate-pulse rounded-sm bg-muted" />
              ))}
            </div>
          }
        >
          <Figures slug={slug} />
        </Suspense>

        <Suspense fallback={null}>
          <NoteArtifacts slug={slug} />
        </Suspense>

        <section className="mt-16 border-l-2 border-l-amber-500 py-1 pl-5">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-amber-600 dark:text-amber-500">
            Replicating this
          </h2>
          <p className="mt-3 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
            The configurations behind these results are published on the{" "}
            <Link
              href="/research"
              className="text-foreground underline decoration-amber-500/50 underline-offset-2 transition-colors hover:decoration-amber-500"
            >
              research index
            </Link>
            , each with its data window, pre-filter, cost model and the number of
            configurations searched. A result that cannot be re-derived from
            those inputs is a bug — say so.
          </p>
        </section>

        <p className="mt-16 border-t pt-5 text-xs leading-relaxed text-muted-foreground">
          Research, not investment advice.
        </p>
      </div>
    </main>
  );
}
