import feedparser
from typing import List, Dict, Any
from datetime import datetime

def fetch_ticker_news(ticker: str) -> List[Dict[str, Any]]:
    """Fetch latest ticker-specific headlines from Yahoo Finance RSS."""
    feed_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker.upper()}&region=US&lang=en-US"
    feed = feedparser.parse(feed_url)
    items = []
    for entry in feed.entries[:5]:
        items.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", datetime.utcnow().isoformat()),
            "summary": entry.get("summary", "")
        })
    return items

def fetch_macro_headlines() -> List[Dict[str, Any]]:
    """Fetch broad market news headlines."""
    macro_url = "https://finance.yahoo.com/news/rssindex"
    feed = feedparser.parse(macro_url)
    items = []
    for entry in feed.entries[:8]:
        items.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", datetime.utcnow().isoformat())
        })
    return items
