import { createClient } from "@sanity/client";

const projectId = process.env.NEXT_PUBLIC_SANITY_PROJECT_ID;
const dataset = process.env.NEXT_PUBLIC_SANITY_DATASET;
const apiVersion = process.env.NEXT_PUBLIC_SANITY_API_VERSION ?? "2026-04-08";

export const isSanityConfigured = Boolean(projectId && dataset);

const sanityClient = isSanityConfigured
  ? createClient({
      projectId,
      dataset,
      apiVersion,
      useCdn: process.env.NODE_ENV === "production",
    })
  : null;

export async function sanityFetch<T>(query: string, params: Record<string, string> = {}): Promise<T> {
  if (!sanityClient) {
    throw new Error("Sanity is not configured. Set NEXT_PUBLIC_SANITY_PROJECT_ID and NEXT_PUBLIC_SANITY_DATASET.");
  }

  return sanityClient.fetch<T>(query, params);
}
