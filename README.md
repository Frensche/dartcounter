# Dartcounter

Ein einfacher Dartcounter für Linux (Python 3 + Tkinter, keine externen
Abhängigkeiten).

## Installation

Tkinter wird auf deinem System noch benötigt:

```bash
sudo apt install python3-tk
```

## Start

```bash
python3 dartcounter.py
```

oder, da die Datei ausführbar ist:

```bash
./dartcounter.py
```

## Funktionen

- **1–4 Spieler** mit Namenseingabe beim Spielstart
- **Startpunktzahl** 301 / 501 / 701 (Standard: 501)
- **Double-Out** (Standard an, kann auf Straight-Out umgestellt werden)
- **Legs** als "First to X" einstellbar (Standard: 1)
- **F1–F12** als Schnelleingabe für die 12 häufigsten 3-Darts-Scores
  (Standardbelegung: 26, 41, 45, 60, 81, 85, 95, 100, 110, 120, 140, 180),
  jederzeit über *Einstellungen → F1–F12 bearbeiten* änderbar. Die Belegung
  wird dauerhaft in `~/.config/dartcounter/config.json` gespeichert.
- **Manuelle Eingabe** eines beliebigen Turn-Scores (0–180) im Textfeld,
  Bestätigung mit Enter
- **Checkout-Vorschläge**: sobald ein Spieler am Zug ist und sein Rest mit
  double-out schaffbar ist, wird automatisch eine mögliche Wurf-Route
  angezeigt (z. B. `T20 → T20 → Bull` bei 170). Die Route wird live berechnet
  (kein starres Nachschlagewerk) und bevorzugt dabei die wenigsten Darts
  sowie die gängigen Zielfelder T20 / 20 / D20 / Bull — bei sehr krummen
  Zwischenwerten kann die vorgeschlagene Route daher gelegentlich von der
  einen "klassischen" Lehrbuch-Route abweichen, ist aber immer ein
  gültiger Double-Out-Checkout.
- **Bust-Erkennung**: Punktzahl unter 0, oder bei Double-Out genau 1 Rest,
  zählt als Bust — der Score bleibt unverändert, der nächste Spieler ist dran
- **Undo** (Button oder Strg+Z) macht die letzte Eingabe rückgängig
- **3-Darts-Average** je Spieler wird live mitgeführt

## Bedienung

- `F1`–`F12`: trägt den hinterlegten Score für den aktuellen Spieler ein und
  wechselt automatisch zum nächsten Spieler
- Zahl eintippen + `Enter`: trägt einen individuellen Turn-Score ein
- `Strg+Z`: letzte Eingabe rückgängig machen
- Menü *Spiel*: neues Spiel, Leg neu starten, Beenden
- Menü *Einstellungen*: F1–F12 bearbeiten

## Turniermodus (KO-System, mehrere Rechner im Netzwerk)

Ein Rechner ist **Turnierleiter** (hält den Turnierbaum und startet einen kleinen
Server), beliebig viele weitere Rechner (Standard: 6) sind **Stationen**. Alle
laufen mit demselben Programm (`python3 dartcounter.py`), alle Rechner müssen im
selben Netzwerk sein. Es werden nur Python-Standardbibliotheken benötigt.

**Turnierleiter:**

1. Menü *Turnier → Neues Turnier erstellen (Turnierleiter)...*
2. Turniername, Spieler (einer pro Zeile, 2-64), Startpunktzahl, Double-Out,
   Legs zum Sieg (Runden / Finale), Anzahl Stationen, Port. Die Spieler werden
   zufällig ausgelost (abschaltbar = Reihenfolge ist die Setzliste). Bei einer
   Spielerzahl, die keine Zweierpotenz ist, gibt es automatisch Freilose.
3. Im Turnierleiter-Fenster siehst du den Turnierbaum, den Status der Stationen
   und oben die Adresse (`IP:Port`), mit der sich die Stationen verbinden.
4. Matches anklicken (Doppelklick): Ergebnis manuell eintragen/korrigieren, ein
   hängendes Match an einer Station freigeben oder ein Ergebnis zurücksetzen
   (nur solange das Folge-Match noch nicht läuft).
5. Der Stand wird nach jeder Änderung in `~/.config/dartcounter/tournament.json`
   gespeichert. Über *Turnier → Gespeichertes Turnier fortsetzen* geht es nach
   einem Neustart weiter.

**Stationen:**

1. Menü *Turnier → Als Station verbinden...*: IP des Turnierleiters, Port und
   die Nummer dieser Station (1-6) eingeben.
2. Im Station-Fenster erscheinen alle spielbereiten Matches. Eins auswählen und
   *Ausgewähltes Match hier spielen* (oder Doppelklick) - es ist dann für alle
   anderen Stationen gesperrt.
3. Das Match wird mit Namen, Startpunktzahl, Double-Out und Legs aus dem Turnier
   im normalen Zähler gespielt. Ist es zu Ende, mit *Ergebnis senden* an den
   Turnierleiter übermitteln (vorher ist noch Undo möglich) - der Sieger wird
   automatisch in den Turnierbaum eingetragen und die nächste Runde freigeschaltet.
   *Match abbrechen* gibt das Match wieder frei.

Hinweis: Die Verbindung ist unverschlüsselt und ohne Passwort - gedacht für das
lokale Netzwerk in der Halle/zu Hause. Eine eventuelle Firewall muss den Port
(Standard 8765) am Turnierleiter-Rechner durchlassen.
