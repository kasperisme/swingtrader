import { describe, it, expect } from "vitest";
import {
  changeTiming,
  isSameSelection,
  selectionForPriceId,
  type PlanOption,
  type PlanSelection,
} from "@/lib/stripe/prices";

const sel = (plan: "investor" | "trader", interval: "monthly" | "annual"): PlanSelection => ({
  plan,
  interval,
});

describe("changeTiming", () => {
  it("applies tier upgrades immediately, whatever the interval", () => {
    expect(changeTiming(sel("investor", "monthly"), sel("trader", "monthly"))).toBe("immediate");
    expect(changeTiming(sel("investor", "monthly"), sel("trader", "annual"))).toBe("immediate");
    // Annual → monthly would normally wait, but gaining a tier wins: the
    // customer should not be stuck on the lower tier until the year is up.
    expect(changeTiming(sel("investor", "annual"), sel("trader", "monthly"))).toBe("immediate");
  });

  it("defers tier downgrades to the end of the paid period", () => {
    expect(changeTiming(sel("trader", "monthly"), sel("investor", "monthly"))).toBe("period_end");
    expect(changeTiming(sel("trader", "monthly"), sel("investor", "annual"))).toBe("period_end");
    expect(changeTiming(sel("trader", "annual"), sel("investor", "annual"))).toBe("period_end");
  });

  it("treats monthly → annual on the same tier as immediate", () => {
    expect(changeTiming(sel("investor", "monthly"), sel("investor", "annual"))).toBe("immediate");
    expect(changeTiming(sel("trader", "monthly"), sel("trader", "annual"))).toBe("immediate");
  });

  it("defers annual → monthly on the same tier — the year is already paid for", () => {
    expect(changeTiming(sel("investor", "annual"), sel("investor", "monthly"))).toBe("period_end");
    expect(changeTiming(sel("trader", "annual"), sel("trader", "monthly"))).toBe("period_end");
  });
});

describe("isSameSelection", () => {
  it("matches on both plan and interval", () => {
    expect(isSameSelection(sel("trader", "annual"), sel("trader", "annual"))).toBe(true);
    expect(isSameSelection(sel("trader", "annual"), sel("trader", "monthly"))).toBe(false);
    expect(isSameSelection(sel("trader", "annual"), sel("investor", "annual"))).toBe(false);
  });
});

describe("selectionForPriceId", () => {
  const options: PlanOption[] = [
    { plan: "investor", interval: "monthly", priceId: "price_inv_m", unitAmount: 900, currency: "usd" },
    { plan: "trader", interval: "annual", priceId: "price_tra_a", unitAmount: 19900, currency: "usd" },
  ];

  it("resolves a known price back to its plan and interval", () => {
    expect(selectionForPriceId(options, "price_tra_a")).toEqual({
      plan: "trader",
      interval: "annual",
    });
  });

  it("returns null for archived or unrelated prices", () => {
    expect(selectionForPriceId(options, "price_archived_39")).toBeNull();
    expect(selectionForPriceId(options, null)).toBeNull();
  });
});
