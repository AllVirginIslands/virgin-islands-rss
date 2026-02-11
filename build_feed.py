import yaml
import feedparser
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

def matches_filters(title: str, summary: str, keywords: list[str], exclude_keywords: list[str]) -> bool:
    blob = f"{title} {summary}".lower()

    if exclude_keywords:
        if any(bad.lower() in blob for bad in exclude_keywords):
            return False

    if not keywords:
        return True

    return any(k.lower() in blob for k in keywords)

def load_feeds_config(path="feeds.yml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def fetch_feed(url):
    return feedparser.parse(url)

def build_rss_feed(items):
    rss = Element("rss")
    rss.set("version", "2.0")

    channel = SubElement(rss, "channel")

    # Required RSS metadata
    SubElement(channel, "title").text = "Virgin Islands Combined RSS Feed"
    SubElement(channel, "description").text = "Aggregated feed from multiple sources"
    SubElement(channel, "link").text = "https://allvirginislands.com/"
    SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

    for item in items:
        entry = SubElement(channel, "item")
        SubElement(entry, "title").text = item["title"]
        SubElement(entry, "link").text = item["link"]
        SubElement(entry, "description").text = item["summary"]

        pub_date = item.get("published")
        if pub_date:
            SubElement(entry, "pubDate").text = pub_date

    # Make pretty XML
    rough = tostring(rss, "utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ")

def main():
    config = load_feeds_config()

    all_items = []

    for feed_cfg in config.get("feeds", []):
        print(f"Fetching: {feed_cfg['url']}")
        parsed = fetch_feed(feed_cfg["url"])

        keywords = feed_cfg.get("keywords", [])
        exclude = feed_cfg.get("exclude_keywords", [])

        for entry in parsed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")

            if not matches_filters(title, summary, keywords, exclude):
                continue

            # Parse publication date
            try:
                published = entry.get("published")
                pub_dt = parsedate_to_datetime(published) if published else None
                pub_rss_fmt = pub_dt.strftime("%a, %d %b %Y %H:%M:%S GMT") if pub_dt else None
            except:
                pub_rss_fmt = None

            all_items.append({
                "title": title,
                "summary": summary,
                "link": entry.get("link", ""),
                "published": pub_rss_fmt
            })

    # Sort items by date (newest first)
    all_items.sort(key=lambda x: x["published"] or "", reverse=True)

    # Build XML string
    xml_output = build_rss_feed(all_items)

    # Write the fil
