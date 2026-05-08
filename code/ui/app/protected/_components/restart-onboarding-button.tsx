"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { track } from "@/lib/analytics/events";
import { restartOnboardingChecklist } from "@/app/actions/onboarding";

export function RestartOnboardingButton({
  completedSteps,
  totalSteps,
}: {
  completedSteps: number;
  totalSteps: number;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function handleRestart() {
    setError(null);
    track("onboarding_restarted", {
      completed_steps: completedSteps,
      total_steps: totalSteps,
    });
    startTransition(async () => {
      const result = await restartOnboardingChecklist();
      if (!result.ok) {
        setError(result.error || "Failed to restart tour");
        return;
      }
      // Clear the checklist's collapsed-state flag so it expands on landing.
      if (typeof window !== "undefined") {
        window.localStorage.setItem("onboarding_checklist_collapsed", "0");
      }
      router.push("/protected");
      router.refresh();
    });
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        size="sm"
        variant="outline"
        onClick={handleRestart}
        disabled={isPending}
        className="gap-1.5"
      >
        <RotateCcw className="h-3.5 w-3.5" />
        {isPending ? "Restarting…" : "Restart tour"}
      </Button>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
