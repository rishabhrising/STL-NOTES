"""Load the CSVs in data/ into aroma.db (SQLite) and rank products.

Marketplace score (Bayesian weighted average):
  1. Platform calibration: each platform rates on its own scale (Flipkart runs
     higher than Amazon), so every listing's rating is shifted by
     (global mean - platform mean), both means weighted by rating count.
  2. Pooling: a product's calibrated ratings across all listings are combined
     as a rating-count-weighted average R, with total count V.
  3. Shrinkage: score = V/(V+m) * R + m/(V+m) * C, where C is the global mean
     and m is the median product rating count. Products with few ratings are
     pulled toward the average, so 4.6 from 20 people can't beat 4.2 from 18k.

YouTube score:
  4. Each video with a stated verdict gets a sentiment score (positive 4.5,
     mixed 3.0, negative 1.5) and a weight by evidence: 1.0 when the verdict
     comes from the video's description/summary, 0.5 when only the title says
     it. Videos with no verdict are stored but not scored. A multi-product
     video counts for every product it names; brand-wide ("Range") videos only
     feed the YouTube average Y.
  5. Shrinkage: yt = (sum(w*s) + K*Y) / (sum(w) + K), so one video moves a
     product only a little and products with no videos sit at Y.

Final score = (1 - YT_WEIGHT) * marketplace + YT_WEIGHT * yt.
"""
import csv
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DB = ROOT / "aroma.db"

SENTIMENT_SCORE = {"positive": 4.5, "mixed": 3.0, "negative": 1.5}
EVIDENCE_WEIGHT = {"description": 1.0, "title": 0.5}
K = 2
YT_WEIGHT = 0.2


def read(name):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(value, cast=float):
    return cast(value) if value not in ("", None) else None


def load(conn):
    conn.executescript(
        """
        DROP TABLE IF EXISTS products; DROP TABLE IF EXISTS ratings;
        DROP TABLE IF EXISTS combos; DROP TABLE IF EXISTS youtube;
        DROP TABLE IF EXISTS youtube_products;
        DROP TABLE IF EXISTS review_themes; DROP TABLE IF EXISTS ranking;
        CREATE TABLE products (product TEXT PRIMARY KEY, line TEXT, gender TEXT,
            notes_or_inspiration TEXT, sizes TEXT, sale_price_inr TEXT,
            mrp_inr TEXT, url TEXT);
        CREATE TABLE ratings (product TEXT, platform TEXT, listing TEXT, size TEXT,
            rating REAL, rating_count INTEGER, review_count INTEGER,
            include INTEGER, source_url TEXT, note TEXT);
        CREATE TABLE combos (combo TEXT, contents TEXT, platform TEXT,
            rating REAL, rating_count INTEGER, source_url TEXT);
        CREATE TABLE youtube (video_id TEXT PRIMARY KEY, url TEXT, title TEXT,
            channel TEXT, language TEXT, video_type TEXT, compared_with TEXT,
            sentiment TEXT, evidence TEXT, score REAL, weight REAL, summary TEXT);
        CREATE TABLE youtube_products (video_id TEXT, product TEXT);
        CREATE TABLE review_themes (product TEXT, platform TEXT, sentiment TEXT,
            theme TEXT, quote_or_paraphrase TEXT);
        CREATE TABLE ranking (rank INTEGER, product TEXT, gender TEXT,
            final_score REAL, marketplace_score REAL, youtube_score REAL,
            youtube_videos INTEGER, pooled_rating REAL, total_ratings INTEGER,
            amazon TEXT, flipkart TEXT, myntra TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?,?,?,?)",
        [tuple(r.values()) for r in read("catalog.csv")],
    )
    conn.executemany(
        "INSERT INTO ratings VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (r["product"], r["platform"], r["listing"], r["size"], num(r["rating"]),
             num(r["rating_count"], int), num(r["review_count"], int),
             int(r["include"]), r["source_url"], r["note"])
            for r in read("ratings.csv")
        ],
    )
    conn.executemany(
        "INSERT INTO combos VALUES (?,?,?,?,?,?)",
        [(r["combo"], r["contents"], r["platform"], num(r["rating"]),
          num(r["rating_count"], int), r["source_url"]) for r in read("combo_ratings.csv")],
    )
    for r in read("youtube.csv"):
        vid = r["video_id"]
        url = (f"https://www.youtube.com/watch?v={vid}" if "Short" not in r["title"]
               else f"https://www.youtube.com/shorts/{vid}")
        score = SENTIMENT_SCORE.get(r["sentiment"])
        weight = EVIDENCE_WEIGHT.get(r["evidence"]) if score else None
        conn.execute(
            "INSERT INTO youtube VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (vid, url, r["title"], r["channel"], r["language"], r["video_type"],
             r["compared_with"], r["sentiment"], r["evidence"], score, weight,
             r["summary_from_search"]),
        )
        conn.executemany("INSERT INTO youtube_products VALUES (?,?)",
                         [(vid, p.strip()) for p in r["products"].split(";")])
    conn.executemany("INSERT INTO review_themes VALUES (?,?,?,?,?)",
                     [tuple(r.values()) for r in read("review_themes.csv")])


def wmean(items):
    return sum(r * n for r, n in items) / sum(n for _, n in items)


def marketplace_scores(conn):
    rows = conn.execute(
        "SELECT product, platform, rating, rating_count FROM ratings "
        "WHERE include = 1 AND rating IS NOT NULL AND rating_count IS NOT NULL"
    ).fetchall()

    global_mean = wmean([(r, n) for _, _, r, n in rows])
    by_platform = defaultdict(list)
    for _, platform, r, n in rows:
        by_platform[platform].append((r, n))
    offset = {p: global_mean - wmean(v) for p, v in by_platform.items()}

    pooled = defaultdict(list)
    per_platform = defaultdict(dict)
    for product, platform, r, n in rows:
        pooled[product].append((r + offset[platform], n))
        prev = per_platform[product].get(platform)
        merged = [(r, n)] + ([prev] if prev else [])
        per_platform[product][platform] = (wmean(merged), sum(x[1] for x in merged))

    totals = {p: sum(n for _, n in v) for p, v in pooled.items()}
    m = statistics.median(totals.values())
    scores = {}
    for product, items in pooled.items():
        r, v = wmean(items), totals[product]
        scores[product] = (v / (v + m) * r + m / (v + m) * global_mean, r, v)
    return scores, per_platform, global_mean, offset, m


def youtube_scores(conn):
    scored = conn.execute(
        "SELECT y.video_id, p.product, y.score, y.weight FROM youtube y "
        "JOIN youtube_products p USING (video_id) WHERE y.score IS NOT NULL"
    ).fetchall()
    per_video = {vid: (s, w) for vid, _, s, w in scored}
    y_mean = wmean(list(per_video.values()))

    by_product = defaultdict(list)
    for _, product, s, w in scored:
        if product != "Range":
            by_product[product].append((s, w))
    counts = dict(conn.execute(
        "SELECT product, COUNT(*) FROM youtube_products GROUP BY product"))

    def score(product):
        items = by_product.get(product, [])
        total_w = sum(w for _, w in items)
        return (sum(s * w for s, w in items) + K * y_mean) / (total_w + K)

    return score, counts, y_mean, len(per_video)


def rank(conn):
    market, per_platform, c, offset, m = marketplace_scores(conn)
    yt, yt_counts, y_mean, n_scored = youtube_scores(conn)
    gender = dict(conn.execute("SELECT product, gender FROM products"))

    def cell(product, platform):
        hit = per_platform[product].get(platform)
        return f"{hit[0]:.1f} ({hit[1]:,})" if hit else "-"

    results = []
    for product, (ms, r, v) in market.items():
        ys = yt(product)
        results.append((product, (1 - YT_WEIGHT) * ms + YT_WEIGHT * ys, ms, ys, r, v))
    results.sort(key=lambda x: x[1], reverse=True)

    out = [
        (i, p, gender.get(p, ""), round(f, 3), round(ms, 3), round(ys, 3),
         yt_counts.get(p, 0), round(r, 2), v,
         cell(p, "amazon"), cell(p, "flipkart"), cell(p, "myntra"))
        for i, (p, f, ms, ys, r, v) in enumerate(results, 1)
    ]
    conn.executemany("INSERT INTO ranking VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", out)
    return out, c, offset, m, y_mean, n_scored


def main():
    conn = sqlite3.connect(DB)
    load(conn)
    out, c, offset, m, y_mean, n_scored = rank(conn)
    conn.commit()

    with open(ROOT / "ranking.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "product", "gender", "final_score", "marketplace_score",
                    "youtube_score", "youtube_videos", "pooled_rating",
                    "total_ratings", "amazon", "flipkart", "myntra"])
        w.writerows(out)

    print(f"Marketplace: C = {c:.3f}; m = {m:.0f} ratings; offsets "
          + ", ".join(f"{p} {o:+.3f}" for p, o in offset.items()))
    print(f"YouTube: {n_scored} videos with a verdict; average Y = {y_mean:.3f}; "
          f"K = {K}; weight in final = {YT_WEIGHT}")
    print(f"{'#':>2}  {'Product':<18} {'Final':>5} {'Market':>6} {'YouTube':>7} "
          f"{'Vids':>4} {'Ratings':>8}")
    for i, p, _, f, ms, ys, nv, _, v, *_ in out:
        print(f"{i:>2}  {p:<18} {f:>5.3f} {ms:>6.3f} {ys:>7.3f} {nv:>4} {v:>8,}")


if __name__ == "__main__":
    main()
