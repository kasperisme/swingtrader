# Every process that imports a service tallies its FMP calls — see shared/fmp_usage.py.
try:
    from shared import fmp_usage as _fmp_usage

    _fmp_usage.install()
except Exception:
    pass
