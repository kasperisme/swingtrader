"""Social publishing — push finished NIS-breakdown assets from the local
``output/setups/<TICKER>/`` folder to Instagram, Facebook, TikTok and LinkedIn.

The content itself is a hand-iterated creative process (the nis-stock-breakdown
skill). This service is the deterministic *last mile*: it reads whatever is
already on disk, stages the media to a public URL (Supabase Storage), and posts
it through the Ayrshare aggregator — one API instead of four native OAuth flows.

No scheduler, no queue, no approval gate. You run it per ticker when the assets
are ready: ``python -m services.social_publishing.cli publish --ticker NWPX``.
"""
