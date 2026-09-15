#!/usr/bin/env python3
"""Fetch FD 'laatste nieuws' RSS and keep only selected sections."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen, Request

FD_RSS = "https://fd.nl/laatste-nieuws?rss="

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


def section_from_url(url: str) -> str | None:
    parts = url.split("/")
    if len(parts) >= 4:
        return parts[3]
    return None


def should_exclude(item) -> bool:
    title = item.findtext("title", "")
    return any(title.startswith(prefix) for prefix in TITLE_EXCLUDE)


def main() -> None:
    req = Request(FD_RSS, headers={"User-Agent": "FD-RSS-Filter/1.0"})
    with urlopen(req, timeout=15) as resp:
        raw = resp.read()

    root = ET.fromstring(raw)
    channel = root.find("channel")

    channel.find("title").text = "FD \u2013 Selectie"
    channel.find("description").text = (
        "Gefilterd op: " + ", ".join(sorted(SECTIONS))
    )

    for item in channel.findall("item"):
        link = item.findtext("link", "")
        if section_from_url(link) not in SECTIONS or should_exclude(item):
            channel.remove(item)

    xml = ET.tostring(root, encoding="unicode", xml_declaration=True)
    Path("feed.xml").write_text(xml, encoding="utf-8")
    print(f"{len(channel.findall('item'))} artikelen geschreven naar feed.xml")


if __name__ == "__main__":
    main()
