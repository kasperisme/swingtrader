import { PageSkeleton, SkeletonMasthead, SkeletonRows } from "@/components/page-skeleton";

/** Covers the directory and every /quote/<symbol>. The symbol pages are the
 *  heaviest reads in the app (bar series, relationship graph, priced-in). */
export default function Loading() {
  return (
    <PageSkeleton className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
      <SkeletonMasthead />
      <div className="mt-8">
        <SkeletonRows n={5} h="h-20" />
      </div>
    </PageSkeleton>
  );
}
