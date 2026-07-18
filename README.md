<div align="center">

  <img src="https://github.com/FwSchultz/assets/blob/main/bots/FwS-Bots/Bot.png" alt="Theken-Cowboys Bot Logo" width="200" height="auto" />
  <h1>Theken-Cowboys Bot</h1>

  <p>Modularer Discord-Bot für Serververwaltung, Automatisierung, Übersetzungen, Audits und Community-Funktionen.</p>

<p>
  <a href="https://github.com/FwSchultz/Theken-Cowboys-Bot/graphs/contributors">
    <img src="https://img.shields.io/github/contributors/FwSchultz/Theken-Cowboys-Bot" alt="contributors" />
  </a>
  <a href="https://github.com/FwSchultz/Theken-Cowboys-Bot/commits/main">
    <img src="https://img.shields.io/github/last-commit/FwSchultz/Theken-Cowboys-Bot" alt="last update" />
  </a>
  <a href="https://github.com/FwSchultz/Theken-Cowboys-Bot/network/members">
    <img src="https://img.shields.io/github/forks/FwSchultz/Theken-Cowboys-Bot" alt="forks" />
  </a>
  <a href="https://github.com/FwSchultz/Theken-Cowboys-Bot/stargazers">
    <img src="https://img.shields.io/github/stars/FwSchultz/Theken-Cowboys-Bot" alt="stars" />
  </a>
  <a href="https://github.com/FwSchultz/Theken-Cowboys-Bot/issues">
    <img src="https://img.shields.io/github/issues/FwSchultz/Theken-Cowboys-Bot" alt="open issues" />
  </a>
  <a href="https://github.com/FwSchultz/Theken-Cowboys-Bot/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/FwSchultz/Theken-Cowboys-Bot.svg" alt="license" />
  </a>
</p>

<h4>
  <a href="https://github.com/FwSchultz/Theken-Cowboys-Bot">Documentation</a>
  <span> · </span>
  <a href="https://github.com/FwSchultz/Theken-Cowboys-Bot/issues">Report Bug</a>
  <span> · </span>
  <a href="https://github.com/FwSchultz/Theken-Cowboys-Bot/issues">Request Feature</a>
</h4>
</div>

<br />

# Inhaltsverzeichnis

- [Über das Projekt](#über-das-projekt)
- [Funktionen](#funktionen)
- [Technik](#technik)
- [Projektstruktur](#projektstruktur)
- [Voraussetzungen](#voraussetzungen)
- [Discord-Bot vorbereiten](#discord-bot-vorbereiten)
- [Konfiguration](#konfiguration)
- [Installation mit Docker Compose](#installation-mit-docker-compose)
- [Lokale Installation ohne Docker](#lokale-installation-ohne-docker)
- [Slash-Befehle](#slash-befehle)
- [Module](#module)
- [Übersetzung und LibreTranslate](#übersetzung-und-libretranslate)
- [Daten und Backups](#daten-und-backups)
- [Logs und Fehleranalyse](#logs-und-fehleranalyse)
- [Sicherheit](#sicherheit)
- [Roadmap](#roadmap)
- [Lizenz](#lizenz)
- [Kontakt](#kontakt)

---

## Über das Projekt

Der **Theken-Cowboys Bot** bündelt mehrere ursprünglich getrennte Discord-Bots in einer modularen Anwendung. Er verwaltet wiederkehrende Serveraufgaben, protokolliert definierte Ereignisse, prüft Rollen und Berechtigungen, übersetzt Nachrichten und stellt zentrale Bedienfelder direkt in Discord bereit.

Die Module lassen sich einzeln aktivieren oder deaktivieren. Laufende Einstellungen werden in einer SQLite-Datenbank gespeichert und können überwiegend über Discord-Panels geändert werden, ohne YAML-Dateien manuell bearbeiten zu müssen.

Das Repository enthält ausschließlich Beispielkonfigurationen. Eigene Server-, Kanal-, Rollen- und Benutzer-IDs müssen vor dem ersten Start eingetragen werden.

---

## Funktionen

- Modularer Aufbau mit separat ladbaren Cogs
- Zentrale Administration über Discord-Panels
- Welcome- und Leave-Nachrichten mit zufälligen Texten
- Hausordnung mit Bestätigungsbutton und automatischer Rollenvergabe
- Voice- und Member-Logging für ausgewählte Rollen
- Automatische Bereinigung alter Member-Logs
- Zeitgesteuertes AutoClear für definierte Bot-Nachrichten
- Geschützte Begriffe, die beim Löschen erhalten bleiben
- Manuelle Kanalbereinigung mit Vorschau und Bestätigungsdialog
- Server-Audit für Rollen, Kanäle und Berechtigungen
- Berichtsausgabe als TXT, JSON oder kombiniert
- Automatische Übersetzung von Texten und Embeds
- Übersetzungsanbieter: OpenAI, DeepL und LibreTranslate
- Frei konfigurierbarer Fallback-Anbieter
- ARC-Raider- und ARCTracker.io-Funktionen
- SQLite-Persistenz für Einstellungen
- Getrennte Logdateien für normale Meldungen und Fehler
- Docker-Compose-Setup inklusive LibreTranslate

---

## Technik

- **Sprache:** Python 3.12
- **Discord-Bibliothek:** discord.py 2.4+
- **Konfiguration:** YAML und Umgebungsvariablen
- **Datenbank:** SQLite
- **HTTP:** aiohttp
- **Übersetzung:** OpenAI, DeepL oder LibreTranslate
- **Deployment:** Docker und Docker Compose

---

## Projektstruktur

```text
Theken-Cowboys-Bot/
├── bot.py
├── cogs/
│   ├── admin.py
│   ├── arc_raider.py
│   ├── audit.py
│   ├── autoclear.py
│   ├── channel_tools.py
│   ├── member_logger.py
│   ├── rules_accept.py
│   ├── settings.py
│   ├── translator.py
│   └── welcome.py
├── config/
│   ├── main.yaml
│   ├── arc_raider.yaml
│   ├── audit.yaml
│   ├── autoclear.yaml
│   ├── memberlog.yaml
│   ├── rules.yaml
│   ├── translator.yaml
│   └── welcome.yaml
├── data/
│   └── .gitkeep
├── logs/
│   └── .gitkeep
├── reports/
│   └── .gitkeep
├── services/
├── translators/
├── utils/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Voraussetzungen

### Empfohlen

- Docker Engine
- Docker Compose Plugin
- Discord-Bot-Anwendung im Discord Developer Portal

### Für den lokalen Betrieb

- Python 3.12 oder neuer
- pip
- optional eine lokale LibreTranslate-Instanz

Für die Übersetzung muss mindestens einer der folgenden Anbieter verfügbar sein:

- OpenAI
- DeepL
- LibreTranslate

LibreTranslate wird bei der Docker-Installation automatisch mitgestartet und benötigt standardmäßig keinen API-Key.

---

## Discord-Bot vorbereiten

1. Im Discord Developer Portal eine neue Anwendung erstellen.
2. Unter **Bot** einen Bot anlegen.
3. Den Bot-Token erzeugen und ausschließlich in der lokalen `.env` speichern.
4. Unter **Privileged Gateway Intents** aktivieren:
   - Server Members Intent
   - Message Content Intent
5. Den Bot mit den benötigten OAuth2-Scopes einladen:
   - `bot`
   - `applications.commands`

Die tatsächlich benötigten Discord-Berechtigungen hängen von den aktivierten Modulen ab. Typischerweise benötigt der Bot:

- Kanäle ansehen
- Nachrichten senden
- Nachrichtenverlauf lesen
- Links einbetten
- Dateien anhängen
- Nachrichten verwalten
- Rollen verwalten

Vergib keine Administrator-Berechtigung, wenn einzelne Rechte ausreichen.

---

## Konfiguration

### 1. Repository klonen

```bash
git clone https://github.com/FwSchultz/Theken-Cowboys-Bot.git
cd Theken-Cowboys-Bot
```

### 2. `.env` erstellen

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Beispiel:

```env
DISCORD_BOT_TOKEN=DEIN_DISCORD_BOT_TOKEN_HIER
GUILD_ID=0

OPENAI_API_KEY=
DEEPL_API_KEY=
LIBRETRANSLATE_URL=http://libretranslate:5000
LIBRETRANSLATE_API_KEY=
```

`GUILD_ID=0` registriert globale Slash-Befehle. Eine konkrete Server-ID beschleunigt die Synchronisation während Entwicklung und Tests.

### 3. Hauptkonfiguration

Die Module werden in `config/main.yaml` aktiviert:

```yaml
modules:
  admin:
    enabled: true
  settings:
    enabled: true
  welcome:
    enabled: true
  rules:
    enabled: true
  memberlog:
    enabled: true
  autoclear:
    enabled: true
  audit:
    enabled: true
  translator:
    enabled: true
  arc_raider:
    enabled: false
  channel_tools:
    enabled: true
```

Trage außerdem deine Guild-ID und die Rollen ein, die Administrationsbefehle verwenden dürfen:

```yaml
guild:
  id: 0

permissions:
  allow_discord_administrator: true
  admin_role_ids: []
```

### 4. Modulkonfigurationen

Alle IDs in den Dateien unter `config/` sind absichtlich auf `0` gesetzt. Ersetze sie durch die IDs deines Servers oder konfiguriere die Module nach dem Start über ihre Panels.

Discord-IDs kopierst du über den Entwicklermodus:

1. Discord-Einstellungen öffnen.
2. **Erweitert → Entwicklermodus** aktivieren.
3. Rechtsklick auf Server, Kanal, Rolle oder Benutzer.
4. **ID kopieren** auswählen.

---

## Installation mit Docker Compose

### 1. Images bauen und Container starten

```bash
docker compose up -d --build
```

Dabei werden zwei Container gestartet:

- `theken-cowboys-bot`
- `theken-cowboys-libretranslate`

LibreTranslate wird automatisch als lokaler Fallback bereitgestellt.

### 2. Status prüfen

```bash
docker compose ps
```

### 3. Logs ansehen

```bash
docker compose logs -f theken-cowboys-bot
```

Oder direkt aus den persistenten Logdateien:

```bash
tail -f logs/bot.log
tail -f logs/error.log
```

### 4. Neu bauen

```bash
docker compose down
docker compose up -d --build
```

### 5. Stoppen

```bash
docker compose down
```

Die SQLite-Datenbank, Logs und Audit-Berichte bleiben auf dem Host erhalten.

---

## Lokale Installation ohne Docker

### 1. Virtuelle Umgebung erstellen

```bash
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

### 3. `.env` und Konfiguration vorbereiten

```bash
cp .env.example .env
```

Beim lokalen Betrieb muss `LIBRETRANSLATE_URL` auf eine erreichbare LibreTranslate-Instanz zeigen, beispielsweise:

```env
LIBRETRANSLATE_URL=http://localhost:5000
```

### 4. Bot starten

```bash
python bot.py
```

---

## Slash-Befehle

Die meisten Funktionen werden über kompakte Bedienfelder gesteuert.

| Befehl | Funktion |
|---|---|
| `/admin status` | Bot-, Modul- und Konfigurationsstatus anzeigen |
| `/admin reload` | Konfiguration neu laden |
| `/settings panel` | Zentrale Einstellungen und Module verwalten |
| `/welcome panel` | Welcome- und Leave-Modul konfigurieren |
| `/rules panel` | Hausordnung, Rolle und Benachrichtigungen verwalten |
| `/rules setup` | Hausordnung im Zielkanal veröffentlichen |
| `/memberlog panel` | Member-Logger und Cleanup verwalten |
| `/memberlog test` | Testeintrag erzeugen |
| `/memberlog cleanup` | Alte Lognachrichten manuell bereinigen |
| `/autoclear panel` | AutoClear vollständig über ein Panel verwalten |
| `/autoclear status` | Aktuelle AutoClear-Konfiguration anzeigen |
| `/autoclear test` | Treffer prüfen, ohne Nachrichten zu löschen |
| `/autoclear now` | AutoClear sofort ausführen |
| `/channel-clear panel` | Sichere Kanalbereinigung öffnen |
| `/audit run` | Server-Audit als TXT, JSON oder kombiniert erstellen |
| `/translate panel` | Übersetzungsanbieter und Kanäle konfigurieren |
| `/arc status` | ARC-Raider-Konfiguration anzeigen |
| `/arc website` | Konfigurierte ARC-Raider-Website anzeigen |

Einzelne Fallback-Befehle können zusätzlich vorhanden sein. Die Panels sind für den normalen Betrieb vorgesehen.

---

## Module

### Admin und Settings

Zeigt den Botstatus an, lädt Konfigurationen neu und verwaltet freigegebene Werte über Discord. Änderungen werden in `data/settings.sqlite` gespeichert.

### Welcome und Leave

Sendet beim Beitritt oder Verlassen zufällige Nachrichten aus konfigurierbaren Pools. Text, Farbe, Zielkanal und Embed-Nutzung sind einstellbar.

### Hausordnung

Veröffentlicht eine Hausordnung mit Bestätigungsbutton. Nach erfolgreicher Bestätigung kann automatisch eine Gastrolle vergeben und ein Administrator benachrichtigt werden.

### Member-Logger

Protokolliert definierte Voice- und Serverereignisse für ausgewählte Rollen. Alte Einträge können zeitgesteuert entfernt werden.

### AutoClear

Prüft einen Zielkanal in einem Intervall oder zu festen Uhrzeiten. Nachrichten werden nur gelöscht, wenn die definierten Löschregeln passen. Schutzbegriffe verhindern versehentliches Entfernen wichtiger Nachrichten.

Vor dem produktiven Einsatz sollte `dry_run` aktiviert und `/autoclear test` ausgeführt werden.

### Channel-Tools

Ermöglicht eine manuelle Bereinigung von Textkanälen. Vor dem Löschen zeigt der Bot eine Vorschau und verlangt eine ausdrückliche Bestätigung.

### Audit

Prüft Rollen, gefährliche globale Rechte, Kanalberechtigungen und selbst definierte Soll-Regeln. Berichte landen im Ordner `reports/`.

### Translator

Übersetzt neue Nachrichten aus konfigurierten Quellkanälen in einen Zielkanal. Texte, Embeds, Links und Fallback-Anbieter lassen sich getrennt konfigurieren.

### ARC-Raider

Bündelt ARCTracker.io-bezogene Status-, Rollen-, Website- und Bereinigungsfunktionen. Das Modul ist in der Beispielkonfiguration deaktiviert.

---

## Übersetzung und LibreTranslate

Die Reihenfolge wird in `config/translator.yaml` festgelegt:

```yaml
translation:
  provider: openai
  fallback_provider: libretranslate
```

Mögliche Werte:

- `openai`
- `deepl`
- `libretranslate`

Beispiel für einen vollständig lokalen Betrieb:

```yaml
translation:
  provider: libretranslate
  fallback_provider: libretranslate
```

Bei Docker Compose ist LibreTranslate unter folgender interner Adresse erreichbar:

```env
LIBRETRANSLATE_URL=http://libretranslate:5000
```

Für OpenAI oder DeepL muss der zugehörige API-Key in `.env` gesetzt werden. API-Keys gehören niemals in YAML-Dateien oder in GitHub-Commits.

---

## Daten und Backups

Folgende Verzeichnisse sind persistent:

```text
data/       SQLite-Einstellungen
logs/       Bot- und Fehlerlogs
reports/    Audit-Berichte
config/     YAML-Grundkonfiguration
```

Ein einfaches Backup:

```bash
tar -czf theken-cowboys-backup.tar.gz .env config data reports
```

Die `.env` enthält Geheimnisse und darf nur sicher gespeichert werden.

---

## Logs und Fehleranalyse

### Bot startet nicht

```bash
docker compose logs --tail=200 theken-cowboys-bot
```

Prüfe besonders:

- Ist `DISCORD_BOT_TOKEN` gesetzt?
- Sind Guild-, Kanal- und Rollen-IDs korrekt?
- Sind die erforderlichen Gateway Intents aktiviert?
- Besitzt der Bot die benötigten Discord-Berechtigungen?

### Slash-Befehle fehlen

- Für Tests eine konkrete `GUILD_ID` verwenden.
- Container neu starten.
- Log auf erfolgreiche Command-Synchronisation prüfen.

### LibreTranslate ist nicht erreichbar

```bash
docker compose logs --tail=200 libretranslate
docker compose restart libretranslate
```

### OpenAI oder DeepL schlägt fehl

- API-Key prüfen.
- Kontingent und Abrechnung beim Anbieter prüfen.
- Fallback auf LibreTranslate aktivieren.

### Nachrichten können nicht gelöscht werden

Der Bot benötigt im Zielkanal **Nachrichten verwalten** und Zugriff auf den Nachrichtenverlauf.

---

## Sicherheit

- `.env` niemals committen oder weitergeben.
- Bot-Tokens und API-Keys sofort ersetzen, sobald sie versehentlich veröffentlicht wurden.
- Echte SQLite-Datenbanken, Logs und Audit-Berichte nicht veröffentlichen.
- Vor AutoClear und Channel-Clear zunächst Dry-Run oder Vorschau verwenden.
- Dem Bot nur die tatsächlich benötigten Discord-Berechtigungen geben.
- Beispielkonfigurationen vor dem Einsatz vollständig prüfen.

Die mitgelieferte `.gitignore` blockiert typische Geheimnisse und Laufzeitdateien. Sie ersetzt jedoch keine manuelle Kontrolle vor einem Commit.

---

## Roadmap

- [x] Modularer Cog-Aufbau
- [x] Zentrale Discord-Panels
- [x] SQLite-basierte Einstellungen
- [x] Docker-Compose-Support
- [x] Lokaler LibreTranslate-Fallback
- [x] Server-Audit als TXT und JSON
- [x] Sichere Kanalbereinigung mit Vorschau
- [ ] Automatisierte Tests
- [ ] GitHub Actions für Syntax- und Qualitätsprüfungen
- [ ] Erweiterte Backup- und Restore-Befehle
- [ ] Mehrsprachige Benutzeroberfläche
- [ ] Vollständige Beispielkonfiguration für einen neutralen Testserver

---

## Lizenz

Dieses Projekt ist unter der **MIT License** lizenziert. Details stehen in [LICENSE](./LICENSE).

---

## Kontakt

Erstellt von **Fw.Schultz**.

- GitHub: [FwSchultz](https://github.com/FwSchultz)
- Homepage: [fwschultz.de](https://fwschultz.de)
- LinkedIn: [Oliver Blume](https://www.linkedin.com/in/oliver-blume)
- Fehler und Funktionswünsche: [GitHub Issues](https://github.com/FwSchultz/Theken-Cowboys-Bot/issues)
