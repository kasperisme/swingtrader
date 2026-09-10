import { PageSkeleton, SkeletonMasthead, SkeletonProse } from "@/components/page-skeleton";

/** Covers the index and every post — both are Sanity reads. */
export default function Loading() {
  return (
    <PageSkeleton className="mx-auto max-w-3xl px-6 py-20">
      <SkeletonMasthead />
      <div className="mt-10">
        <SkeletonProse n={10} />
      </div>
    </PageSkeleton>
  );
}
