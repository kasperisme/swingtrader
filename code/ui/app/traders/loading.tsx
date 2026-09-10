import { PageSkeleton, SkeletonCards, SkeletonMasthead } from "@/components/page-skeleton";

export default function Loading() {
  return (
    <PageSkeleton className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
      <SkeletonMasthead />
      <div className="mt-10">
        <SkeletonCards n={6} h="h-32" cols="sm:grid-cols-2" />
      </div>
    </PageSkeleton>
  );
}
