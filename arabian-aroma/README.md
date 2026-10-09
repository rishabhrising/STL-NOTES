# Arabian Aroma — catalog, reviews and ranking

Run `python3 build_db.py` to rebuild `aroma.db` (SQLite) and `ranking.csv` from `data/`.

| File | Contents |
|---|---|
| `data/catalog.csv` | 90 products from arabianaroma.in: line, gender, notes, sizes, prices, URL |
| `data/ratings.csv` | 41 marketplace listings (Amazon, Flipkart, Myntra, plus brand-site widget scores kept but excluded) |
| `data/combo_ratings.csv` | Ratings for gift sets and combos (not ranked) |
| `data/review_themes.csv` | Recurring praise and complaints per product |
| `data/youtube.csv` | 60 YouTube reviews: single-product, multi-product, clone-vs-original comparisons and rankings, with products covered, what each is compared against, verdict and summary |
| `aroma.db` | All of the above as tables (`youtube_products` links videos to perfumes), plus `ranking` |

Ranking: 80% marketplace score (platform-calibrated Bayesian average of star ratings) + 20% YouTube score (verdict-weighted, shrunk toward the YouTube average). Full method at the top of `build_db.py`; tune `YT_WEIGHT`, `K` and the sentiment scores there.

## Data limitations (snapshot of 2026-10-09)

- Collected through web-search results only. This environment's network policy blocked direct page
  fetches, so arabianaroma.in, Amazon, Flipkart, Myntra and YouTube pages were never opened directly.
  Ratings are the figures shown in search snippets and may be days or months old.
- The catalog is the subset of the site that search engines had indexed. The site advertises 100+
  fragrances, so some are missing, and prices are blank where no snippet showed them.
- YouTube: titles and channel names are verified through YouTube's oEmbed endpoint (59 of 60; one returns 401).
  Transcripts could not be downloaded: YouTube answers this cloud container with a "confirm you're not a bot"
  wall. Run `fetch_transcripts.py` from a home connection to fill `data/transcripts/`. Of the 60 videos, 23 have
  a visible verdict (20 positive, 1 mixed, 2 negative). 3 videos from the brand's own channel are marked
  `promotional` and not scored. Verdicts taken from a title alone get half weight.
- No Arabian Aroma listings were found on Nykaa.
- Products with fewer than ~100 ratings (Good Girl, Noir, Wanted By Night, Oud Timber, Tamdan) are
  pulled strongly toward the average, so their positions are low-confidence.
