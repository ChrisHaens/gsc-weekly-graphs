from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re


def _extract_article_id(page_url: str) -> Optional[str]:
    """Extract article ID from URL (e.g., _aid-12345 at the end)."""
    match = re.search(r'_aid-\d+(?:[/?#]|$)', page_url)
    if match:
        return match.group(0).rstrip('/?#')
    return None


def fetch_page_title(page_url: str) -> str:
    """Fetch the page title from a URL using User-Agent 'RPD-SEO-Team'."""
    try:
        print(f"  Hole Titel für: {page_url}")
        headers = {
            "User-Agent": "RPD-SEO-Team"
        }
        response = requests.get(page_url, headers=headers, timeout=5)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        title_tag = soup.find('title')
        
        if title_tag and title_tag.string:
            return title_tag.string.strip()
        else:
            return page_url
    except Exception as e:
        print(f"  ⚠ Fehler beim Abrufen des Titels für {page_url}: {e}")
        return page_url


def fetch_top_performers(
    service,
    site_url: str,
    site_label: str,
    panel_label: str,
    search_type: str,
    start_date: str,
    end_date: str,
    top_n: int = 3,
) -> pd.DataFrame:
    """Fetch top pages for a single site and channel, grouped by article ID."""
    # Fetch with higher rowLimit to get all URLs for grouping by article ID
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["page"],
        "rowLimit": 250,  # Fetch many rows to group by article ID
        "dataState": "all",
        "searchType": search_type,
    }

    response = (
        service.searchanalytics()
        .query(siteUrl=site_url, body=body)
        .execute()
    )

    rows = response.get("rows", [])
    
    # Group by article ID
    article_groups = {}
    
    for row in rows:
        page_url = row["keys"][0]
        article_id = _extract_article_id(page_url)
        
        # If no article ID found, use the full URL as key
        group_key = article_id if article_id else page_url
        
        if group_key not in article_groups:
            article_groups[group_key] = {
                "urls": [],
                "clicks": 0,
                "impressions": 0,
                "ctr": 0.0,
                "position": 0.0,
                "count": 0,
            }
        
        article_groups[group_key]["urls"].append(page_url)
        article_groups[group_key]["clicks"] += row.get("clicks", 0)
        article_groups[group_key]["impressions"] += row.get("impressions", 0)
        article_groups[group_key]["ctr"] += row.get("ctr", 0.0)
        article_groups[group_key]["position"] += row.get("position", 0.0)
        article_groups[group_key]["count"] += 1
    
    # Calculate average metrics and sort by clicks
    data = []
    for group_key, group_data in article_groups.items():
        count = group_data["count"]
        data.append(
            {
                "site_url": site_url,
                "site_label": site_label,
                "panel": panel_label,
                "search_type": search_type,
                "article_id": group_key,
                "urls": group_data["urls"],
                "url_count": count,
                "clicks": group_data["clicks"],
                "impressions": group_data["impressions"],
                "ctr": group_data["ctr"] / count if count > 0 else 0.0,
                "position": group_data["position"] / count if count > 0 else 0.0,
            }
        )
    
    df = pd.DataFrame(data)
    
    # Sort by clicks descending and take top_n
    df = df.sort_values("clicks", ascending=False).head(top_n).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    
    # Fetch titles for the first URL of each article
    df["page_title"] = df["urls"].apply(lambda urls: fetch_page_title(urls[0]))
    
    return df[
        [
            "site_url",
            "site_label",
            "panel",
            "search_type",
            "rank",
            "article_id",
            "urls",
            "url_count",
            "page_title",
            "clicks",
            "impressions",
            "ctr",
            "position",
        ]
    ]


def fetch_top_performers_for_all(
    service,
    sites: Dict[str, str],
    search_types: Dict[str, str],
    start_date: str,
    end_date: str,
    top_n: int = 3,
) -> pd.DataFrame:
    """Fetch top pages for all configured sites and channels."""
    frames: List[pd.DataFrame] = []

    for site_url, site_label in sites.items():
        for panel_label, search_type in search_types.items():
            print(
                f"Hole Top-{top_n} Performer für {site_label} / {panel_label} ({search_type}) ..."
            )
            frames.append(
                fetch_top_performers(
                    service=service,
                    site_url=site_url,
                    site_label=site_label,
                    panel_label=panel_label,
                    search_type=search_type,
                    start_date=start_date,
                    end_date=end_date,
                    top_n=top_n,
                )
            )

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def format_top_performers_text(
    top_df: pd.DataFrame,
    site_label: str,
    panel_label: str,
    top_n: int = 3,
) -> str:
    """Build a compact text block for a site's top performers."""
    if top_df is None or top_df.empty:
        return f"Top {top_n} Performer Vorwoche: keine Daten"

    subset = top_df[
        (top_df["site_label"] == site_label) & (top_df["panel"] == panel_label)
    ].copy()

    if subset.empty:
        return f"Top {top_n} Performer Vorwoche: keine Daten"

    subset = subset.sort_values("rank")
    lines = [f"Top {top_n} Performer Vorwoche:"]

    for _, row in subset.iterrows():
        page_title = row.get("page_title", row["article_id"])
        clicks = _format_number(row["clicks"])
        impressions = _format_number(row["impressions"])
        url_count = row.get("url_count", 1)
        
        # Add URL count info if multiple URLs for this article
        url_info = f" ({url_count} URLs)" if url_count > 1 else ""
        
        lines.append(
            f"{int(row['rank'])}. {page_title}{url_info} | Klicks: {clicks} | Impr.: {impressions}"
        )

    return "\n".join(lines)


def _format_number(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", ".")