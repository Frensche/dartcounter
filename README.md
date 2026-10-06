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
python3 dartcounter.py              # Kiosk-Modus (Vollbild, keine Taskleiste)
python3 dartcounter.py --windowed   # normales Fenster, z. B. zum Testen
```

Im **Kiosk-Modus** füllt das Programm den ganzen Bildschirm. Zum Verlassen
(*Spiel → Kiosk-Modus ein/aus*) und zum Beenden ist das Turnierleiter-Passwort nötig.
Systemweite Tastenkürzel des Desktops (z. B. Super-Taste, Strg+Alt+T) kann das
Programm nicht sperren - dafür müsste der Desktop selbst als Kiosk konfiguriert werden.

## Funktionen

- **1–4 Spieler** mit Namenseingabe beim Spielstart
- **Startpunktzahl** 301 / 501 / 701 (Standard: 501)
- **Double-Out** (Standard an, kann auf Straight-Out umgestellt werden)
- **Legs** als "First to X" einstellbar (Standard: 1)
- **F1–F12** als Schnelleingabe für die 12 häufigsten 3-Darts-Scores
  (Standardbelegung: 26, 41, 45, 60, 81, 85, 95, 100, 110, 120, 140, 180),
  jederzeit über *Einstellungen → F1–F12 bearbeiten* änderbar. Die Belegung
  wird dauerhaft in `~/.config/dartcounter/config.json` gespeichert.
- **Handicap** (Vorgabe in Punkten) pro Spieler - im freien Spiel (z. B. 1:1) und im
  Turnier. Die Vorgabe wird relativ zum Spieler mit der kleinsten Vorgabe vom Startwert
  abgezogen: Bei 501 und Vorgaben 0 / 100 startet der eine mit 501, der andere mit 401.
  Bei mehr als zwei Spielern gilt dasselbe für jeden einzelnen.
- **Letzte Würfe** werden bei jedem Spieler angezeigt (neueste zuerst, Busts
  als `BUST (45)` markiert)
- **Vereinslogo** (TSV Feichten) im Kopf des Programms und als Fensterbild;
  die Bilddateien liegen in `assets/` und lassen sich dort austauschen
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

## Turniermodus (mehrere Rechner im Netzwerk)

Ein Rechner ist **Turnierleiter** (hält Turnierbaum bzw. Gruppentabellen und startet einen
kleinen Server), beliebig viele weitere Rechner (Standard: 6) sind **Stationen**. Alle
laufen mit demselben Programm, alle Rechner müssen im selben Netzwerk sein. Es werden nur
Python-Standardbibliotheken benötigt.

### Turnierleiter (passwortgeschützt)

Der Turnierleiter-Bereich (*Turnier → Neues Turnier / Gespeichertes Turnier fortsetzen*)
ist durch ein Passwort gesperrt. Das Passwort ändert man unter
*Einstellungen → Turnierleiter-Passwort ändern...* (gespeichert wird nur ein Hash).
Es ist eine Sperre gegen versehentliche Bedienung, kein Hochsicherheitssystem.

1. *Turnier → Neues Turnier erstellen*
2. Turniername, Spieler (einer pro Zeile, 2-64) und der **Turniermodus**. Handicaps
   trägst du optional direkt in der Spielerliste ein: `Name;Vorgabe`, z. B. `Anna;100`.
   Im Match gilt dann der Unterschied der beiden Vorgaben (siehe oben), die Startwerte
   zeigen Station und Turnierleiter an.
   - **Nur KO-Runde**: Turnierbaum, bei ungerader Spielerzahl mit Freilosen.
   - **Gruppenphase + KO-Runde**: Anzahl Gruppen, wie viele pro Gruppe weiterkommen und
     Legs der Gruppenspiele einstellbar. Die Spieler werden per Schlangenverteilung auf
     die Gruppen verteilt, in jeder Gruppe spielt jeder gegen jeden.
3. Startpunktzahl, Double-Out, Legs (Gruppe / KO-Runde / Finale), Anzahl Stationen, Port.
4. Das Fenster zeigt oben die Adresse (`IP:Port`), mit der sich die Stationen verbinden,
   außerdem Gruppentabellen und Spiele, den Turnierbaum und den Status der Stationen.
5. Matches anklicken (Doppelklick): Ergebnis manuell eintragen/korrigieren, ein
   hängendes Match freigeben oder ein Ergebnis zurücksetzen.
6. Der Stand wird nach jeder Änderung in `~/.config/dartcounter/tournament.json`
   gespeichert und lässt sich nach einem Neustart fortsetzen.

**Gruppenphase im Detail:** Sieg = 2 Punkte. Platzierung nach Punkten, dann Leg-Differenz,
dann gewonnenen Legs, dann direktem Vergleich (bei genau zwei Gleichplatzierten), zuletzt
alphabetisch. Sind alle Gruppenspiele beendet, wird die KO-Runde automatisch ausgelost:
Gruppensieger gegen Zweite anderer Gruppen, die Besten bekommen bei Bedarf Freilose.
Gruppenergebnisse lassen sich nachträglich korrigieren, solange in der KO-Runde noch kein
Spiel begonnen hat (die Auslosung wird dann neu berechnet). Ein Spieler kann nie an zwei
Stationen gleichzeitig spielen.

### Stationen

1. *Turnier → Als Station verbinden...*: Der Turnierleiter wird **automatisch im Netzwerk
   gesucht** (IP und Port werden eingetragen, das Programm merkt sich außerdem die letzte
   Verbindung). Es genügt, die Nummer dieser Station zu prüfen und *Verbinden* (Enter) zu
   drücken. Wird nichts gefunden, kann die IP wie bisher von Hand eingegeben werden.
2. Im Station-Fenster erscheinen alle spielbereiten Matches (Gruppen- und KO-Spiele).
   Eins auswählen und *Ausgewähltes Match hier spielen* (oder Doppelklick) - es ist dann
   für alle anderen Stationen gesperrt.
3. Das Match wird mit Namen, Startpunktzahl, Double-Out und Legs aus dem Turnier im
   normalen Zähler gespielt. Ist es zu Ende, mit *Ergebnis senden* übermitteln (vorher ist
   noch Undo möglich) - Tabelle bzw. Turnierbaum werden automatisch aktualisiert.
   *Match abbrechen* gibt das Match wieder frei.

Hinweis: Die Verbindung ist unverschlüsselt und ohne Passwort - gedacht für das lokale
Netzwerk in der Halle. Eine eventuelle Firewall muss am Turnierleiter-Rechner den Port
8765 (TCP, Turnierdaten) und 8766 (UDP, automatische Suche) durchlassen. Die Suche nutzt
UDP-Broadcast und scannt zusätzlich das lokale Netz (/24) nach Port 8765; in WLANs mit
Geräte-Isolation findet sie nichts - dann bitte die IP von Hand eintragen.
