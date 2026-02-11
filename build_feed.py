import requests
from bs4 import BeautifulSoup
import yaml
import re
from datetime import datetime
from email.utils import format_datetime
from dateutil import parser as dateparser
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

# ----------------------------------------
# FILTERING LOGIC
# ----------------------------------------

def matches_filters(title, summary, keywords, exclude_keywords):
    blob = f"{title} {summary}".lower()

    if any(bad.lower() in blob for bad in exclude_keywords):
        return False

    if not keywords:
        return True

    return any(k.lower() in blob for k in keywords)

# ----------------------------------------
# HELPERS
# ----------------------------------------

def clean_text(text):
    if not text:
        return ""
    return " ".join(text.split())

def extract_date(raw):
    if not raw:
        return None
    try:
        dt = dateparser.parse(raw)
        return format_datetime(dt)
    except:
        return None

def fetch_html(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
    }

    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text

# ----------------------------------------
# SCRAPING ENGINE
# ----------------------------------------

def scrape_source(src):
    print(f"\nScraping list: {src['name']}")
    html = fetch_html(src["list_url"])
    soup = BeautifulSoup(html, "lxml")

    # Find item links
    links = soup.select(src["item_link_selector"])
    urls = []

    for tag in links:
        href = tag.get("href")
        if not href:
            continue

        # Make relative URLs absolute
        if href.startswith("/"):
            domain = re.match(r"https?://[^/]+", src["list_url"]).group(0)
            href = domain + href

        if href not in urls:
            urls.append(href)

    # Limit items from this source
    urls = urls[: src.get("max_from_source", 20)]
    print(f"Found {len(urls)} article links")

    items = []

    for url in urls:
        try:
            print(f"  Fetching article: {url}")
            art_html = fetch_html(url)
            art = BeautifulSoup(art_html, "lxml")

            title_tag = art.select_one(src["item_title_selector"])
            summary_tag = art.select_one(src["item_summary_selector"])
            date_tag = art.select_one(src["item_date_selector"])

            title = clean_text(title_tag.get_text() if title_tag else "")
            summary = clean_text(summary_tag.get_text() if summary_tag else "")
            pub_date = extract_date(date_tag.get_text() if date_tag else "")

            if not title:
                continue

            items.append({
                "title": title,
                "summary": summary,
                "link": url,
                "published": pub_date,
            })
        except Exception as e:
            print(f"Error scraping {url}: {e}")

    return items

# ----------------------------------------
# RSS GENERATOR
# ----------------------------------------

def build_rss(items, config):
    rss = Element("rss")
    rss.set("version", "2.0")
    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = config.get("title", "Virgin Islands Feed")
    SubElement(channel, "description").text = config.get("description", "")
    SubElement(channel, "link").text = "https://allvirginislands.com/"
    SubElement(channel, "lastBuildDate").text = format_datetime(datetime.utcnow())

    for item in items:
        entry = SubElement(channel, "item")
        SubElement(entry, "title").text = item["title"]
        SubElement(entry, "link").text = item["link"]
        SubElement(entry, "description").text = item["summary"]
        if item["published"]:
            SubElement(entry, "pubDate").text = item["published"]

    xml_raw = tostring(rss, "utf-8")
    return minidom.parseString(xml_raw).toprettyxml(indent="  ")

# ----------------------------------------
# MAIN LOGIC
# ----------------------------------------

def main():
    with open("feeds.yml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    keywords = config.get("keywords", [])
    exclude = config.get("exclude_keywords", [])
    sources = config.get("sources", [])
    max_items = config.get("max_items", 60)

    all_items = []

    for src in sources:
        scraped = scrape_source(src)
        print(f"Scraped {len(scraped)} items from {src['name']}")

        # Filter them
        for item in scraped:
            if matches_filters(item["title"], item["summary"], keywords, exclude):
                all_items.append(item)

    # Sort newest first
    all_items.sort(key=lambda x: x["published"] or "", reverse=True)

    # Limit total number of items
    all_items = all_items[:max_items]

    print(f"\nTotal items after filtering: {len(all_items)}")

    # Build RSS
    xml = build_rss(all_items, config)

    # Write file
    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(xml)

    print("\nfeed.xml created successfully!")

if __name__ == "__main__":
    main()
