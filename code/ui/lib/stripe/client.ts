import Stripe from "stripe";

let _stripe: Stripe | null = null;

export function getStripe(): Stripe {
  if (!_stripe) {
    const key = process.env.STRIPE_SECRET_KEY;
    if (!key) throw new Error("Missing env var: STRIPE_SECRET_KEY");
    _stripe = new Stripe(key);
  }
  return _stripe;
}