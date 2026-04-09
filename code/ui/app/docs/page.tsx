import { redirect } from "next/navigation";

export const metadata = {
  title: "Documentation | News Impact Screener",
  description: "Learn how to use News Impact Screener to track news themes and their impact on stocks.",
};

export default async function DocsIndexPage() {
  redirect("/docs/getting-started");
}
