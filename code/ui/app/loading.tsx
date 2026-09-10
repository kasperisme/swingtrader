import { PageSkeleton, SkeletonCards, SkeletonMasthead } from "@/components/page-skeleton";

/**
 * The catch-all boundary, and the one the LANDING page uses.
 *
 * A boundary at the root segment covers every route without a closer one. The
 * static pages under it (about, pricing, terms) are fully prefetched and commit
 * instantly, so in practice this is what `/` shows while its six sequential
 * reads resolve — the slowest navigation in the app at 2.8s warm, 15s cold.
 */
export default function Loading() {
  return (
    <PageSkeleton className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8">
      <SkeletonMasthead wide />
      <div className="mt-10">
        <SkeletonCards n={3} h="h-52" />
      </div>
      <div className="mt-8">
        <SkeletonCards n={6} h="h-32" />
      </div>
    </PageSkeleton>
  );
}
