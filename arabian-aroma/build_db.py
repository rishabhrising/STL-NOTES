"""Load the CSVs in data/ into aroma.db (SQLite) and rank products.

Ranking method (Bayesian weighted average):
  1. Platform calibration: each platform rates on its own scale (Flipkart runs
     higher than Amazon), so every listing's rating is shifted by
     (global mean - platform mean), both means weighted by rating count.
  2. Pooling: a product's calibrated ratings across all listings are combined
     as a rating-count-weighted average R, with total count V.
  3. Shrinkage: score = V/(V+m) * R + m/(V+m) * C, where C is the global mean
     and m is the median product rating count. Products with few ratings are
     pulled toward the average, so 4.6 from 20 people can't beat 4.2 from 18k.
"""
import csv
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DB = ROOT / "aroma.db"


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
        DROP TABLE IF EXISTS review_themes; DROP TABLE IF EXISTS ranking;
        CREATE TABLE products (product TEXT PRIMARY KEY, line TEXT, gender TEXT,
            notes_or_inspiration TEXT, sizes TEXT, sale_price_inr TEXT,
            mrp_inr TEXT, url TEXT);
        CREATE TABLE ratings (product TEXT, platform TEXT, listing TEXT, size TEXT,
            rating REAL, rating_count INTEGER, review_count INTEGER,
            include INTEGER, source_url TEXT, note TEXT);
        CREATE TABLE combos (combo TEXT, contents TEXT, platform TEXT,
            rating REAL, rating_count INTEGER, source_url TEXT);
        CREATE TABLE youtube (video_url TEXT, title TEXT, products TEXT, summary TEXT);
        CREATE TABLE review_themes (product TEXT, platform TEXT, sentiment TEXT,
            theme TEXT, quote_or_paraphrase TEXT);
        CREATE TABLE ranking (rank INTEGER, product TEXT, gender TEXT,
            score REAL, pooled_rating REAL, total_ratings INTEGER,
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
    conn.executemany("INSERT INTO youtube VALUES (?,?,?,?)",
                     [tuple(r.values()) for r in read("youtube.csv")])
    conn.executemany("INSERT INTO review_themes VALUES (?,?,?,?,?)",
                     [tuple(r.values()) for r in read("review_themes.csv")])


def rank(conn):
    rows = conn.execute(
        "SELECT product, platform, rating, rating_count FROM ratings "
        "WHERE include = 1 AND rating IS NOT NULL AND rating_count IS NOT NULL"
    ).fetchall()

    def wmean(items):
        return sum(r * n for r, n in items) / sum(n for _, n in items)

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
    gender = dict(conn.execute("SELECT product, gender FROM products"))

    results = []
    for product, items in pooled.items():
        r, v = wmean(items), totals[product]
        score = v / (v + m) * r + m / (v + m) * global_mean
        results.append((product, score, r, v))
    results.sort(key=lambda x: x[1], reverse=True)

    def cell(product, platform):
        hit = per_platform[product].get(platform)
        return f"{hit[0]:.1f} ({hit[1]:,})" if hit else "-"

    out = [
        (i, p, gender.get(p, ""), round(s, 3), round(r, 2), v,
         cell(p, "amazon"), cell(p, "flipkart"), cell(p, "myntra"))
        for i, (p, s, r, v) in enumerate(results, 1)
    ]
    conn.executemany("INSERT INTO ranking VALUES (?,?,?,?,?,?,?,?,?)", out)
    return out, global_mean, offset, m


def main():
    conn = sqlite3.connect(DB)
    load(conn)
    out, c, offset, m = rank(conn)
    conn.commit()

    with open(ROOT / "ranking.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "product", "gender", "score", "pooled_rating",
                    "total_ratings", "amazon", "flipkart", "myntra"])
        w.writerows(out)

    print(f"Global mean C = {c:.3f}; shrinkage m = {m:.0f} ratings")
    print("Platform offsets: " + ", ".join(f"{p} {o:+.3f}" for p, o in offset.items()))
    print(f"{'#':>2}  {'Product':<18} {'Score':>5} {'Pooled':>6} {'Ratings':>8}  "
          f"{'Amazon':<13} {'Flipkart':<13} Myntra")
    for i, p, _, s, r, v, a, fk, my in out:
        print(f"{i:>2}  {p:<18} {s:>5.3f} {r:>6.2f} {v:>8,}  {a:<13} {fk:<13} {my}")


if __name__ == "__main__":
    main()
