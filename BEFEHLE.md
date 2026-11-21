# Befehls-Übersicht Dartcounter

Repository: `git@github.com:Frensche/dartcounter.git`
(Web: https://github.com/Frensche/dartcounter)

## 1. Einmalig vorbereiten (neuer Rechner)

```bash
# Debian / Ubuntu / Mint / Raspberry Pi OS
sudo apt update && sudo apt install python3 python3-tk git
```

Prüfen, ob alles da ist:

```bash
python3 --version
python3 -c "import tkinter; print('Tk OK')"
git --version
```

## 2. Herunterladen (erstes Mal)

```bash
cd ~
git clone https://github.com/Frensche/dartcounter.git
cd dartcounter
```

Ist das Repo privat oder soll per SSH geladen werden:

```bash
git clone git@github.com:Frensche/dartcounter.git
```

## 3. Starten

```bash
cd ~/dartcounter
python3 dartcounter.py              # Kiosk-Modus (Vollbild)
python3 dartcounter.py --windowed   # normales Fenster (zum Testen)
```

## 4. Aktualisieren (neuester Stand von GitHub)

```bash
cd ~/dartcounter
git pull
```

Gibt `git pull` eine Meldung über lokal geänderte Dateien aus, dann hast du dort etwas
verändert. Eigene Änderungen verwerfen und exakt den GitHub-Stand herstellen:

```bash
cd ~/dartcounter
git fetch origin
git reset --hard origin/main
```

Alternativ ohne Git: ZIP von GitHub laden (grüner Button *Code → Download ZIP*) und den
alten Ordner ersetzen.

## 5. Änderungen hochladen (vom Entwicklungs-Rechner)

```bash
cd ~/dartcounter
git status                      # was hat sich geändert?
git add -A                      # alles vormerken
git commit -m "Kurze Beschreibung der Änderung"
git push                        # hochladen (fragt die SSH-Passphrase ab)
```

Beim allerersten Push eines Branches:

```bash
git push -u origin main
```

## 6. Nützliche Zusatzbefehle

```bash
git log --oneline | head        # letzte Änderungen anzeigen
git diff                        # noch nicht committete Änderungen ansehen
git remote -v                   # wohin wird hochgeladen?
git remote set-url origin git@github.com:Frensche/dartcounter.git   # Adresse ändern
```

SSH-Verbindung zu GitHub testen:

```bash
ssh -T git@github.com           # Antwort: "Hi Frensche! You've successfully authenticated ..."
```

Eigenen öffentlichen SSH-Schlüssel anzeigen (der muss bei GitHub unter
*Settings → SSH and GPG keys* als **Authentication Key** eingetragen sein):

```bash
cat ~/.ssh/id_ed25519.pub
```

## 7. Programmdaten

| Was | Wo |
|---|---|
| F1–F12, Einstellungen, Passwort-Hash | `~/.config/dartcounter/config.json` |
| Gespeichertes Turnier | `~/.config/dartcounter/tournament.json` |

Diese Dateien bleiben bei `git pull` unverändert. Zurücksetzen (alles auf Standard):

```bash
rm -r ~/.config/dartcounter
```

## 8. Turnier im Netzwerk - Ports für die Firewall

Am Turnierleiter-Rechner müssen erreichbar sein: **8765/TCP** (Turnierdaten) und
**8766/UDP** (automatische Suche). Bei `ufw`:

```bash
sudo ufw allow 8765/tcp
sudo ufw allow 8766/udp
```

## 9. Im Programm

| Taste | Wirkung |
|---|---|
| `Esc` | Hauptmenü (Pfeiltasten + Enter) |
| `F1`–`F8` | Schnell-Scores: 0, 26, 41, 45, 60, 81, 85, 100 |
| `F9` oder `R` | Rest eingeben (verbleibende Punktzahl statt geworfener Punkte) |
| `F10` / `F11` / `F12` oder `Strg+1` / `2` / `3` | Finish mit 1 / 2 / 3 Darts |
| `Strg+Z` | Letzte Eingabe rückgängig |
| `F9` / `R`, dann Zahl | Rest: Zahl wird ohne Enter übernommen |
| `Strg+G` | Minispiele (Random Checkout, 121, Cricket, Around the Clock, Shanghai, Bob's 27, Highscore) |
| `Strg+N` / `Strg+W` / `Strg+R` | Neues Spiel / Wer beginnt? / Leg neu |
| `Strg+Q` | Beenden (im Kiosk-Modus mit Passwort) |

## 10. Tests (ohne Bildschirm)

```bash
cd ~/dartcounter
python3 tests/test_engine.py
python3 tests/test_minigames.py
```
