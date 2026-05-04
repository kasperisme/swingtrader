"""
Bulk per-ticker technical-analysis worker.

Triggered from the UI by inserting a row into
``swingtrader.user_bulk_analysis_jobs``. The Mac Mini's system crontab calls
``scripts/run_bulk_analysis_tick.sh`` every minute, which runs ``cli tick``
to pick up queued jobs and dispatch a subprocess per job. Each subprocess
fetches 6 months of FMP daily candles + SMAs for every ticker in the linked
scan run, runs a single Ollama pass, writes the analysis into
``user_ticker_chart_workspace.ai_chat_messages`` (mirroring the chat shape),
and sets the call on ``user_scan_row_notes.status``.
"""
