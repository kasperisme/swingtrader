# dimension_significance_cli.py

Statistical significance testing for company vector dimensions against stock performance targets.

Tests each dimension for predictive power using multiple statistical methods, ranked by effect size × significance.

---

## Usage

```bash
# Default: trend_template target, most recent date
python dimension_significance_cli.py

# Specific target
python dimension_significance_cli.py --target rs_rating
python dimension_significance_cli.py --target price_momentum

# Specific date
python dimension_significance_cli.py --target trend_template --date 2026-04-01

# Limit output, show plot
python dimension_significance_cli.py --target price_momentum --top 20 --plot

# Save to CSV
python dimension_significance_cli.py --target trend_template --output results.csv

# Raise minimum sample threshold
python dimension_significance_cli.py --target trend_template --min-samples 30
```

---

## Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--target` | `trend_template` | Target variable — see Targets below |
| `--date` | latest available | Analysis date `YYYY-MM-DD` |
| `--top` | all | Show only top N dimensions |
| `--output` | none | Save full ranked results to CSV |
| `--plot` | off | Open interactive Plotly charts |
| `--min-samples` | 10 | Minimum group size to compute tests |

---

## Targets

| Target | Type | Source | Description |
|--------|------|--------|-------------|
| `trend_template` | binary 0/1 | `scan_rows` | IBD Minervini trend template pass/fail |
| `rs_rating` | continuous 0–99 | `scan_rows` | IBD relative strength rank |
| `price_momentum` | continuous 0–1 | `company_vectors` | Price vs 52-week high (from dimensions) |

---

## Statistical Tests

### Binary target (`trend_template`)

| Metric | Method |
|--------|--------|
| `mwu_p` | Mann-Whitney U p-value (non-parametric group comparison) |
| `pb_r` | Point-biserial correlation |
| `cohens_d` | Cohen's d effect size |
| `lr_coef` | Logistic regression coefficient (sklearn, C=1e6, no regularisation) |

**Rank score** = `abs(cohens_d) × -log10(mwu_p)` clipped to [0, 10]

Cohen's d reference: `|d| > 0.8` large · `> 0.5` medium · `> 0.2` small

### Continuous targets (`rs_rating`, `price_momentum`)

| Metric | Method |
|--------|--------|
| `spearman_rho` | Spearman rank correlation + p-value |
| `pearson_r` | Pearson correlation + p-value |
| `mutual_info` | Mutual information (sklearn, 5 neighbours) |

**Rank score** = `abs(spearman_rho) × -log10(spearman_p) + normalized_MI`

---

## Output

Ranked table printed to stdout + optional cluster summary.

### Binary columns
```
#  Dimension  Cluster  Dir  n_pass  n_fail  Cohen_d  pb_r  MWU_p  Sig  LR_coef  Score
```

### Continuous columns
```
#  Dimension  Cluster  Dir  n  Spearman_ρ  Spearman_p  Sig  Pearson_r  MutInfo  Score
```

Significance stars: `*** p<0.001` · `** p<0.01` · `* p<0.05`

---

## Data Requirements

Reads from Supabase (schema/credentials via `.env`):

- `company_vectors` — one row per ticker per date, `dimensions_json` field
- `scan_rows` — dataset `trend_template`, fields `symbol`, `scan_date`, `row_data.Passed`, `row_data.RS_Rank`

Both tables must share the same date for join-based targets (`trend_template`, `rs_rating`).

---

## Dependencies

```
numpy pandas scipy scikit-learn python-dotenv
plotly  # optional, for --plot
```
