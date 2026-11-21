import { PageSkeleton, SkeletonMasthead, SkeletonRows } from "@/components/page-skeleton";

/** Covers /correction and every /correction/<ticker>. */
export default function Loading() {
  return (
    <PageSkeleton className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
      <SkeletonMasthead />
      <div className="mt-8">
        <SkeletonRows n={4} h="h-24" />
      </div>
    </PageSkeleton>
  );
}
