#!/usr/bin/env python3
"""
gsc_discover_articles.py

Offline-first Discover analytics with domain-level scoring.
Fetches GSC Discover data with pagination, caches to disk, and runs analyses offline.
"""

from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
import matplotlib.pyplot as plt
import os
import argparse
import re
import shutil
from pathlib import Path
from typing import Optional, Tuple
import warnings

warnings.filterwarnings('ignore')

# --- CONFIG --------------------------------------------------------------

ACCESS_JSON = "gsc.json"

SITES = {
    "https://rp-online.de/": "RPO",
    "https://ga.de/": "GA",
    "https://www.saarbruecker-zeitung.de/": "SZ",
    "https://www.volksfreund.de/": "TV",
    "https://www.tonight.de/": "Tonight",
}

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

DEFAULT_CACHE_DIR = "data/gsc_cache"
DEFAULT_ROLLING_WINDOW = 28
MAX_PAGES = 100
ROW_LIMIT = 25000

# --- AUTH ---------------------------------------------------------------

def get_service():
    """Initialize GSC API service."""
    creds = service_account.Credentials.from_service_account_file(
        ACCESS_JSON, scopes=SCOPES
    )
    return build("searchconsole", "v1", credentials=creds)


# --- CACHE MANAGEMENT ---------------------------------------------------

def get_cache_path(cache_dir: str, site_label: str, start_date: str, end_date: str, fmt: str = "parquet") -> Path:
    """Get cache file path for a specific site and date range."""
    ext = "parquet" if fmt == "parquet" else "csv"
    cache_folder = Path(cache_dir) / site_label / "discover" / "date_page"
    cache_folder.mkdir(parents=True, exist_ok=True)
    return cache_folder / f"{start_date}_{end_date}.{ext}"


def purge_discover_cache(cache_dir: str, site_label: Optional[str] = None):
    """
    Purge Discover cache.
    If site_label is None, purge ALL sites.
    If site_label is provided, purge only that site's Discover cache.
    """
    if site_label is None:
        # Purge all sites
        for label in SITES.values():
            site_cache_dir = Path(cache_dir) / label / "discover" / "date_page"
            if site_cache_dir.exists():
                print(f"[CACHE] Purging all Discover cache for {label}: {site_cache_dir}")
                shutil.rmtree(site_cache_dir)
    else:
        # Purge specific site
        site_cache_dir = Path(cache_dir) / site_label / "discover" / "date_page"
        if site_cache_dir.exists():
            print(f"[CACHE] Purging Discover cache for {site_label}: {site_cache_dir}")
            shutil.rmtree(site_cache_dir)


def load_from_cache(cache_path: Path) -> Optional[pd.DataFrame]:
    """Load cached data if it exists."""
    if cache_path.exists():
        print(f"[CACHE] Loading from cache: {cache_path}")
        if cache_path.suffix == ".parquet":
            try:
                return pd.read_parquet(cache_path)
            except ImportError:
                print("[CACHE] Parquet library not available, trying CSV fallback...")
                csv_path = cache_path.with_suffix(".csv")
                if csv_path.exists():
                    return pd.read_csv(csv_path)
        elif cache_path.suffix == ".csv":
            return pd.read_csv(cache_path)
    return None


def save_to_cache(df: pd.DataFrame, cache_path: Path, fmt: str = "parquet"):
    """Save DataFrame to cache."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    
    if fmt == "parquet":
        try:
            df.to_parquet(cache_path, index=False)
            print(f"[CACHE] Saved to cache (Parquet): {cache_path}")
            return
        except ImportError:
            print("[CACHE] Parquet library not available, falling back to CSV...")
            cache_path = cache_path.with_suffix(".csv")
    
    df.to_csv(cache_path, index=False, encoding="utf-8")
    print(f"[CACHE] Saved to cache (CSV): {cache_path}")


# --- DATA FETCHING WITH PAGINATION --------------------------------------

def fetch_discover_data_paginated(service, site_url: str, site_label: str,
                                  start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch Discover data with pagination support.
    Returns DataFrame with columns: site_url, site_label, search_type, date, page, clicks, impressions, ctr, position
    """
    all_rows = []
    start_row = 0
    page_num = 0
    
    while True:
        page_num += 1
        
        if page_num > MAX_PAGES:
            print(f"[WARNING] Reached max pages limit ({MAX_PAGES}) for {site_label}. Stopping pagination.")
            break
        
        print(f"[API] Fetching {site_label} page {page_num} (startRow={start_row})...")
        
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["date", "page"],
            "rowLimit": ROW_LIMIT,
            "startRow": start_row,
            "dataState": "all",
            "searchType": "discover",
        }
        
        try:
            response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except Exception as e:
            print(f"[ERROR] API request failed for {site_label}: {e}")
            break
        
        rows = response.get("rows", [])
        
        if not rows:
            print(f"[API] No more rows for {site_label}. Total fetched: {len(all_rows)}")
            break
        
        print(f"[API] Received {len(rows)} rows for {site_label}")
        
        for r in rows:
            row_date = r["keys"][0]
            page_url = r["keys"][1]
            clicks = r.get("clicks", 0)
            impressions = r.get("impressions", 0)
            ctr = r.get("ctr", 0.0)
            position = r.get("position", 0.0)
            
            all_rows.append({
                "site_url": site_url,
                "site_label": site_label,
                "search_type": "discover",
                "date": row_date,
                "page": page_url,
                "clicks": clicks,
                "impressions": impressions,
                "ctr": ctr,
                "position": position,
            })
        
        if len(rows) < ROW_LIMIT:
            print(f"[API] Received fewer rows than limit ({len(rows)} < {ROW_LIMIT}). Stopping pagination.")
            break
        
        start_row += ROW_LIMIT
    
    if not all_rows:
        print(f"[WARNING] No Discover data found for {site_label}")
        return pd.DataFrame(columns=[
            "site_url", "site_label", "search_type", "date", "page",
            "clicks", "impressions", "ctr", "position"
        ])
    
    print(f"[API] Total rows fetched for {site_label}: {len(all_rows)}")
    return pd.DataFrame(all_rows)


def fetch_or_load_discover_data(service, site_url: str, site_label: str,
                                start_date: str, end_date: str,
                                cache_dir: str, use_cache: bool, cache_format: str) -> pd.DataFrame:
    """
    Fetch or load Discover data with strict cache invalidation rules.
    
    Rules:
    - If use_cache=True AND exact cache file exists → load
    - If use_cache=True AND cache miss → purge site's cache, fetch, save
    - If use_cache=False → always purge site's cache, fetch, save
    """
    cache_path = get_cache_path(cache_dir, site_label, start_date, end_date, cache_format)
    
    if use_cache:
        # Try to load from cache
        df = load_from_cache(cache_path)
        if df is not None:
            print(f"[CACHE] Cache HIT for {site_label}")
            return df
        else:
            print(f"[CACHE] Cache MISS for {site_label}")
            # Purge this site's cache before fetching
            purge_discover_cache(cache_dir, site_label)
    else:
        # Always purge when not using cache
        purge_discover_cache(cache_dir, site_label)
    
    # Fetch fresh data
    df = fetch_discover_data_paginated(service, site_url, site_label, start_date, end_date)
    
    # Save to cache
    if not df.empty:
        save_to_cache(df, cache_path, cache_format)
    
    return df


# --- ARTICLE ID EXTRACTION ----------------------------------------------

def extract_article_id(page_url: str) -> Optional[str]:
    """Extract article ID from page URL using regex for _aid-{article_id}."""
    match = re.search(r'_aid-(\d+)', page_url)
    return match.group(1) if match else None


def enrich_with_article_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Add article_id column and filter out rows without valid article IDs."""
    df = df.copy()
    df["article_id"] = df["page"].apply(extract_article_id)
    
    initial_count = len(df)
    df = df[df["article_id"].notna()].copy()
    filtered_count = initial_count - len(df)
    
    if filtered_count > 0:
        print(f"[INFO] Filtered out {filtered_count} rows without article IDs ({filtered_count/initial_count*100:.1f}%)")
    
    return df


# --- ANALYSIS: DAILY DISCOVER ARTICLES ----------------------------------

def analyze_daily_discover_articles(df: pd.DataFrame, df_prev: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Compute daily unique Discover articles per domain.
    
    Returns DataFrame with columns:
    - site_label
    - date
    - discover_articles (count of unique article IDs with impressions > 0)
    - discover_articles_prev (if df_prev is provided)
    - delta_abs
    - delta_pct
    """
    # Enrich with article IDs
    df = enrich_with_article_ids(df)
    
    if df.empty:
        print("[WARNING] No valid article IDs found in data")
        return pd.DataFrame()
    
    # Aggregate per (site_label, date, article_id)
    agg = df.groupby(["site_label", "date", "article_id"]).agg({
        "impressions": "sum",
        "clicks": "sum"
    }).reset_index()
    
    # Filter: article "landed" if impressions > 0
    agg = agg[agg["impressions"] > 0]
    
    # Count unique articles per (site_label, date)
    daily = agg.groupby(["site_label", "date"]).agg({
        "article_id": "nunique"
    }).reset_index()
    daily.rename(columns={"article_id": "discover_articles"}, inplace=True)
    
    # YoY comparison
    if df_prev is not None and not df_prev.empty:
        df_prev = enrich_with_article_ids(df_prev)
        
        if not df_prev.empty:
            # Shift prev year dates forward by 365 days
            df_prev = df_prev.copy()
            df_prev["date"] = pd.to_datetime(df_prev["date"]) + timedelta(days=365)
            df_prev["date"] = df_prev["date"].dt.strftime("%Y-%m-%d")
            
            agg_prev = df_prev.groupby(["site_label", "date", "article_id"]).agg({
                "impressions": "sum"
            }).reset_index()
            
            agg_prev = agg_prev[agg_prev["impressions"] > 0]
            
            daily_prev = agg_prev.groupby(["site_label", "date"]).agg({
                "article_id": "nunique"
            }).reset_index()
            daily_prev.rename(columns={"article_id": "discover_articles_prev"}, inplace=True)
            
            # Merge
            daily = daily.merge(daily_prev, on=["site_label", "date"], how="left")
            daily["discover_articles_prev"] = daily["discover_articles_prev"].fillna(0).astype(int)
            daily["delta_abs"] = daily["discover_articles"] - daily["discover_articles_prev"]
            daily["delta_pct"] = (daily["delta_abs"] / daily["discover_articles_prev"].replace(0, 1)) * 100
        else:
            daily["discover_articles_prev"] = 0
            daily["delta_abs"] = 0
            daily["delta_pct"] = 0.0
    else:
        daily["discover_articles_prev"] = 0
        daily["delta_abs"] = 0
        daily["delta_pct"] = 0.0
    
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values(["site_label", "date"])
    
    return daily


# --- ANALYSIS: ARTICLE LIFETIME -----------------------------------------

def analyze_article_lifetime(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute article lifetime metrics per domain.
    
    Returns DataFrame with columns:
    - site_label
    - article_id
    - first_date
    - last_date
    - active_days (count of days with impressions > 0)
    - lifetime_days (last_date - first_date + 1)
    - total_impressions
    - total_clicks
    """
    df = enrich_with_article_ids(df)
    
    if df.empty:
        print("[WARNING] No valid article IDs found in data")
        return pd.DataFrame()
    
    # Filter rows with impressions > 0
    df = df[df["impressions"] > 0].copy()
    
    # Aggregate per (site_label, article_id, date)
    agg = df.groupby(["site_label", "article_id", "date"]).agg({
        "impressions": "sum",
        "clicks": "sum"
    }).reset_index()
    
    # Filter days with impressions > 0
    agg = agg[agg["impressions"] > 0]
    
    # Compute lifetime metrics per article
    lifetime = agg.groupby(["site_label", "article_id"]).agg(
        first_date=("date", "min"),
        last_date=("date", "max"),
        active_days=("date", "count"),
        total_impressions=("impressions", "sum"),
        total_clicks=("clicks", "sum")
    ).reset_index()
    
    # Compute lifetime_days
    lifetime["first_date"] = pd.to_datetime(lifetime["first_date"])
    lifetime["last_date"] = pd.to_datetime(lifetime["last_date"])
    lifetime["lifetime_days"] = (lifetime["last_date"] - lifetime["first_date"]).dt.days + 1
    
    return lifetime


# --- ANALYSIS: DOMAIN SCORE ---------------------------------------------

def compute_rolling_metrics(df: pd.DataFrame, window_days: int = DEFAULT_ROLLING_WINDOW) -> pd.DataFrame:
    """
    Compute rolling window metrics per domain for domain scoring.
    
    Returns DataFrame with columns per (site_label, date):
    - avg_daily_discover_articles (mean over window)
    - clicks_per_article (total clicks / total articles in window)
    - median_lifetime_days (from lifetime analysis)
    """
    # Get daily articles
    daily_articles = analyze_daily_discover_articles(df)
    
    if daily_articles.empty:
        return pd.DataFrame()
    
    # Get article lifetime
    lifetime = analyze_article_lifetime(df)
    
    if lifetime.empty:
        print("[WARNING] No article lifetime data available")
        return pd.DataFrame()
    
    # Enrich df with article IDs for clicks aggregation
    df_enriched = enrich_with_article_ids(df)
    
    # Aggregate clicks per (site_label, date)
    daily_clicks = df_enriched.groupby(["site_label", "date"]).agg({
        "clicks": "sum"
    }).reset_index()
    daily_clicks["date"] = pd.to_datetime(daily_clicks["date"])
    
    # Merge daily articles with clicks
    daily_articles = daily_articles.merge(
        daily_clicks,
        on=["site_label", "date"],
        how="left"
    )
    daily_articles["clicks"] = daily_articles["clicks"].fillna(0)
    
    # Compute rolling metrics per domain
    results = []
    
    for site_label in daily_articles["site_label"].unique():
        site_data = daily_articles[daily_articles["site_label"] == site_label].copy()
        site_data = site_data.sort_values("date")
        
        # Rolling avg of daily articles
        site_data["avg_daily_discover_articles"] = (
            site_data["discover_articles"]
            .rolling(window=window_days, min_periods=1)
            .mean()
        )
        
        # Rolling sum of clicks and articles for clicks_per_article
        site_data["rolling_clicks"] = (
            site_data["clicks"]
            .rolling(window=window_days, min_periods=1)
            .sum()
        )
        
        site_data["rolling_articles"] = (
            site_data["discover_articles"]
            .rolling(window=window_days, min_periods=1)
            .sum()
        )
        
        site_data["clicks_per_article"] = (
            site_data["rolling_clicks"] / site_data["rolling_articles"].replace(0, 1)
        )
        
        # Median lifetime days for this domain
        site_lifetime = lifetime[lifetime["site_label"] == site_label]
        median_lifetime = site_lifetime["lifetime_days"].median() if not site_lifetime.empty else 0
        site_data["median_lifetime_days"] = median_lifetime
        
        results.append(site_data[[
            "site_label", "date",
            "avg_daily_discover_articles",
            "clicks_per_article",
            "median_lifetime_days"
        ]])
    
    return pd.concat(results, ignore_index=True)


def compute_domain_score(rolling_metrics: pd.DataFrame) -> pd.DataFrame:
    """
    Compute Discover Domain Score with per-domain z-score normalization.
    
    Each domain is compared to its OWN historical performance, not to other domains.
    This accounts for different publication sizes (editorial staff size).
    
    Formula:
    discover_index = 0.4 * reach_z + 0.4 * effectiveness_z + 0.2 * persistence_z
    discover_score_0_100 = 50 + 15 * discover_index (clipped to 0-100)
    
    Returns DataFrame with all metrics + z-scores + index + 0-100 score.
    """
    if rolling_metrics.empty:
        return pd.DataFrame()
    
    df = rolling_metrics.copy()
    
    # Z-score normalization PER DOMAIN (over time), not across domains
    # Each domain is compared to its own historical average
    def compute_zscore(series):
        mean = series.mean()
        std = series.std()
        if std == 0:
            return pd.Series([0] * len(series), index=series.index)
        return (series - mean) / std
    
    df["reach_z"] = df.groupby("site_label")["avg_daily_discover_articles"].transform(compute_zscore)
    df["effectiveness_z"] = df.groupby("site_label")["clicks_per_article"].transform(compute_zscore)
    df["persistence_z"] = df.groupby("site_label")["median_lifetime_days"].transform(compute_zscore)
    
    # Compute intermediate index (can be negative)
    df["discover_index"] = (
        0.4 * df["reach_z"] +
        0.4 * df["effectiveness_z"] +
        0.2 * df["persistence_z"]
    )
    
    # Transform to 0-100 score using continuous linear scaling
    # Scale: 50 = average for THIS domain, +15 points ≈ +1 standard deviation
    df["discover_score_0_100"] = (50 + 15 * df["discover_index"]).clip(0, 100)
    
    return df


# --- PLOTTING -----------------------------------------------------------

def plot_daily_articles(daily_df: pd.DataFrame, output_dir: str, rolling_7d: bool = False):
    """Plot daily Discover articles per domain."""
    if daily_df.empty:
        print("[WARNING] No data to plot for daily articles")
        return
    
    for site_label in daily_df["site_label"].unique():
        site_data = daily_df[daily_df["site_label"] == site_label].copy()
        site_data = site_data.sort_values("date")
        
        fig, ax = plt.subplots(figsize=(12, 5))
        
        # Current year
        ax.plot(site_data["date"], site_data["discover_articles"],
                label="Discover Articles", linewidth=2, color="#1f77b4")
        
        # YoY if available
        if "discover_articles_prev" in site_data.columns and site_data["discover_articles_prev"].sum() > 0:
            ax.plot(site_data["date"], site_data["discover_articles_prev"],
                    label="Discover Articles (Vorjahr)", linestyle="--",
                    alpha=0.6, linewidth=1.5, color="#1f77b4")
        
        # Rolling average if requested
        if rolling_7d:
            site_data["rolling_7d"] = site_data["discover_articles"].rolling(window=7, min_periods=1).mean()
            ax.plot(site_data["date"], site_data["rolling_7d"],
                    label="7-Day Rolling Avg", linestyle=":", alpha=0.7, color="#ff7f0e")
        
        ax.set_xlabel("Datum")
        ax.set_ylabel("Anzahl Discover Artikel")
        ax.set_title(f"{site_label} – Tägliche Discover Artikel")
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)
        
        import matplotlib.dates as mdates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m.%Y'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
        fig.autofmt_xdate()
        
        plt.tight_layout()
        
        out_path = os.path.join(output_dir, f"DISCOVER_{site_label}_articles_daily.png")
        plt.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"[PLOT] Saved: {out_path}")


def plot_domain_score_timeseries(domain_score_df: pd.DataFrame, output_dir: str):
    """Plot Discover Domain Score time series for all domains."""
    if domain_score_df.empty:
        print("[WARNING] No data to plot for domain score time series")
        return
    
    fig, ax = plt.subplots(figsize=(14, 7))
    
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
    
    for idx, site_label in enumerate(sorted(domain_score_df["site_label"].unique())):
        site_data = domain_score_df[domain_score_df["site_label"] == site_label].copy()
        site_data = site_data.sort_values("date")
        
        color = colors[idx % len(colors)]
        ax.plot(site_data["date"], site_data["discover_score_0_100"],
                label=site_label, linewidth=2, color=color)
    
    ax.set_xlabel("Datum", fontsize=7)
    ax.set_ylabel("Discover Domain Score (0–100)", fontsize=7)
    ax.set_title("Discover Domain Score – Time Series (alle Domains)", fontsize=13, fontweight='bold')
    ax.legend(loc="upper left", fontsize=10)
    ax.grid(True, alpha=0.3)
    
    # Fixed Y-axis range 0-100
    ax.set_ylim(0, 100)
    
    # Reference lines
    ax.axhline(y=50, color='gray', linestyle='--', linewidth=0.8, alpha=0.4, label='Median (50)')
    
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m.%Y'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    fig.autofmt_xdate()
    
    # Add explanatory text box in German
    legend_text = (
        "Discover Domain Score (0–100)\n"
        "───────────────────────────────\n"
        "Der Score vergleicht die Discover-Performance\n"
        "aller Domains relativ zueinander.\n\n"
        "Berechnung (28-Tage-Fenster):\n"
        "• Reichweite: Ø tägl. Discover-Artikel (40%)\n"
        "• Effektivität: Klicks pro Artikel (40%)\n"
        "• Persistenz: Median Artikel-Lebensdauer (20%)\n\n"
        "Interpretation:\n"
        "• 50 = Durchschnittliche Performance\n"
        "• +15 Punkte ≈ +1 Standardabweichung\n"
        "  (überdurchschnittliche Stärke)\n"
        "• -15 Punkte ≈ -1 Standardabweichung\n"
        "  (unterdurchschnittliche Stärke)\n"
        "• Werte sind auf 0–100 begrenzt\n\n"
        "Beispiel: Score 65 = die Domain liegt\n"
        "1 Standardabweichung über dem Durchschnitt."
    )
    
    plt.tight_layout(rect=[0, 0.22, 1, 1])
    
    # Create two-column legend text for better space utilization
    legend_left = (
        "Discover Domain Score (0–100)\n"
        "───────────────────────────────\n"
        "Der Score zeigt die Discover-Performance\n"
        "jeder Domain relativ zu ihrer eigenen Historie.\n\n"
        "Berechnung (28-Tage-Fenster):\n"
        "• Reichweite: ø tägl. Discover-Artikel (40%)\n"
        "• Effektivität: Klicks pro Artikel (40%)\n"
        "• Persistenz: Median Artikel-Lebensdauer (20%)"
    )
    
    legend_right = (
        "Interpretation (pro Domain):\n"
        "───────────────────────────────\n"
        "• 50 = Durchschnittliche Performance\n"
        "  dieser Domain (über den Zeitraum)\n"
        "• +15 Punkte ≈ +1 Standardabweichung\n"
        "  (überdurchschnittlich für diese Domain)\n"
        "• -15 Punkte ≈ -1 Standardabweichung\n"
        "  (unterdurchschnittlich für diese Domain)\n\n"
        "Scores sind NICHT zwischen Domains vergleichbar!"
    )
    
    fig.text(0.25, 0.18, legend_left, ha='center', va='top',
            fontsize=7.5,
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            family='monospace')
    
    fig.text(0.75, 0.18, legend_right, ha='center', va='top',
            fontsize=7.5,
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            family='monospace')
    
    out_path = os.path.join(output_dir, "DISCOVER_domain_score_timeseries.png")
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[PLOT] Saved: {out_path}")


def plot_domain_scatter(domain_score_df: pd.DataFrame, output_dir: str):
    """
    Plot Reach vs Effectiveness scatter (snapshot from last window).
    Bubble size = median_lifetime_days
    
    NOTE: DISABLED BY DEFAULT
    Scatter plots are not meaningful at domain level due to low N (only 5 domains).
    This visualization is intended for directory-level or topic-level analysis later,
    where N will be much larger and patterns will be more interpretable.
    
    To enable, uncomment the function body below.
    """
    # DISABLED - Uncomment to enable scatter plot
    return
    
    # if domain_score_df.empty:
    #     print("[WARNING] No data to plot for domain scatter")
    #     return
    # 
    # # Get last date's data
    # last_date = domain_score_df["date"].max()
    # snapshot = domain_score_df[domain_score_df["date"] == last_date].copy()
    # 
    # if snapshot.empty:
    #     print("[WARNING] No snapshot data available for scatter plot")
    #     return
    # 
    # fig, ax = plt.subplots(figsize=(10, 8))
    # 
    # colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
    # 
    # for idx, site_label in enumerate(sorted(snapshot["site_label"].unique())):
    #     site_data = snapshot[snapshot["site_label"] == site_label]
    #     
    #     x = site_data["avg_daily_discover_articles"].values[0]
    #     y = site_data["clicks_per_article"].values[0]
    #     size = site_data["median_lifetime_days"].values[0] * 10  # Scale for visibility
    #     color = colors[idx % len(colors)]
    #     
    #     ax.scatter(x, y, s=size, alpha=0.6, color=color, edgecolors='black', linewidth=1.5)
    #     ax.text(x, y, f"  {site_label}", fontsize=10, va='center')
    # 
    # ax.set_xlabel("Reach: Avg Daily Discover Articles")
    # ax.set_ylabel("Effectiveness: Clicks per Article")
    # ax.set_title(f"Discover Domain Analysis (Snapshot: {last_date.strftime('%d.%m.%Y')})")
    # ax.grid(True, alpha=0.3)
    # 
    # # Add legend for bubble size
    # from matplotlib.lines import Line2D
    # legend_elements = [
    #     Line2D([0], [0], marker='o', color='w', label='Bubble Size = Median Lifetime Days',
    #            markerfacecolor='gray', markersize=10, alpha=0.6)
    # ]
    # ax.legend(handles=legend_elements, loc='upper right')
    # 
    # plt.tight_layout()
    # 
    # out_path = os.path.join(output_dir, "DISCOVER_domain_scatter.png")
    # plt.savefig(out_path, dpi=150)
    # plt.close(fig)
    # print(f"[PLOT] Saved: {out_path}")


# --- MAIN ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Discover Analytics: Offline-first workflow with domain-level scoring"
    )
    
    # Date range
    parser.add_argument("--days-back", type=int, default=90, help="Number of days to fetch (default: 90)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--previous-year", action="store_true", help="Include previous year data for YoY comparison")
    
    # Cache
    parser.add_argument("--cache-dir", type=str, default=DEFAULT_CACHE_DIR, help="Cache directory path")
    parser.add_argument("--use-cache", action="store_true", help="Use cached data if available")
    parser.add_argument("--cache-only", action="store_true", help="Only use cache, do not fetch new data")
    parser.add_argument("--purge-cache", action="store_true", help="Purge all Discover cache before fetching")
    parser.add_argument("--format", type=str, choices=["parquet", "csv"], default="parquet", help="Cache format")
    
    # Analyses
    parser.add_argument("--lifetime", action="store_true", help="Run article lifetime analysis")
    parser.add_argument("--domain-score", action="store_true", help="Run domain score analysis")
    parser.add_argument("--rolling-7d", action="store_true", help="Add 7-day rolling average to plots")
    
    args = parser.parse_args()
    
    # Determine output directory
    iso_year, iso_week, _ = date.today().isocalendar()
    output_dir = os.path.join("diagrams", f"{iso_year}_KW{iso_week}")
    os.makedirs(output_dir, exist_ok=True)
    
    # Determine date range
    if args.start and args.end:
        start_date = args.start
        end_date = args.end
    else:
        end = date.today() - timedelta(days=2)
        start = end - timedelta(days=args.days_back)
        start_date = start.isoformat()
        end_date = end.isoformat()
    
    print(f"[INFO] Date range: {start_date} to {end_date}")
    print(f"[INFO] Output directory: {output_dir}")
    
    # Purge cache if requested
    if args.purge_cache:
        print("[CACHE] Purging ALL Discover cache...")
        purge_discover_cache(args.cache_dir)
    
    # Initialize service (only if not cache-only mode)
    service = None
    if not args.cache_only:
        service = get_service()
    
    # Fetch or load current year data
    all_frames = []
    
    for site_url, site_label in SITES.items():
        print(f"\n[SITE] Processing {site_label}...")
        
        if args.cache_only:
            # Only load from cache
            cache_path = get_cache_path(args.cache_dir, site_label, start_date, end_date, args.format)
            df = load_from_cache(cache_path)
            if df is None:
                print(f"[ERROR] No cache found for {site_label} in cache-only mode")
                continue
        else:
            # Fetch or load with cache logic
            df = fetch_or_load_discover_data(
                service, site_url, site_label,
                start_date, end_date,
                args.cache_dir, args.use_cache, args.format
            )
        
        if not df.empty:
            all_frames.append(df)
    
    if not all_frames:
        print("[ERROR] No data available. Exiting.")
        return
    
    df_current = pd.concat(all_frames, ignore_index=True)
    print(f"\n[INFO] Total current year rows: {len(df_current)}")
    
    # Fetch or load previous year data if requested
    df_previous = None
    if args.previous_year:
        print("\n[INFO] Fetching previous year data...")
        
        prev_start = (pd.to_datetime(start_date) - timedelta(days=365)).date().isoformat()
        prev_end = (pd.to_datetime(end_date) - timedelta(days=365)).date().isoformat()
        
        print(f"[INFO] Previous year range: {prev_start} to {prev_end}")
        
        prev_frames = []
        
        for site_url, site_label in SITES.items():
            print(f"\n[SITE] Processing {site_label} (previous year)...")
            
            if args.cache_only:
                cache_path = get_cache_path(args.cache_dir, site_label, prev_start, prev_end, args.format)
                df = load_from_cache(cache_path)
                if df is None:
                    print(f"[WARNING] No cache found for {site_label} previous year")
                    continue
            else:
                df = fetch_or_load_discover_data(
                    service, site_url, site_label,
                    prev_start, prev_end,
                    args.cache_dir, args.use_cache, args.format
                )
            
            if not df.empty:
                prev_frames.append(df)
        
        if prev_frames:
            df_previous = pd.concat(prev_frames, ignore_index=True)
            print(f"\n[INFO] Total previous year rows: {len(df_previous)}")
    
    # Run analyses
    print("\n" + "="*60)
    print("RUNNING ANALYSES")
    print("="*60)
    
    # Default: run domain score if no specific analysis flags are set
    run_domain_score = args.domain_score or (not args.lifetime and not args.domain_score)
    
    # Daily Discover Articles (always run for plots)
    print("\n[ANALYSIS] Computing daily Discover articles...")
    daily_articles_df = analyze_daily_discover_articles(df_current, df_previous)
    
    if not daily_articles_df.empty:
        out_path = os.path.join(output_dir, "discover_articles_daily.csv")
        daily_articles_df.to_csv(out_path, index=False)
        print(f"[OUTPUT] Saved: {out_path}")
        
        # Plot per domain
        plot_daily_articles(daily_articles_df, output_dir, args.rolling_7d)
    
    # Article Lifetime
    if args.lifetime:
        print("\n[ANALYSIS] Computing article lifetime...")
        lifetime_df = analyze_article_lifetime(df_current)
        
        if not lifetime_df.empty:
            out_path = os.path.join(output_dir, "discover_article_lifetime.csv")
            lifetime_df.to_csv(out_path, index=False)
            print(f"[OUTPUT] Saved: {out_path}")
            
            # Summary stats
            print("\n[SUMMARY] Article Lifetime Statistics:")
            summary = lifetime_df.groupby("site_label").agg({
                "article_id": "count",
                "lifetime_days": ["mean", "median", "max"],
                "active_days": ["mean", "median"],
                "total_impressions": "sum",
                "total_clicks": "sum"
            }).round(2)
            print(summary)
    
    # Domain Score
    if run_domain_score:
        print("\n[ANALYSIS] Computing Discover Domain Score...")
        rolling_metrics_df = compute_rolling_metrics(df_current, DEFAULT_ROLLING_WINDOW)
        
        if not rolling_metrics_df.empty:
            domain_score_df = compute_domain_score(rolling_metrics_df)
            
            out_path = os.path.join(output_dir, "discover_domain_score_daily.csv")
            domain_score_df.to_csv(out_path, index=False)
            print(f"[OUTPUT] Saved: {out_path}")
            
            # Plot time series
            plot_domain_score_timeseries(domain_score_df, output_dir)
            
            # Plot scatter
            plot_domain_scatter(domain_score_df, output_dir)
            
            # Summary stats for last date
            last_date = domain_score_df["date"].max()
            summary = domain_score_df[domain_score_df["date"] == last_date][
                ["site_label", "discover_score_0_100", "discover_index",
                 "avg_daily_discover_articles", "clicks_per_article", "median_lifetime_days"]
            ].sort_values("discover_score_0_100", ascending=False)
            
            print(f"\n[SUMMARY] Domain Score Ranking ({last_date.strftime('%Y-%m-%d')}):")
            print(summary.to_string(index=False))
    
    print("\n" + "="*60)
    print("ANALYSIS COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()
