"""Read-only Meta Marketing API access — pull ad performance (CTR, CPC, spend,
Lead conversions) by feature (utm_content) and reconcile with the email leads
captured in Supabase. No writes: this never creates or edits a campaign.

Needs, in code/analytics/.env:
    META_ADS_TOKEN        — a System User token with `ads_read`
    META_AD_ACCOUNT_ID    — the ad account id (with or without the act_ prefix)
    META_API_VERSION      — optional; defaults to a recent Graph API version
"""
