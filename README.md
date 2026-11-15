# Klangwerk – Kanal-Dashboard

Dashboard für die YouTube-Kanäle **Klangwerk Music** und **Klangwerk Kids**.
Adresse: https://klangwerk.kompassapps.de

## So aktualisiert sich die Seite
- Jeden Morgen holt GitHub Actions (`.github/workflows/daten.yml`) die Zahlen über die YouTube-Schnittstelle
  und schreibt sie in `daten.json` (Skript: `scripts/aktualisieren.py`).
- Von Hand starten: Reiter **Actions** → „Daten aktualisieren“ → **Run workflow**.
- Benötigte Secrets: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `REFRESH_TOKEN_MUSIC`, `REFRESH_TOKEN_KIDS`.
- Fehlt ein Token oder klappt ein Kanal nicht, bleiben dessen alte Zahlen stehen.
