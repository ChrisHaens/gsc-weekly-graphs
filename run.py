from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
import matplotlib.pyplot as plt
import os
import argparse

from gsc_top_performers import (
    fetch_top_performers_for_all,
    format_top_performers_text,
)

# --- CONFIG --------------------------------------------------------------

ACCESS_JSON = "gsc.json"  # Pfad zu deinem Service-Account-JSON

# GSC-Properties (mit Slash am Ende!)
SITES = {
    "https://rp-online.de/": "RPO",
    "https://ga.de/": "GA",
    "https://www.saarbruecker-zeitung.de/": "SZ",
    "https://www.volksfreund.de/": "TV",
    "https://www.tonight.de/": "Tonight",
}

# Panels / Labels -> GSC searchType
# Wenn "organisch" etwas anderes als "web" sein soll, hier anpassen.
SEARCH_TYPES = {
    "WEB": "web",         # GSC-Websuche
    "NEWS": "googleNews",     # aktuell identisch zu WEB, nur anderes Label
    "DISCO": "discover",  # Discover
}

DAYS_BACK = 90
OUTPUT_CSV = "gsc_daily_metrics.csv"

# Diagramm-Ordner nach aktueller Kalenderwoche
iso_year, iso_week, _ = date.today().isocalendar()
DIAGRAM_DIR = os.path.join("diagrams", f"{iso_year}_KW{iso_week}")
os.makedirs(DIAGRAM_DIR, exist_ok=True)

# --- AUTH ---------------------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

creds = service_account.Credentials.from_service_account_file(
    ACCESS_JSON, scopes=SCOPES
)

service = build("searchconsole", "v1", credentials=creds)


# --- HELFER -------------------------------------------------------------

def fetch_daily_metrics(site_url: str, panel_label: str, search_type: str,
                        start_date: str, end_date: str) -> pd.DataFrame:
    """
    Holt tägliche Metriken (date, clicks, impressions, ctr, position)
    für eine Property + searchType aus der Search Console.
    """
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["date"],
        "rowLimit": 25000,
        "dataState": "all",
        "searchType": search_type,
    }

    response = (
        service.searchanalytics()
        .query(siteUrl=site_url, body=body)
        .execute()
    )

    rows = response.get("rows", [])
    data = []

    for r in rows:
        row_date = r["keys"][0]
        clicks = r.get("clicks", 0)
        impressions = r.get("impressions", 0)
        ctr = r.get("ctr", 0.0)
        position = r.get("position", 0.0)

        data.append(
            {
                "site_url": site_url,
                "site_label": SITES[site_url],
                "panel": panel_label,        # WEB / ORGANIC / DISCO
                "search_type": search_type,  # web / discover / ...
                "date": row_date,
                "clicks": clicks,
                "impressions": impressions,
                "ctr": ctr,
                "position": position,
            }
        )

    if not data:
        return pd.DataFrame(
            columns=[
                "site_url",
                "site_label",
                "panel",
                "search_type",
                "date",
                "clicks",
                "impressions",
                "ctr",
                "position",
            ]
        )

    return pd.DataFrame(data)


def create_combined_plot(df: pd.DataFrame, show_previous_year: bool = False) -> None:
    """
    Erstellt ein kombiniertes Diagramm mit allen Sites untereinander,
    gruppiert nach Sites. Jede Site zeigt alle Panels nebeneinander.
    """
    # Berechne Vorjahresdaten wenn Flag gesetzt
    df_previous = None
    if show_previous_year:
        # Berechne Datumsbereich für das Vorjahr
        current_dates = pd.to_datetime(df["date"])
        min_date = current_dates.min()
        max_date = current_dates.max()
        
        prev_start = (min_date - timedelta(days=365)).date().isoformat()
        prev_end = (max_date - timedelta(days=365)).date().isoformat()
        
        print(f"Lade Vorjahresdaten: {prev_start} bis {prev_end}")
        
        prev_frames = []
        for site_url in SITES.keys():
            for panel_label, search_type in SEARCH_TYPES.items():
                df_temp = fetch_daily_metrics(
                    site_url=site_url,
                    panel_label=panel_label,
                    search_type=search_type,
                    start_date=prev_start,
                    end_date=prev_end,
                )
                prev_frames.append(df_temp)
        
        if prev_frames:
            df_previous = pd.concat(prev_frames, ignore_index=True)
            df_previous["date"] = pd.to_datetime(df_previous["date"])
            # Verschiebe Vorjahresdaten um 365 Tage nach vorne für Vergleichbarkeit
            df_previous["date"] = df_previous["date"] + timedelta(days=365)
    site_labels = sorted(df["site_label"].unique())
    panel_labels = sorted(df["panel"].unique())
    
    # 4 Sites untereinander, 3 Panels nebeneinander
    n_sites = len(site_labels)
    n_panels = len(panel_labels)
    
    fig, axes = plt.subplots(n_sites, n_panels, figsize=(24, 4 * n_sites))
    
    # Sicherstellen, dass axes immer 2D ist
    if n_sites == 1:
        axes = axes.reshape(1, -1)
    if n_panels == 1:
        axes = axes.reshape(-1, 1)
    
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter
    
    for site_idx, site_label in enumerate(site_labels):
        for panel_idx, panel_label in enumerate(panel_labels):
            ax1 = axes[site_idx, panel_idx]
            
            # Daten filtern
            subset = df[(df["site_label"] == site_label) & (df["panel"] == panel_label)].copy()
            
            if subset.empty:
                ax1.text(0.5, 0.5, 'Keine Daten', ha='center', va='center', transform=ax1.transAxes)
                ax1.set_title(f"{site_label} – {panel_label}")
                continue
            
            subset["date"] = pd.to_datetime(subset["date"])
            subset = subset.sort_values("date")
            
            # Clicks auf linker Y-Achse
            ax1.plot(subset["date"], subset["clicks"], color='#1f77b4', label="Klicks", linewidth=2)
            
            # Vorjahreswerte für Clicks
            if df_previous is not None:
                prev_subset = df_previous[(df_previous["site_label"] == site_label) & (df_previous["panel"] == panel_label)].copy()
                if not prev_subset.empty:
                    prev_subset = prev_subset.sort_values("date")
                    ax1.plot(prev_subset["date"], prev_subset["clicks"], color='#1f77b4', 
                            linestyle='--', label="Klicks (Vorjahr)", alpha=0.6, linewidth=1.5)
            
            ax1.set_ylabel("Klicks", color='#1f77b4')
            ax1.tick_params(axis='y', labelcolor='#1f77b4')
            ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{int(x):,}'.replace(',', '.')))
            
            # Impressionen auf rechter Y-Achse
            ax2 = ax1.twinx()
            ax2.plot(subset["date"], subset["impressions"], linestyle="--", color='#2ca02c', 
                    label="Impressionen", linewidth=2)
            
            # Vorjahreswerte für Impressionen
            if df_previous is not None:
                if not prev_subset.empty:
                    ax2.plot(prev_subset["date"], prev_subset["impressions"], color='#2ca02c', 
                            linestyle=':', label="Impressionen (Vorjahr)", alpha=0.6, linewidth=1.5)
            
            ax2.set_ylabel("Impressionen", color='#2ca02c')
            ax2.tick_params(axis='y', labelcolor='#2ca02c')
            ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{int(x):,}'.replace(',', '.')))
            
            # Titel und Formatierung
            ax1.set_title(f"{site_label} – {panel_label}", fontsize=11, fontweight='bold')
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m.%Y'))
            ax1.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=10))
            ax1.tick_params(axis='x', labelsize=8, rotation=45)
            ax1.tick_params(axis='y', labelsize=9)
            ax2.tick_params(axis='y', labelsize=9)
            
            # Nur für die unterste Zeile X-Label anzeigen
            if site_idx == n_sites - 1:
                ax1.set_xlabel("Datum")
    
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    
    # Informationsbox unten hinzufügen
    min_date = pd.to_datetime(df["date"]).min().strftime('%d.%m.%Y')
    max_date = pd.to_datetime(df["date"]).max().strftime('%d.%m.%Y')
    info_text = f"Betrachtungszeitraum: {min_date} – {max_date} | Datenquelle: Google Search Console API"
    
    fig.text(0.5, 0.01, info_text, ha='center', fontsize=10, 
             bbox=dict(boxstyle='round,pad=0.5', facecolor='lightgray', alpha=0.8))
    
    out_path = os.path.join(DIAGRAM_DIR, "combined_all_sites.png")
    plt.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_time_series(
    df: pd.DataFrame,
    site_label: str,
    panel_label: str,
    show_previous_year: bool = False,
    top_performers_df: pd.DataFrame | None = None,
    top_n: int = 3,
) -> None:
    """
    Baut ein Diagramm (Clicks + Impressions über Zeit) und speichert es
    in DIAGRAM_DIR/{site_label}_{panel_label}.png
    """
    # Daten filtern
    subset = df[(df["site_label"] == site_label) & (df["panel"] == panel_label)].copy()
    if subset.empty:
        return

    subset["date"] = pd.to_datetime(subset["date"])
    subset = subset.sort_values("date")
    highlight_start_str, highlight_end_str = get_previous_week_range(date.today())
    highlight_start = pd.Timestamp(highlight_start_str)
    highlight_end = pd.Timestamp(highlight_end_str)
    highlight_subset = subset[
        (subset["date"] >= highlight_start) & (subset["date"] <= highlight_end)
    ].copy()

    has_top_performers = top_performers_df is not None
    fig, ax1 = plt.subplots(figsize=(12, 5.4 if has_top_performers else 4))

    ax1.plot(subset["date"], subset["clicks"], label="Klicks", linewidth=2)
    if not highlight_subset.empty:
        ax1.axvspan(highlight_start, highlight_end, color="#f6c85f", alpha=0.16)
    
    # Vorjahreswerte für Clicks wenn Flag gesetzt
    if show_previous_year:
        # Berechne Datumsbereich für das Vorjahr
        min_date = subset["date"].min()
        max_date = subset["date"].max()
        
        prev_start = (min_date - timedelta(days=365)).date().isoformat()
        prev_end = (max_date - timedelta(days=365)).date().isoformat()
        
        # Hole entsprechende Site URL
        site_url = [url for url, label in SITES.items() if label == site_label][0]
        search_type = [st for pl, st in SEARCH_TYPES.items() if pl == panel_label][0]
        
        df_prev = fetch_daily_metrics(
            site_url=site_url,
            panel_label=panel_label,
            search_type=search_type,
            start_date=prev_start,
            end_date=prev_end,
        )
        
        if not df_prev.empty:
            df_prev["date"] = pd.to_datetime(df_prev["date"])
            # Verschiebe Datum um 365 Tage nach vorne
            df_prev["date"] = df_prev["date"] + timedelta(days=365)
            df_prev = df_prev.sort_values("date")
            
            ax1.plot(df_prev["date"], df_prev["clicks"], linestyle='--', 
                    label="Klicks (Vorjahr)", alpha=0.6, linewidth=1.5)
    ax1.set_xlabel("Datum")
    
    # Datumsformat auf dd.mm.YYYY setzen
    import matplotlib.dates as mdates
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m.%Y'))
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=15))
    
    # Y-Achse für Klicks mit Tausendertrennzeichen formatieren
    from matplotlib.ticker import FuncFormatter
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{int(x):,}'.replace(',', '.')))
    
    ax1.set_ylabel("Klicks")
    ax1.tick_params(axis='x', labelsize=8)

    ax2 = ax1.twinx()
    ax2.plot(subset["date"], subset["impressions"], linestyle="--", label="Impressionen", linewidth=2)
    
    # Vorjahreswerte für Impressionen wenn Flag gesetzt
    if show_previous_year and not df_prev.empty:
        ax2.plot(df_prev["date"], df_prev["impressions"], linestyle=':', 
                label="Impressionen (Vorjahr)", alpha=0.6, linewidth=1.5)
    
    ax2.set_ylabel("Impressionen")
    
    # Y-Achse für Impressionen als Ganzzahl formatieren
    from matplotlib.ticker import FuncFormatter
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{int(x):,}'.replace(',', '.')))

    title = f"{site_label} – {panel_label}"
    ax1.set_title(title)

    fig.autofmt_xdate()

    # Legende zusammenführen
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    if has_top_performers:
        top_text = format_top_performers_text(top_performers_df, site_label, panel_label, top_n=top_n)
        fig.subplots_adjust(bottom=0.30)
        fig.text(0.02, 0.03, top_text, ha="left", va="bottom", fontsize=9)
    else:
        plt.tight_layout()

    if has_top_performers:
        plt.tight_layout(rect=[0, 0.22, 1, 1])

    filename = f"{site_label}_{panel_label}.png"
    out_path = os.path.join(DIAGRAM_DIR, filename)
    plt.savefig(out_path, dpi=150)
    plt.close(fig)


def get_previous_week_range(reference_date: date) -> tuple[str, str]:
    """Return Monday-Sunday date strings for the previous ISO week."""
    previous_week_end = reference_date - timedelta(days=reference_date.isoweekday())
    previous_week_start = previous_week_end - timedelta(days=6)
    return previous_week_start.isoformat(), previous_week_end.isoformat()


# --- MAIN ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="GSC Weekly Graphs - Holt Daten aus der Google Search Console und erstellt Diagramme"
    )
    parser.add_argument(
        "--previous-year",
        action="store_true",
        help="Zeigt Vorjahreswerte als gestrichelte Linien in den Diagrammen an"
    )
    parser.add_argument(
        "--top-performers",
        action="store_true",
        help="Zeigt die Top 3 Performer pro Publikation und Kanal unterhalb der Einzeldiagramme an"
    )
    args = parser.parse_args()
    
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=DAYS_BACK)

    start_str = start.isoformat()
    end_str = end.isoformat()

    all_frames = []

    for site_url in SITES.keys():
        for panel_label, search_type in SEARCH_TYPES.items():
            print(f"Hole Daten für {site_url} / {panel_label} ({search_type}) ...")

            df = fetch_daily_metrics(
                site_url=site_url,
                panel_label=panel_label,
                search_type=search_type,
                start_date=start_str,
                end_date=end_str,
            )
            all_frames.append(df)

    if not all_frames:
        print("Keine Daten gezogen – irgendwas läuft schief.")
        return

    result = pd.concat(all_frames, ignore_index=True)

    # CTR in Prozent
    result["ctr_pct"] = result["ctr"] * 100

    # CSV speichern
    result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"Fertig. {len(result)} Zeilen nach {OUTPUT_CSV} geschrieben.")

    # Debug-Übersicht
    summary = (
        result.groupby(["site_label", "panel"])
        .agg(
            clicks_total=("clicks", "sum"),
            impressions_total=("impressions", "sum"),
            ctr_avg=("ctr_pct", "mean"),
            position_avg=("position", "mean"),
        )
        .reset_index()
    )

    print("\nKachel-Übersicht (grobes Debugging):")
    print(summary)

    top_performers_df = None
    if args.top_performers:
        top_start_str, top_end_str = get_previous_week_range(date.today())
        print("\nLade Top-Performer pro Publikation und Kanal...")
        print(f"Vorwochen-Zeitraum für Ranking: {top_start_str} bis {top_end_str}")
        top_performers_df = fetch_top_performers_for_all(
            service=service,
            sites=SITES,
            search_types=SEARCH_TYPES,
            start_date=top_start_str,
            end_date=top_end_str,
            top_n=3,
        )

        if not top_performers_df.empty:
            top_performers_path = os.path.join(DIAGRAM_DIR, "top_performers.csv")
            top_performers_df.to_csv(top_performers_path, index=False, encoding="utf-8")
            print(f"Top-Performer CSV: {top_performers_path}")
        else:
            print("Keine Top-Performer-Daten gefunden.")

    # Diagramme pro Site + Panel bauen
    for site_label in result["site_label"].unique():
        for panel_label in result["panel"].unique():
            print(f"Baue Diagramm für {site_label} / {panel_label} ...")
            plot_time_series(
                result,
                site_label,
                panel_label,
                show_previous_year=args.previous_year,
                top_performers_df=top_performers_df,
                top_n=3,
            )

    print(f"Einzelne Diagramme liegen in: {DIAGRAM_DIR}")
    
    # Kombiniertes Diagramm erstellen (alle Sites untereinander, gruppiert nach SITES)
    print("\nErstelle kombiniertes Diagramm...")
    create_combined_plot(result, show_previous_year=args.previous_year)
    print(f"Kombiniertes Diagramm: {DIAGRAM_DIR}/combined_all_sites.png")


if __name__ == "__main__":
    main()
