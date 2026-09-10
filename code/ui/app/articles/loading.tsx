import { PageSkeleton, SkeletonCards, SkeletonMasthead } from "@/components/page-skeleton";

export default function Loading() {
  return (
    <PageSkeleton className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <SkeletonMasthead wide />
      <div className="mt-8">
        <SkeletonCards n={9} h="h-36" cols="sm:grid-cols-2 lg:grid-cols-3" />
      </div>
    </PageSkeleton>
  );
}
