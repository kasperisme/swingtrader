"use server";

import { createClient } from "@/lib/supabase/server";
import { revalidatePath } from "next/cache";

export async function getTradingStrategy(): Promise<string> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return "";
  const { data } = await supabase
    .schema("swingtrader")
    .from("user_trading_strategy")
    .select("strategy")
    .eq("user_id", userId)
    .maybeSingle();
  return data?.strategy ?? "";
}

export async function saveTradingStrategy(
  strategy: string,
): Promise<{ ok: boolean; error?: string }> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Unauthorized" };
  const { error } = await supabase
    .schema("swingtrader")
    .from("user_trading_strategy")
    .upsert({
      user_id: userId,
      strategy: strategy.trim(),
      updated_at: new Date().toISOString(),
    });
  if (error) return { ok: false, error: error.message };
  revalidatePath("/protected/profile");
  return { ok: true };
}
