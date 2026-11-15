#!/usr/bin/env python3
"""Holt die Kanalzahlen von YouTube und schreibt daten.json neu.

Läuft täglich über GitHub Actions (.github/workflows/daten.yml).
Benötigte Geheimnisse (GitHub → Settings → Secrets → Actions):
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
  REFRESH_TOKEN_MUSIC (Konto mit Klangwerk Music),
  REFRESH_TOKEN_KIDS  (Konto mit Klangwerk Kids)
Fehlt ein Token oder schlägt ein Kanal fehl, bleiben dessen alte Zahlen stehen.
Nur Python-Standardbibliothek, keine Zusatzpakete nötig.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DATEI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daten.json")

# kanal-id im Dashboard → Einstellungen
KANAELE = {
    "music": {"token_env": "REFRESH_TOKEN_MUSIC", "quellen_zeitraum": "gesamt", "videos_zeitraum": "gesamt", "max_videos": 15},
    "kids": {"token_env": "REFRESH_TOKEN_KIDS", "quellen_zeitraum": "28t", "videos_zeitraum": "28t", "max_videos": 15},
}
# Ab diesem Datum veröffentlichte Videos auf Klangwerk Kids zählen als „Kinderlied“
KINDERLIED_AB = "2026-10-01"

QUELLEN_NAMEN = {
    "SHORTS": "Shorts-Feed",
    "RELATED_VIDEO": "Videovorschläge",
    "SUBSCRIBER": "Startseite & Abos",
    "YT_SEARCH": "YouTube-Suche",
    "YT_CHANNEL": "Kanalseite",
    "PLAYLIST": "Playlists",
    "YT_PLAYLIST_PAGE": "Playlists",
    "EXT_URL": "Extern",
    "NO_LINK_OTHER": "Direkt/unbekannt",
    "NOTIFICATION": "Benachrichtigungen",
    "END_SCREEN": "Abspanne",
}


def http(url, data=None, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} bei {url.split('?')[0]}: {e.read().decode()[:400]}") from None


def zugangs_token(refresh_token):
    antwort = http("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    return antwort["access_token"]


def bericht(token, start, ende, metrics, dimensions=None, sort=None, max_results=None, filters=None):
    q = {"ids": "channel==MINE", "startDate": start, "endDate": ende, "metrics": metrics}
    if dimensions:
        q["dimensions"] = dimensions
    if sort:
        q["sort"] = sort
    if max_results:
        q["maxResults"] = max_results
    if filters:
        q["filters"] = filters
    antwort = http("https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode(q), token=token)
    namen = [h["name"] for h in antwort.get("columnHeaders", [])]
    return [dict(zip(namen, zeile)) for zeile in antwort.get("rows", []) or []]


def dauer_sekunden(iso):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def laenge_text(sek):
    h, rest = divmod(sek, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def kurz_titel(titel):
    # Emojis und doppelte Leerzeichen entfernen, damit die Tabelle ruhig bleibt
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", titel)
    t = t.replace(" | Klangwerk Kids", "").replace("| Klangwerk Kids", "")
    return re.sub(r"\s{2,}", " ", t).strip(" |")


def kanal_holen(kanal, cfg, heute):
    token = zugangs_token(os.environ[cfg["token_env"]])
    # YouTube Analytics hat ca. 2 Tage Verzögerung
    ende = heute - dt.timedelta(days=2)
    start = ende - dt.timedelta(days=27)
    s28, e = start.isoformat(), ende.isoformat()
    s_ges = "2005-01-01"

    # Tageswerte
    tage = {r["day"]: r for r in bericht(token, s28, e, "views,estimatedMinutesWatched,subscribersGained,subscribersLost", "day", "day")}
    taeglich = []
    for i in range(28):
        tag = (start + dt.timedelta(days=i)).isoformat()
        r = tage.get(tag, {})
        taeglich.append({
            "kanal": kanal, "datum": tag,
            "aufrufe": int(r.get("views", 0)),
            "stunden": round(r.get("estimatedMinutesWatched", 0) / 60, 1),
            "abos": int(r.get("subscribersGained", 0) - r.get("subscribersLost", 0)),
        })

    # Summen
    z28 = (bericht(token, s28, e, "views,estimatedMinutesWatched,subscribersGained,subscribersLost,averageViewPercentage") or [{}])[0]
    zges = (bericht(token, s_ges, e, "views,estimatedMinutesWatched,subscribersGained,subscribersLost") or [{}])[0]

    # Abonnenten gesamt: genaue Zahl aus Analytics, sonst gerundete Zahl aus der Data API
    abos_gesamt = int(zges.get("subscribersGained", 0) - zges.get("subscribersLost", 0))
    kanal_info = http("https://www.googleapis.com/youtube/v3/channels?part=statistics,snippet&mine=true", token=token)
    items = kanal_info.get("items") or []
    if items:
        api_abos = int(items[0]["statistics"].get("subscriberCount", 0))
        if abos_gesamt <= 0 or abs(abos_gesamt - api_abos) > max(50, api_abos * 0.05):
            abos_gesamt = api_abos

    ueberblick = {
        "kanal": kanal,
        "abos_gesamt": abos_gesamt,
        "abos_28t": int(z28.get("subscribersGained", 0) - z28.get("subscribersLost", 0)),
        "aufrufe_28t": int(z28.get("views", 0)),
        "stunden_28t": round(z28.get("estimatedMinutesWatched", 0) / 60, 1),
        "aufrufe_gesamt": int(zges.get("views", 0)),
        "stunden_gesamt": round(zges.get("estimatedMinutesWatched", 0) / 60, 1),
        "gesehen_pct_28t": round(z28.get("averageViewPercentage", 0), 1),
    }

    # Zugriffsquellen
    q_start = s_ges if cfg["quellen_zeitraum"] == "gesamt" else s28
    summen = {}
    for r in bericht(token, q_start, e, "views", "insightTrafficSourceType", "-views"):
        name = QUELLEN_NAMEN.get(r["insightTrafficSourceType"], "Sonstiges")
        summen[name] = summen.get(name, 0) + int(r["views"])
    quellen = sorted(({"kanal": kanal, "quelle": k, "aufrufe": v} for k, v in summen.items() if v > 0), key=lambda x: -x["aufrufe"])
    # „Sonstiges“ immer ans Ende
    quellen.sort(key=lambda x: x["quelle"] == "Sonstiges")

    # Videos
    v_start = s_ges if cfg["videos_zeitraum"] == "gesamt" else s28
    zeilen = bericht(token, v_start, e, "views,estimatedMinutesWatched,subscribersGained,subscribersLost,averageViewPercentage",
                     "video", "-views", cfg["max_videos"])
    ids = [z["video"] for z in zeilen]
    infos = {}
    if ids:
        antwort = http("https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails&id=" + ",".join(ids), token=token)
        infos = {v["id"]: v for v in antwort.get("items", [])}
    videos = []
    for z in zeilen:
        info = infos.get(z["video"], {})
        sn = info.get("snippet", {})
        titel = sn.get("title", z["video"])
        sek = dauer_sekunden(info.get("contentDetails", {}).get("duration"))
        ist_short = "#short" in titel.lower() or (0 < sek <= 60)
        if kanal == "kids":
            kategorie = "Kinderlied" if sn.get("publishedAt", "")[:10] >= KINDERLIED_AB else "Alte Videos"
        else:
            kategorie = "Violine"
        t = kurz_titel(titel)
        if any(v["titel"] == t for v in videos):  # Titel müssen eindeutig sein
            t += " (Short)" if ist_short else " (Video)"
        videos.append({
            "kanal": kanal, "titel": t, "typ": "Short" if ist_short else "Video", "laenge": laenge_text(sek),
            "aufrufe": int(z.get("views", 0)),
            "stunden": round(z.get("estimatedMinutesWatched", 0) / 60, 1),
            "abos": int(z.get("subscribersGained", 0) - z.get("subscribersLost", 0)),
            "wiedergabe_pct": round(z.get("averageViewPercentage", 0), 1),
            "kategorie": kategorie,
        })
    return {"taeglich": taeglich, "ueberblick": [ueberblick], "quellen": quellen, "videos": videos,
            "zeitraum": {"von": s28, "bis": e}}


def main():
    heute = dt.date.today()
    with open(DATEI, encoding="utf-8") as f:
        daten = json.load(f)
    if not os.environ.get("GOOGLE_CLIENT_ID") or not os.environ.get("GOOGLE_CLIENT_SECRET"):
        print("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET fehlen – nichts geändert.")
        return 0
    fehler, erfolgreich = [], []
    daten.setdefault("zeitraum", {})
    for kanal, cfg in KANAELE.items():
        if not os.environ.get(cfg["token_env"]):
            print(f"{kanal}: {cfg['token_env']} fehlt – alte Zahlen bleiben.")
            continue
        try:
            neu = kanal_holen(kanal, cfg, heute)
        except Exception as ex:  # ein Kanal darf den anderen nicht blockieren
            fehler.append(f"{kanal}: {ex}")
            continue
        for teil in ("taeglich", "ueberblick", "quellen", "videos"):
            daten[teil] = [r for r in daten.get(teil, []) if r.get("kanal") != kanal] + neu[teil]
        daten["zeitraum"][kanal] = neu["zeitraum"]
        erfolgreich.append(kanal)
        print(f"{kanal}: aktualisiert ({neu['ueberblick'][0]['aufrufe_28t']} Aufrufe in 28 Tagen)")
    if erfolgreich:
        daten["stand"] = heute.strftime("%d.%m.%Y")
        with open(DATEI, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=1)
    for f_ in fehler:
        print("FEHLER", f_, file=sys.stderr)
    return 1 if fehler and not erfolgreich else 0


if __name__ == "__main__":
    sys.exit(main())
