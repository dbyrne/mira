#!/usr/bin/env python
"""Build a book's _overview_contact_sheet.png from its per-target PNGs.

Tiles the framing previews in the book's own order (season-sorted, same as
emission_book.md — read from the CSV) into a grid for one-glance browsing.

Run:  python output/books/make_contact_sheet.py <book_dir>
e.g.  python output/books/make_contact_sheet.py output/books/esprit80_emission_book
"""
import csv, math, sys
from pathlib import Path
from PIL import Image

SEASON = {m: i for i, m in enumerate(
    ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May"])}
TILE = 360  # px per tile


def main(book_dir):
    book = Path(book_dir)
    rows = list(csv.DictReader(open(book / "emission_book.csv", encoding="utf-8")))
    rows.sort(key=lambda r: (SEASON.get(r["peak"], 99), -int(r["maxalt"])))
    n = len(rows)
    cols = math.ceil(math.sqrt(n))
    nrows = math.ceil(n / cols)
    sheet = Image.new("RGB", (cols * TILE, nrows * TILE), (8, 8, 8))
    for i, r in enumerate(rows):
        im = Image.open(book / r["png"]).resize((TILE, TILE), Image.LANCZOS)
        sheet.paste(im, ((i % cols) * TILE, (i // cols) * TILE))
    out = book / "_overview_contact_sheet.png"
    sheet.save(out)
    print(f"wrote {out}  ({n} tiles, {cols}x{nrows})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "output/books/esprit80_emission_book")
