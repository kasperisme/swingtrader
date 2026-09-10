import { PageSkeleton, SkeletonMasthead, SkeletonRows } from "@/components/page-skeleton";

/** Covers the whole signed-in surface: workspace, ops, attribution, trades,
 *  agents, api-keys, profile. Every one of them reads per request. */
export default function Loading() {
  return (
    <PageSkeleton className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6">
      <SkeletonMasthead />
      <div className="mt-8">
        <SkeletonRows n={7} h="h-16" />
      </div>
    </PageSkeleton>
  );
}
