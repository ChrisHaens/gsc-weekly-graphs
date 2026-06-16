# GSC Weekly Graphs

Ein Python-Tool zur Visualisierung von Google Search Console Metriken für mehrere Websites. Das Programm erstellt automatisch wöchentliche Diagramme mit Klicks und Impressionen über verschiedene Suchtypen (Web, News, Discover).
Zur Nutzung in den Audience-Weekly-Meetings.

## Funktionsweise

Das Programm holt täglich aggregierte Daten aus der Google Search Console API für mehrere konfigurierte Websites und erstellt daraus Zeitreihen-Diagramme. Die Daten werden sowohl als CSV-Datei gespeichert als auch visuell aufbereitet.

### Features

- **Mehrere Websites**: Unterstützt gleichzeitige Abfrage mehrerer GSC-Properties
- **Verschiedene Suchtypen**: Web-Suche, Google News und Discover
- **Flexible Zeiträume**: Konfigurierbare Anzahl von Tagen zurück
- **Automatische Diagramme**: 
  - Einzeldiagramme pro Website und Panel
  - Kombiniertes Übersichtsdiagramm mit allen Websites
- **Vorjahresvergleich**: Optional können Vorjahreswerte als gestrichelte Linien angezeigt werden
- **Wöchentliche Organisation**: Diagramme werden automatisch nach Kalenderwochen sortiert

## Voraussetzungen

### Software

- Python 3.x
- Google Cloud Service Account mit aktivierter Search Console API

### Python-Pakete

```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client pandas matplotlib
```

## Setup

### 1. Google Cloud Service Account erstellen

1. Gehe zur [Google Cloud Console](https://console.cloud.google.com/)
2. Erstelle ein neues Projekt oder wähle ein bestehendes aus
3. Aktiviere die "Google Search Console API"
4. Erstelle einen Service Account und lade die JSON-Datei herunter
5. Benenne die JSON-Datei in `gsc.json` um und lege sie im Projektverzeichnis ab

### 2. Search Console Berechtigungen

Füge die Service Account E-Mail-Adresse als Nutzer in der Google Search Console für alle gewünschten Properties hinzu:

1. Gehe zu [Google Search Console](https://search.google.com/search-console)
2. Wähle die Property aus
3. Gehe zu "Einstellungen" → "Nutzer und Berechtigungen"
4. Füge die Service Account E-Mail mit "Eingeschränkt"-Berechtigung hinzu

### 3. Konfiguration anpassen

Bearbeite die Konfigurationsvariablen in `run.py`:

```python
# GSC-Properties (mit Slash am Ende!)
SITES = {
    "https://example.com/": "Example",
    # Weitere Websites hinzufügen...
}

# Zeitraum in Tagen
DAYS_BACK = 90
```

## Verwendung

### Basis-Verwendung

```bash
python run.py
```

Erstellt Diagramme für den konfigurierten Zeitraum ohne Vorjahresvergleich.

### Mit Vorjahresvergleich

```bash
python run.py --previous-year
```

Lädt zusätzlich die Daten vom Vorjahr und zeigt diese als gestrichelte Linien in den Diagrammen an. Die Vorjahreswerte werden dabei automatisch um 365 Tage verschoben, um einen direkten Vergleich zu ermöglichen.

**Visualisierung:**
- **Klicks (aktuell)**: durchgezogene blaue Linie
- **Klicks (Vorjahr)**: gestrichelte blaue Linie (--), halbtransparent
- **Impressionen (aktuell)**: gestrichelte grüne Linie (--)
- **Impressionen (Vorjahr)**: gepunktete grüne Linie (:), halbtransparent

### Hilfe anzeigen

```bash
python run.py --help
```

## Ausgabe

### CSV-Datei

- **Datei**: `gsc_daily_metrics.csv`
- **Inhalt**: Alle abgerufenen Rohdaten mit Datum, Klicks, Impressionen, CTR und Position

### Diagramme

Diagramme werden in Unterordnern nach Kalenderwoche organisiert:

```
diagrams/
├── 2026_KW2/
│   ├── RPO_WEB.png
│   ├── RPO_NEWS.png
│   ├── RPO_DISCO.png
│   ├── GA_WEB.png
│   ├── ...
│   └── combined_all_sites.png
├── 2026_KW3/
└── ...
```

- **Einzeldiagramme**: Ein Diagramm pro Website und Suchtyp (z.B. `RPO_WEB.png`)
- **Kombiniertes Diagramm**: `combined_all_sites.png` - Übersicht über alle Websites in einem Bild

### Diagramm-Features

- **Dual-Y-Achsen**: Klicks (links) und Impressionen (rechts)
- **Datumsformat**: TT.MM.JJJJ
- **Tausendertrennzeichen**: Deutsche Formatierung (Punkt als Tausendertrennzeichen)
- **Metadaten**: Betrachtungszeitraum wird am unteren Rand angezeigt
- **Hochauflösend**: 150 DPI für gute Druckqualität

## Konfigurationsoptionen

### Suchtypen anpassen

```python
SEARCH_TYPES = {
    "WEB": "web",           # Organische Websuche
    "NEWS": "googleNews",   # Google News
    "DISCO": "discover",    # Google Discover
}
```

### Zeitraum ändern

```python
DAYS_BACK = 90  # Anzahl der Tage zurück
```

**Hinweis**: GSC-API liefert Daten mit 2-3 Tagen Verzögerung, daher wird automatisch 2 Tage vom aktuellen Datum abgezogen.

### Service Account Datei

```python
ACCESS_JSON = "gsc.json"  # Pfad zur Service Account JSON-Datei
```

## Fehlerbehebung

### "Permission denied" oder 403-Fehler

- Stelle sicher, dass der Service Account in der Search Console als Nutzer hinzugefügt wurde
- Überprüfe, ob die richtige Property-URL verwendet wird (mit/ohne Trailing Slash beachten!)

### "No data returned"

- Prüfe, ob die Property in der Search Console Daten für den gewählten Zeitraum hat
- Neue Websites können bis zu 48 Stunden brauchen, bis Daten verfügbar sind

### Import-Fehler

```bash
pip install --upgrade google-auth google-api-python-client pandas matplotlib
```

## Struktur

```
gsc-weekly-graphs/
├── run.py                  # Hauptprogramm
├── gsc.json               # Service Account Credentials (nicht in Git!)
├── gsc_daily_metrics.csv  # Ausgabe: Rohdaten
├── README.md              # Diese Datei
├── .gitignore             # Git-Konfiguration
└── diagrams/              # Diagramm-Ausgabe (nicht in Git!)
    ├── 2026_KW2/
    ├── 2026_KW3/
    └── ...
```

## Git

Die `.gitignore` ist so konfiguriert, dass folgende Dateien/Ordner **nicht** in Git eingecheckt werden:
- `diagrams/` - Generierte Diagramme
- `gsc.json` - Service Account Credentials (sensibel!)
- `*.csv` - Datendateien

## Lizenz

Internes Tool - keine öffentliche Lizenz.
