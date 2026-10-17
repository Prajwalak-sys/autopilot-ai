import csv
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CSV_FILE = DATA_DIR / "internships.csv"


def save_internships(internships):
    """
    Save internship results to a CSV file.
    Avoid duplicate entries using the source URL.
    """

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    existing = {}

    if CSV_FILE.exists():
        with open(
            CSV_FILE, "r", newline="", encoding="utf-8"
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                key = row.get("url", "").strip()
                if key:
                    existing[key] = row

    added = 0

    for item in internships:
        url = item.get("url", "").strip()

        if not url:
            continue

        if url not in existing:
            existing[url] = {
                "title": item.get("title", ""),
                "url": url,
                "snippet": item.get("snippet", "")
            }
            added += 1

    fields = ["title", "url", "snippet"]

    with open(
        CSV_FILE, "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(existing.values())

    return {
        "file": str(CSV_FILE),
        "total_saved": len(existing),
        "new_entries": added
    }