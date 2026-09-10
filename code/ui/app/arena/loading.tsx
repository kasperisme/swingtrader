import { PageSkeleton, SkeletonMasthead, SkeletonRows } from "@/components/page-skeleton";

/** The arena reads a championship, then its standings — serially, and it cannot
 *  be cached, so this is the one route that was consistently 2.4s cold or warm. */
export default function Loading() {
  return (
    <PageSkeleton className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
      <SkeletonMasthead />
      <div className="mt-10">
        <SkeletonRows n={9} h="h-16" />
      </div>
    </PageSkeleton>
  );
}
