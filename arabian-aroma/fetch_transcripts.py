"""Download transcripts for every video in data/youtube.csv.

Needs network access to youtube.com and PyPI:
    pip install youtube-transcript-api
    python3 fetch_transcripts.py

Writes data/transcripts/<video_id>.txt (skips ones already saved) and a status
column per video to data/transcript_status.csv. build_db.py loads the saved
text into the `transcripts` table.
"""
import csv
import time
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi

DATA = Path(__file__).parent / "data"
OUT = DATA / "transcripts"
LANGUAGES = ["en", "en-IN", "hi", "ml", "ta", "te", "ur"]


def main():
    OUT.mkdir(exist_ok=True)
    api = YouTubeTranscriptApi()
    with open(DATA / "youtube.csv", newline="", encoding="utf-8") as f:
        ids = [r["video_id"] for r in csv.DictReader(f)]

    status = []
    for vid in ids:
        path = OUT / f"{vid}.txt"
        if path.exists():
            status.append((vid, "saved", ""))
            continue
        try:
            fetched = api.fetch(vid, languages=LANGUAGES)
            path.write_text("\n".join(s.text for s in fetched.snippets), encoding="utf-8")
            status.append((vid, "saved", fetched.language_code))
        except Exception as e:  # no captions, private video, rate limit, ...
            status.append((vid, "failed", type(e).__name__))
        time.sleep(1)

    with open(DATA / "transcript_status.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["video_id", "status", "language_or_error"])
        w.writerows(status)
    saved = sum(s == "saved" for _, s, _ in status)
    print(f"{saved}/{len(ids)} transcripts saved to {OUT}")


if __name__ == "__main__":
    main()
