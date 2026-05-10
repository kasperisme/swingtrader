"use client";

import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { track } from "@/lib/analytics/events";

export function LogoutButton() {
  const logout = async () => {
    const supabase = createClient();
    track("logout", {});
    await supabase.auth.signOut();
    window.location.href = "/auth/login";
  };

  return <Button onClick={logout}>Logout</Button>;
}
