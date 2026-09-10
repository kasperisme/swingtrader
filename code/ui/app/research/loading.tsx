import { PageSkeleton, SkeletonMasthead, SkeletonProse } from "@/components/page-skeleton";

export default function Loading() {
  return (
    <PageSkeleton className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
      <SkeletonMasthead />
      <div className="mt-10">
        <SkeletonProse n={10} />
      </div>
    </PageSkeleton>
  );
}
