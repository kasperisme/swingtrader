import { PageSkeleton, SkeletonMasthead, SkeletonRows } from "@/components/page-skeleton";

/** Covers /agent/<slug> and /agent/<slug>/<season>. */
export default function Loading() {
  return (
    <PageSkeleton className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
      <SkeletonMasthead />
      <div className="mt-10">
        <SkeletonRows n={7} h="h-16" />
      </div>
    </PageSkeleton>
  );
}
