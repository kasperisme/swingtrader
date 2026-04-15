import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { OpsUI } from "./ops-ui";

export const metadata = { title: "Operations · SwingTrader" };

export default async function OpsPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in");

  return <OpsUI />;
}
