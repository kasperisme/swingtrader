import { PageSkeleton, SkeletonCards, SkeletonMasthead } from "@/components/page-skeleton";

export default function Loading() {
  return (
    <PageSkeleton className="mx-auto max-w-6xl px-4 pt-10 pb-20 sm:px-6 md:pt-14">
      <SkeletonMasthead wide />
      <div className="mt-10">
        <SkeletonCards n={6} h="h-44" />
      </div>
    </PageSkeleton>
  );
}
