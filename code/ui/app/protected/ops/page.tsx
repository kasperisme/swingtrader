import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { OpsUI } from "./ops-ui";

export const metadata = { title: "Operations · SwingTrader" };

export default async function OpsPage() {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  if (!claims?.claims?.sub) redirect("/sign-in");

  return <OpsUI />;
}
