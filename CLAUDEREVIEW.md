# Description of Changes for Claude Review

## Feature Request
Add support for fetching X (Twitter) posts from specific accounts when using the `--x-news` flag in the news impact scorer.

## Changes Made

### 1. Modified `score_news_cli.py`
- Added `--x-accounts` argument:
  ```python
  parser.add_argument(
      "--x-accounts", nargs="+", metavar="ACCOUNT", default=None,
      help="Specific X accounts to fetch posts from (without @ symbol)",
  )
  ```
- Updated usage examples in docstring:
  ```python
  # Fetch recent X (Twitter) posts mentioning stock cashtags
  python -m news_impact.score_news_cli --x-news --tickers AAPL MSFT NVDA
  python -m news_impact.score_news_cli --x-news --tickers TSLA --x-limit 50
  python -m news_impact.score_news_cli --x-news --tickers AAPL --x-accounts finansworld seekingalpha
  python -m news_impact.score_news_cli --x-news --tickers TSLA --x-accounts tsla elonmusk --x-limit 100
  ```
- Modified `_process_x_news()` function to pass `x_accounts` to the fetcher:
  ```python
  x_accounts = getattr(args, "x_accounts", None)
  posts = fetcher.fetch_stock_posts(tickers=tickers, max_results=x_limit, accounts=x_accounts)
  ```

### 2. Modified `x_fetcher.py`
- Enhanced `_build_query()` method to accept optional `accounts` parameter:
  ```python
  def _build_query(self, tickers: list[str], accounts: Optional[list[str]] = None) -> str:
      """
      Build an X search query for the given tickers.
      
      Searches cashtags ($AAPL OR $MSFT …) excluding retweets and replies
      to focus on original content. If accounts are provided, restricts to those accounts.
      """
      cashtags = " OR ".join(f"${t}" for t in tickers[:10])  # X query max ~512 chars
      
      if accounts:
          # Clean account names (remove @ if present) and format for query
          clean_accounts = [acc.lstrip('@') for acc in accounts]
          account_query = " OR ".join(f"from:{acc}" for acc in clean_accounts[:10])
          return f"({cashtags}) ({account_query}) -is:retweet -is:reply lang:en"
      else:
          return f"({cashtags}) -is:retweet -is:reply lang:en"
  ```
- Updated `fetch_stock_posts()` method signature to accept `accounts` parameter
- Added URL decoding for bearer token to handle encoded tokens in .env files:
  ```python
  def __init__(self) -> None:
      import urllib.parse
      raw_token = os.environ.get("X_BEARER_TOKEN", "")
      if not raw_token:
          raise RuntimeError("X_BEARER_TOKEN must be set in .env to use --x-news")
      # URL-decode the token if it's encoded (as it often is in .env files)
      self.bearer_token = urllib.parse.unquote(raw_token)
  ```

### 3. Updated `README_score_news.md`
- Added usage examples for the new functionality:
  ```markdown
  # Fetch recent X (Twitter) posts mentioning stock cashtags
  python -m news_impact.score_news_cli --x-news --tickers AAPL MSFT NVDA
  python -m news_impact.score_news_cli --x-news --tickers TSLA --x-limit 50
  # Fetch X posts from specific accounts mentioning stock cashtags
  python -m news_impact.score_news_cli --x-news --tickers AAPL --x-accounts finansworld seekingalpha
  python -m news_impact.score_news_cli --x-news --tickers TSLA --x-accounts tsla elonmusk --x-limit 100
  ```
- Added `--x-accounts` to the complete option reference table:
  | Flag                         | Default | Description                                                             |
  | ---------------------------- | ------- | ----------------------------------------------------------------------- |
  | `--x-accounts ACCOUNT ...`   | —       | Specific X accounts to fetch posts from (without @ symbol, requires --x-news and --tickers). |

### 4. Fixed Python 3.9 Compatibility Issues
Throughout the codebase, replaced union type syntax (`str | None`) that is not supported in Python 3.9 with proper `Optional[]` types:
- `fmp_fetcher.py`: Replaced `str | None` with `Optional[str]`, `list | dict | None` with `Union[list, dict, None]`
- `do_agent_client.py`: Replaced `str | None` with `Optional[str]`
- `impact_scorer.py`: Replaced `asyncio.Semaphore | None` with `Optional[asyncio.Semaphore]` and `str | None` with `Optional[str]`
- Added proper imports for `Union`, `List`, `Dict` where needed

## How It Works
When using `--x-accounts`, the script:
1. Constructs an X API query that combines:
   - Cashtag search for specified tickers (e.g., `($AAPL OR $MSFT)`)
   - Account restriction (e.g., `(from:finansworld OR from:seekingalpha)`)
   - Standard filters (`-is:retweet -is:reply lang:en`)
2. Fetches posts matching this combined query
3. Applies existing filters (minimum 5 likes threshold)
4. Processes each qualifying post through the normal impact scoring pipeline

## Usage Examples
```bash
# Fetch X posts about AAPL from specific financial accounts
python -m news_impact.score_news_cli --x-news --tickers AAPL --x-accounts finansworld seekingalpha

# Fetch TSLA posts from Elon Musk and Tesla official account
python -m news_impact.score_news_cli --x-news --tickers TSLA --x-accounts tsla elonmusk --x-limit 100

# Combine with date filtering for FMP news
python -m news_impact.score_news_cli --x-news --tickers NVDA --x-accounts nvidia --from 2025-04-01 --to 2025-04-20 --no-persist
```

## Requirements
- `X_BEARER_TOKEN` must be set in `.env` file
- `xdk` package must be installed (`pip install xdk`)
- Account names should be provided without the @ symbol

All changes maintain backward compatibility and follow existing codebase patterns.