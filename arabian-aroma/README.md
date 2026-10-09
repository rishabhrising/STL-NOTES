# Arabian Aroma — catalog, reviews and ranking

Run `python3 build_db.py` to rebuild `aroma.db` (SQLite) and `ranking.csv` from `data/`.

| File | Contents |
|---|---|
| `data/catalog.csv` | 90 products from arabianaroma.in: line, gender, notes, sizes, prices, URL |
| `data/ratings.csv` | 41 marketplace listings (Amazon, Flipkart, Myntra, plus brand-site widget scores kept but excluded) |
| `data/combo_ratings.csv` | Ratings for gift sets and combos (not ranked) |
| `data/review_themes.csv` | Recurring praise and complaints per product |
| `data/youtube.csv` | 10 YouTube reviews: title, products covered, summary |
| `aroma.db` | All of the above as tables, plus `ranking` |

The ranking method is described at the top of `build_db.py`.

## Data limitations (snapshot of 2026-10-09)

- Collected through web-search results only. This environment's network policy blocked direct page
  fetches, so arabianaroma.in, Amazon, Flipkart, Myntra and YouTube pages were never opened directly.
  Ratings are the figures shown in search snippets and may be days or months old.
- The catalog is the subset of the site that search engines had indexed. The site advertises 100+
  fragrances, so some are missing, and prices are blank where no snippet showed them.
- YouTube entries are titles and descriptions, not transcripts.
- No Arabian Aroma listings were found on Nykaa.
- Products with fewer than ~100 ratings (Good Girl, Noir, Wanted By Night, Oud Timber, Tamdan) are
  pulled strongly toward the average, so their positions are low-confidence.
