# Translator-Fix

Problem: Der Translator hat Bot-/Webhook-Nachrichten ignoriert. Viele Feed-/Telegram-/News-Posts kommen aber als Bot/Webhook-Nachricht im Quellkanal an.

Fix:
- Eigene Bot-Nachrichten werden weiter ignoriert.
- Bot-/Webhook-Nachrichten im Quellkanal werden standardmäßig übersetzt.
- Zielkanal wird immer ignoriert, um Schleifen zu verhindern.
- Neue Config: `translator.behavior.allow_bot_messages: true`
- Neuer Testbefehl: `/translate test text:<Text>`
- Bessere Logs:
  - `Translator: Nachricht erkannt ...`
  - `Translator: Übersetzung gepostet ...`
  - Fehler mit Stacktrace in `logs/error.log`

Nach dem Einspielen testen:

```bash
docker compose down
docker compose up -d --build
docker logs -f theken-cowboys-bot
```

Discord:

```text
/translate status
/translate test text:Hello this is a test
/translate reload
```

Danach eine echte Nachricht im Quellkanal posten oder vom Feed/Bot posten lassen.
