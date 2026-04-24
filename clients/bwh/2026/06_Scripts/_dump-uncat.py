"""Aggregate the currently-Uncategorized tickets by similar title, so we can see the real work mix."""
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parent.parent   # clients/BWH/
HERE = ROOT / "03_Accounting"
SCRIPTS = ROOT / "06_Scripts"

# Reuse the classifier from _categorize-work.py
spec = importlib.util.spec_from_file_location("catmod", SCRIPTS / "_categorize-work.py")
catmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catmod)

uncat_titles = Counter()
uncat_hours = defaultdict(float)
uncat_word_hours = defaultdict(float)

with (HERE / "ticket-by-ticket.csv").open("r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        title = (row.get("Ticket") or "").strip()
        try:
            hours = abs(float(row.get("Hours") or 0))
        except ValueError:
            hours = 0.0
        cat = catmod.classify(title)
        if cat != "Uncategorized":
            continue
        # collapse obvious hostnames/IDs to get a clean title for grouping
        t = re.sub(r"\bBW[A-Z0-9-]+", "<host>", title, flags=re.I)
        t = re.sub(r"\b\d+\.\d+\.\d+\.\d+\b", "<ip>", t)
        t = re.sub(r"\s+", " ", t).strip()
        uncat_titles[t] += 1
        uncat_hours[t] += hours
        for tok in re.findall(r"[A-Za-z]{4,}", title.lower()):
            uncat_word_hours[tok] += hours

# Top titles by hours
print("\n=== TOP UNCATEGORIZED TITLES BY HOURS ===")
for t, hrs in sorted(uncat_hours.items(), key=lambda kv: -kv[1])[:50]:
    print(f"{hrs:7.1f}h  x{uncat_titles[t]:<4}  {t[:120]}")

print("\n=== TOP UNCATEGORIZED KEYWORDS BY HOURS (len>=4) ===")
STOP = {"with", "from", "this", "that", "have", "will", "been", "they", "them",
        "into", "your", "what", "when", "email", "issue", "issues",
        "need", "needs", "needed", "over", "only", "some", "please",
        "there", "their", "more", "back", "like", "than", "other",
        "about", "which", "also", "does", "through", "just", "could", "would",
        "before", "after", "while", "these", "those", "being", "where"}
for w, hrs in sorted(uncat_word_hours.items(), key=lambda kv: -kv[1])[:60]:
    if w in STOP:
        continue
    print(f"{hrs:7.1f}h  {w}")
