#!/usr/bin/env python3
"""Bouwt een gefilterde FD-feed met een archief van 30 dagen.

De bronfeed toont alleen de nieuwste artikelen (een venster van ongeveer een
halve dag). Dit script bewaart elk artikel dat het tegenkomt in archive.json en
bouwt de feed op uit het hele archief, zodat de feed ook na weken niet lezen
nog alles bevat wat er in de tussentijd verscheen.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.request import urlopen, Request

FD_RSS = "https://fd.nl/laatste-nieuws?rss="
OUTPUT = Path("feed.xml")
ARCHIVE_FILE = Path("archive.json")

# Hoelang een artikel in de feed blijft, gerekend vanaf het moment dat dit
# script het voor het eerst zag.
FEED_DAYS = 30

SECTIONS = {
    "economie",
    "politiek",
    "bedrijfsleven",
    "samenleving",
    "tech-en-innovatie",
}

TITLE_EXCLUDE = [
    "Vandaag in Dagkoers:",
    "Personalia ",
]


def fetch_source() -> bytes:
    req = Request(FD_RSS, headers={"User-Agent": "FD-RSS-Filter/1.0"})
    with urlopen(req, timeout=15) as resp:
        return resp.read()


def section_from_url(url: str) -> str | None:
    parts = url.split("/")
    if len(parts) >= 4:
        return parts[3]
    return None


def article_id(url: str) -> str:
    """Stabiele sleutel: het FD-artikelnummer uit de URL.

    De sectie en de slug kunnen veranderen, het nummer niet.
    """
    parts = url.split("/")
    if len(parts) >= 5 and parts[4].isdigit():
        return parts[4]
    return url


def should_exclude(title: str, description: str) -> bool:
    text = f"{title} {description}"
    return any(prefix in text for prefix in TITLE_EXCLUDE)


def keep(link: str, title: str, description: str) -> bool:
    return (
        section_from_url(link) in SECTIONS
        and not should_exclude(title, description)
    )


def load_archive() -> dict:
    if not ARCHIVE_FILE.exists():
        return {}
    try:
        return json.loads(ARCHIVE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_archive(archive: dict) -> None:
    ARCHIVE_FILE.write_text(
        json.dumps(archive, indent=1, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def _parse(rfc_date: str) -> datetime | None:
    try:
        dt = parsedate_to_datetime(rfc_date)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_recent(rfc_date: str, cutoff: datetime) -> bool:
    """Onparseerbare datum telt als recent, zodat we niets per ongeluk wissen."""
    dt = _parse(rfc_date)
    return True if dt is None else dt >= cutoff


def _sort_key(rfc_date: str) -> datetime:
    dt = _parse(rfc_date)
    return dt or datetime.min.replace(tzinfo=timezone.utc)


def build_item(entry: dict) -> ET.Element:
    item = ET.Element("item")
    ET.SubElement(item, "title").text = entry["title"]
    ET.SubElement(item, "link").text = entry["link"]
    ET.SubElement(item, "description").text = entry["description"]
    if entry.get("enclosure"):
        ET.SubElement(item, "enclosure", entry["enclosure"])
    ET.SubElement(item, "pubDate").text = entry["pubDate"]
    # De guid blijft de artikel-URL, net als in de bronfeed: zo herkent de
    # RSS-reader artikelen die hij al heeft en komen ze niet opnieuw binnen.
    ET.SubElement(item, "guid").text = entry["link"]
    return item


def main() -> int:
    archive = load_archive()
    now = datetime.now(timezone.utc)
    now_str = format_datetime(now)

    try:
        raw = fetch_source()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        # Niets wegschrijven: feed.xml en archive.json blijven staan zoals ze
        # waren, dus de feed verliest geen artikelen door een mislukte run.
        print(f"Bronfeed niet op te halen: {e}", file=sys.stderr)
        return 1

    root = ET.fromstring(raw)
    channel = root.find("channel")

    n_new = 0
    for item in channel.findall("item"):
        link = item.findtext("link", "")
        title = item.findtext("title", "")
        description = item.findtext("description", "")
        if not keep(link, title, description):
            continue

        enclosure = item.find("enclosure")
        fields = {
            "title": title,
            "link": link,
            "description": description,
            "enclosure": dict(enclosure.attrib) if enclosure is not None else None,
        }

        key = article_id(link)
        entry = archive.get(key)
        if entry is None:
            n_new += 1
            archive[key] = {
                **fields,
                "pubDate": item.findtext("pubDate", now_str),
                "first_seen": now_str,
                "last_seen": now_str,
            }
        else:
            # Titel en tekst mogen bijwerken, pubDate en first_seen niet: het
            # artikel mag niet opnieuw als nieuw binnenkomen bij de lezer.
            entry.update(fields)
            entry["last_seen"] = now_str

    cutoff = now - timedelta(days=FEED_DAYS)
    archive = {
        k: v
        for k, v in archive.items()
        if is_recent(v["first_seen"], cutoff)
        and keep(v["link"], v["title"], v["description"])
    }
    save_archive(archive)

    for item in channel.findall("item"):
        channel.remove(item)
    channel.find("title").text = "FD – Selectie"
    channel.find("description").text = (
        "Gefilterd op: " + ", ".join(sorted(SECTIONS))
    )
    for _, entry in sorted(
        archive.items(), key=lambda kv: _sort_key(kv[1]["pubDate"]), reverse=True
    ):
        channel.append(build_item(entry))

    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode", xml_declaration=True)
    OUTPUT.write_text(xml, encoding="utf-8")
    print(
        f"{len(archive)} artikelen in de feed "
        f"({n_new} nieuw, archief van {FEED_DAYS} dagen)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
