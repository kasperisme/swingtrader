import { PageSkeleton, SkeletonCards, SkeletonMasthead } from "@/components/page-skeleton";

/** Covers /briefings and /briefings/manage. */
export default function Loading() {
  return (
    <PageSkeleton className="mx-auto w-full max-w-5xl px-4 py-12 lg:px-6 lg:py-16">
      <SkeletonMasthead />
      <div className="mt-10">
        <SkeletonCards n={4} h="h-40" cols="sm:grid-cols-2" />
      </div>
    </PageSkeleton>
  );
}
