import re
import time
import yaml
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from dateutil import parser as dateparser
from email.utils import format_datetime


# -----------------------------
# Filtering
# -----------------------------

def matches_filters(title: str, summary: str, keywords: list[str], exclude_keywords: list[str]) -> bool:
    blob = f"{title} {summary}".lower()

    if exclude_keywords:
        if any(bad.lower() in blob for bad in exclude_keywords):
            return False

    if not keywords:
        return True

    return any(k.lower() in blob for k in keywords)


# -----------------------------
# Utilities
# -----------------------------

def clean_text(text: str) -> str:
    if not text:
        return ""
    return " ".join(text.split())


def make_absolute_url(base_url: str, href: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        m = re.match(r"^https?://[^/]+", base_url)
        if m:
            return m.group(0) + href
    # relative path
    if base_url.endswith("/"):
        return base_url + href.lstrip("/")
    return base_url.rsplit("/", 1)[0] + "/" + href.lstrip("/")


def parse_date_to_rss(raw: str) -> str | None:
    """
    Parse many date formats to RFC 2822 for RSS <pubDate>.
    Returns None if can't parse.
    """
    raw = clean_text(raw)
    if not raw:
        return None
    try:
        dt = dateparser.parse(raw)
        if not dt:
            return None
        # Make timezone-aware (UTC) if missing tzinfo
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    except Exception:
        return None


def now_rss_date() -> str:
    return format_datetime(datetime.now(timezone.utc))


def is_403(exc: Exception) -> bool:
    return "403" in str(exc) or "Forbidden" in str(exc)


# -----------------------------
# HTTP fetching (with skip on 403)
# -----------------------------

def fetch_html(url: str, retries: int = 2, backoff_sec: float = 2.0) -> str | None:
    """
    Returns HTML text or None if blocked (403).
    Raises on other errors after retries.
    """
    headers = {
        # "real browser" headers
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "DNT": "1",
    }

    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=25)
            if resp.status_code == 403:
                print(f"SKIP (403 Forbidden): {url}")
                return None
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_err = e
            if is_403(e):
                print(f"SKIP (403 Forbidden): {url}")
                return None
            if attempt < retries:
                print(f"Retry {attempt + 1}/{retries} for {url} due to: {e}")
                time.sleep(backoff_sec)
                continue
            raise last_err


# -----------------------------
# Scraper
# -----------------------------

def scrape_source(src: dict) -> list[dict]:
    """
    Scrape one source using its selectors.
    Returns list of items: {title, summary, link, published}
    """
    name = src.get("name", "Unnamed Source")
    list_url = src.get("list_url")
    link_sel = src.get("item_link_selector")
    title_sel = src.get("item_title_selector", "h1")
    date_sel = src.get("item_date_selector", "time")
    summary_sel = src.get("item_summary_selector", "article")
    max_from_source = int(src.get("max_from_source", 20))

    print(f"\nScraping list: {name}")

    if not list_url or not link_sel:
        print(f"Skipping {name}: missing list_url or item_link_selector")
        return []

    html = fetch_html(list_url)
    if not html:
        print(f"Skipping source (blocked list page): {name}")
        return []

    soup = BeautifulSoup(html, "lxml")
    link_tags = soup.select(link_sel)

    urls: list[str] = []
    for tag in link_tags:
        href = tag.get("href")
        if not href:
            continue
        abs_url = make_absolute_url(list_url, href)
        if abs_url and abs_url not in urls:
            urls.append(abs_url)

    urls = urls[:max_from_source]
    print(f"Found {len(urls)} article links")

    items: list[dict] = []

    for url in urls:
        try:
            print(f"  Fetching article: {url}")
            art_html = fetch_html(url)
            if not art_html:
                continue  # blocked article

            art = BeautifulSoup(art_html, "lxml")

            title_tag = art.select_one(title_sel)
            date_tag = art.select_one(date_sel)
            summary_tag = art.select_one(summary_sel)

            title = clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")
            summary = clean_text(summary_tag.get_text(" ", strip=True) if summary_tag else "")
            published = parse_date_to_rss(date_tag.get_text(" ", strip=True) if date_tag else "")

            if not title:
                continue

            # If summary is huge, keep it reasonable
            if len(summary) > 4000:
                summary = summary[:4000] + "…"

            items.append({
                "title": title,
                "summary": summary,
                "link": url,
                "published": published,
            })
        except Exception as e:
            print(f"Error scraping {url}: {e}")

    print(f"Scraped {len(items)} items from {name}")
    return items


# -----------------------------
# RSS Builder
# -----------------------------

def build_rss_feed(items: list[dict], config: dict) -> str:
    rss = Element("rss")
    rss.set("version", "2.0")

    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = config.get("title", "Virgin Islands Combined RSS Feed")
    SubElement(channel, "description").text = config.get("description", "Aggregated feed from multiple sources")
    SubElement(channel, "language").text = config.get("language", "en-us")
    SubElement(channel, "link").text = "https://allvirginislands.com/"
    SubElement(channel, "lastBuildDate").text = now_rss_date()

    for item in items:
        entry = SubElement(channel, "item")
        SubElement(entry, "title").text = item["title"]
        SubElement(entry, "link").text = item["link"]
        SubElement(entry, "guid").text = item["link"]
        SubElement(entry, "description").text = item["summary"]
        if item.get("published"):
            SubElement(entry, "pubDate").text = item["published"]

    rough = tostring(rss, "utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ")


# -----------------------------
# Main
# -----------------------------

def main():
    with open("feeds.yml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    keywords = config.get("keywords", []) or []
    exclude = config.get("exclude_keywords", []) or []
    sources = config.get("sources", []) or []
    max_items = int(config.get("max_items", 60))

    all_items: list[dict] = []
    seen_links: set[str] = set()

    for src in sources:
        src_type = (src.get("type") or "scrape").lower().strip()
        if src_type != "scrape":
            print(f"Skipping source (unsupported type={src_type}): {src.get('name')}")
            continue

        scraped = scrape_source(src)

        # Apply global filters + dedupe
        for item in scraped:
            if item["link"] in seen_links:
                continue

            if matches_filters(item["title"], item["summary"], keywords, exclude):
                all_items.append(item)
                seen_links.add(item["link"])

    # Sort newest first by published date string (RFC2822 sorts poorly as string)
    # We'll sort by parsed datetime, fallback to oldest
    def sort_key(x):
        try:
            if x.get("published"):
                dt = dateparser.parse(x["published"])
                return dt.timestamp()
        except Exception:
            pass
        return 0.0

    all_items.sort(key=sort_key, reverse=True)

    # Limit to max_items
    all_items = all_items[:max_items]

    print(f"\nTotal items after filtering: {len(all_items)}")

    xml_output = build_rss_feed(all_items, config)

    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(xml_output)

    print("feed.xml created successfully!")


if __name__ == "__main__":
    main()
