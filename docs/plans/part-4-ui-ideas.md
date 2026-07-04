# Part 4 — UI-Ideen (Ideation)

**Status: Ideation only — nichts entschieden.**
Datum: 2026-07-04.
Feeds: Part-4-Kickoff + HTMX/Datastar-Prototyp.

Dies ist ein Ideenkatalog, keine Spezifikation. Vier Ideation-Läufe (Archivar-Workflow,
Member-Discovery, archivische Konventionen, Hypermedia-Ökonomie) sind hier pro **Screen**
zusammengeführt und entdoppelt. Der Projektinhaber reagiert darauf beim Kickoff.

Kosten-Tags = Hypermedia-Bauaufwand: **billig** / **mittel** / **teuer**.
Jede Idee funktioniert im No-JS-Baseline (plain hypermedia). Alpine/JS nur dort erwähnt,
wo es echten Nutzen bringt. HTMX-vs-Datastar-Unterschiede sind markiert, wo sie zählen.

Fixe Grundregeln (nicht mehr verhandelt): server-rendered Django; HTMX **oder** Datastar
(Entscheidung offen — Ideen müssen in beiden laufen); Alpine nur als Sprinkle; kein SPA,
kein Build; Sichtbarkeit läuft immer durch die **eine** `effective_audience`-Funktion;
Medien nur über autorisierte Views; Feld-Floors (`physical_location` + Custom nur Archivar).

Screens: Browse/Suche · Detail + Medien · Katalogisierung · Sammlungen · Publish-Flow.

---

## 1. Browse / Suche (Member-Discovery)

Prägend für alle Ideen: der reale Korpus ist **textlastig, thumbnail-arm, datums-unscharf**.
Nur ~57 % der Datensätze haben eine Datei, ~450 haben gar kein Datum, ~300 sind unscharf
(`Herbst 1997`, `50er Jahre`, `vor 1945`). Ein hübsches Foto-Raster würde den Bestand
falsch darstellen. Ehrlichkeit gegenüber den Daten ist der rote Faden.

### 1.1 URL-as-State-Facettensuche — das Rückgrat, zuerst bauen
Der ganze Such-Screen ist **ein Formular**, dessen kompletter Zustand (Volltext, Sammlungs-Knoten,
Medienart, Dokumenttyp, Schlagwörter, Jahrzehnt/Datumsbereich, `ref_code`-Sortierung, Seite)
in der Query-String steht. Jede Facette ist ein Link oder Input, der eine neue URL setzt und
nur den Ergebnisbereich + Facettenzähler tauscht. Zähler kommen aus der bereits scoped
Index-Query — nur über die für diesen Viewer sichtbare Menge.
*Warum: eine geteilte Such-URL löst in 10 Jahren ohne JS noch auf; natürliche Form der
audience-scoped `search()`.* **Kosten: billig.**

### 1.2 Facetten als entfernbare Chips + Suchsatz
Aktive Filter erscheinen als abwählbare Chips über den Ergebnissen; verfügbare Facetten in
einer einklappbaren linken Leiste mit Live-Zählern. Chip-✕ entfernt einen Schritt. Optional
als Prosa: ein **Suchsatz**, der den aktuellen Filter in Klartext zurückliest
(*„Pfadfinder · Bestand: Gau Franken · Medienart: Schrifttum · 1980–1989"*). URL spiegelt
immer die Chips — jeder Filterzustand ist teilbar.
*Warum: der aktuelle Filter ist auf einen Blick lesbar und Schritt für Schritt widerrufbar;
teilbare URL = kleines Geschenk zwischen Mitgliedern.* **Kosten: billig–mittel.**

### 1.3 Jahrzehnt-Leiste mit Unschärfe-Ehrlichkeitsband
Statt eines Zwei-Daumen-Sliders (der bei `Herbst 1997` und `vor 1945` lügt): eine
horizontale Jahrzehnt-Leiste (1930er … 2020er), jede mit Zähler und kleinem Histogramm-Balken,
damit man sieht, wo der Bestand dicht ist. Dazu zwei ehrliche Schalter:
**„Ungefähre Daten einbeziehen"** (Überlappung vs. Enthaltensein auf `date_lo`/`date_hi`) und
**„Ohne Datum (450)"** als erstklassiger, gezählter Filter.
*Warum: die Daten sind von Natur aus unscharf; ein Slider täuscht Präzision vor, die der
Bestand nicht hat.* **Kosten: mittel** (UI billig; die Kosten liegen in der Query-Logik).

### 1.4 Adaptive Ergebnisdarstellung — Textkarte ↔ Raster
Standard ist eine kompakte **Kartenliste** (Thumbnail *oder* Medienart-Glyph 📄🎞🔊, Titel,
`ref_code` rechts, Sammlung/Typ/Datum, Schlagwörter). Umschalter **Liste / Raster**; das
Raster wird schön, sobald foto-lastige Ergebnisse dominieren (z. B. nach Filter Medienart=Foto).
Datensätze ohne Datei zeigen einen Glyph, nie eine kaputte Bildbox.
*Warum: Darstellung passt zu dem, was wirklich da ist — Text für die vielen, Raster für die
foto-reichen Teilmengen; kein Platzhalter-Friedhof.* **Kosten: mittel.**

### 1.5 Zero-Hit-Rettung — die nächste Tür anbieten
Kein Treffer ist nie eine Sackgasse. Warme Meldung + **nächstgelegene Nachbarn** aus dem, was
getippt wurde: *„Ohne ‚1930er' → 94 Treffer", „‚Gau Franken' allein → 347"*, ähnliche
Schlagwörter, Sprung in die Sammlung. Jede Empfehlung ist ein Ein-Klick-Link, der den
restriktivsten Chip fallen lässt. **Leak-sicher:** existieren Treffer nur oberhalb der
Viewer-Stufe, bleibt die Meldung ehrlich (*„keine für dich sichtbaren Treffer"*) und verrät
nie, was gesperrt ist.
*Warum: Freiwilligen-Publikum vertippt und überfiltert sich; die nächste Tür hält den
gelegentlichen Besucher.* **Kosten: mittel.**

### 1.6 Serendipität — Zufallsfund + „Mehr aus …"
Zwei billige Stöber-Affordanzen: **Zufallsfund 🎲** tauscht einen zufälligen, sichtbaren,
veröffentlichten Artikel ein („Nochmal 🎲"); **„Mehr aus den 1970ern / aus Gau Franken"** als
Geschwister-Streifen auf Detail- und Ergebnisseiten. Beide **zwingend durch die
effective-audience-Funktion** — nie in etwas über der eigenen Stufe hineinstolpern.
*Warum: Mitglieder stöbern gelegentlich statt gezielt zu suchen; lädt den glücklichen Zufall
ein, den der Auftrag will.* **Kosten: billig.**

### 1.7 Findbuch-Einstiege + Tektonik-Baum als Browse-Rückgrat
Für stöbernde Mitglieder ist der Sammlungsbaum die Achse — als klassische **Tektonik**
(Bestand → Serie → Akte) mit Bestandzählern, Breadcrumb und lazy-expandierten Kindknoten;
spiegelt die realen `location`-Pfade (`Gruppen des DPB / Gau Franken / Zeitschrift / …`).
Ergänzt durch kuratierte **Einstiege** auf der Startseite — handbeschriftete Kacheln
(*„Fotos der 1960er", „Bundeslager", „Liederhefte"*), die nur gespeicherte Facetten-URLs sind,
**keine** neue Entität (nicht das deferred Album).
*Warum: Mitglieder denken in der eigenen Gau-Hierarchie; Einstiege sind Türen statt leerem
Suchfeld.* **Kosten: billig–mittel.**

**Divergenz für den Prototyp (Suchbox):** debounced Search-as-you-type über `q` **nur die
Ergebnisse tauschen**, Facettenzähler erst bei Submit/Facetten-Klick neu rechnen (sonst
schmilzt die teure Aggregat-Query auf dem Hot Path). HTMX: `hx-trigger="keyup changed
delay:400ms"` (deklarativ). Datastar: Signal-Binding + `data-on-input__debounce.400ms`.
Beide können es — guter, risikoarmer Ort, um die zwei Denkmodelle zu fühlen.

---

## 2. Detail + Medien-Anzeige

### 2.1 Zettel-Ansicht — Detail als Katalogkarte
Die Detailseite öffnet als **Katalogkarte** mit fester archivischer Feldreihenfolge
(Signatur → Titel → Urheber → Datierung → Ort → Dokumenttyp → Standort → Bestand), die
Signatur groß als „Rücken" der Karte. Leere Felder klappen ein. **Feld-Floors durch Abwesenheit:**
ein Mitglied sieht die Standort-/Custom-Zeilen schlicht *nicht* — kein ausgegrautes
„🔒 versteckt", das Existenz verrät. Für Archivare wächst dieselbe Karte einen abgesetzten
Bereich *„Nur für Archivar:innen"*.
*Warum: die Katalogkarte ist das native Detail-Idiom des Archivs; feste Feldreihenfolge lässt
hundert Datensätze scannen, ohne Labels neu zu lesen.* **Kosten: billig.**

### 2.2 Herkunft & Vermerke — Provenienz-Panel (Archivar-only)
Ein eigenes **Herkunft / Vermerke**-Panel sammelt, was das Altsystem verstreut hatte
(`source`, `owner`, `notes`, `amount`) — jetzt der Custom-Bag (ADR 0009), seeded mit den
erkennbaren deutschen Schlüsseln (*Quelle, Herkunft Original, Notiz, Anzahl Objekte, Querverweis*).
Sichtbare *„Nur für Archivar:innen"*-Bänderung macht die Nie-für-Mitglieder-Regel strukturell.
Ein Hinweis — *„Um ein Feld allen zu zeigen, muss es ein festes Feld werden"* — verortet die
ADR-0009-Escape-Hatch-Regel dort, wo der Archivar sie sucht.
*Warum: Provenienz und Randvermerke sind das Handwerk des Archivars und gehören zusammen in
ein klar restriktives Panel.* **Kosten: billig.**

### 2.3 Medien: native Player + Lightbox, die zur Seite degradiert
Die Galerie ist eine **geordnete** Liste von N Medien mit Bildunterschriften.
- **Bilder:** Thumbnail-Reihe; Klick öffnet eine Lightbox (fragment-getauschtes Panel mit
  vor/zurück, Caption, Download). **Flag:** die fokus-gefangene Tastatur-Lightbox ist
  Alpine-Level-UI — der Kernpfad muss degradieren: jedes Thumbnail ist auch ein echter Link
  auf eine volle Medienseite. Der degradierte Link-Pfad ist framework-identisch.
- **Video/Audio:** natives `<video>`/`<audio>` inline, ein Element pro Galerie-Slot — kein
  Transcoding nötig (§8).
- **PDF:** natives Browser-Embed für die erste Datei + prominenter „Als PDF öffnen"-Link; die
  gerenderte Erste-Seite-Ableitung (§8) steht als Vorschau in der Liste. Kein JS-PDF-Viewer.
*Warum: gemischte Medien mit kleinem Team → auf den Browser stützen; die Lightbox ist der eine
Sprinkle, der sich lohnt, alles andere ist nativ und läuft auch 2036.* **Kosten: mittel**
(nur die Lightbox; Player/PDF quasi gratis).

### 2.4 Bild-Performance: srcset + natives lazy-load, null JS
Templates emittieren `srcset`/`sizes` + `loading="lazy"` + feste `width`/`height` (kein JS-Lazy-Loader,
kein Layout-Shift). **Kritisch:** jeder Thumbnail-Byte geht über die autorisierte `can_view`-View
(X-Accel-Redirect) — `src`/`srcset` zeigen auf `/media/…`-App-URLs, nie auf einen öffentlichen Pfad.
*Warum: ergebnisdichte Seiten bleiben leicht auf dem Laptop eines Freiwilligen; reines
Plattform-HTML, keine Library, die verrottet.* **Kosten: billig** (Server-/Worker-seitig separat).

---

## 3. Katalogisierung (Archivar-Workflow)

Maßstab: ein Freiwilliger sitzt sonntags mit einem Schuhkarton voll 80 Fotos. Jede Idee wird
an Sekunden/Tastenanschlägen pro Artikel gemessen — und daran, ob je Arbeit verloren geht.

### 3.1 „Stapel anlegen" — erst Batch-Upload, dann als Queue annotieren
Der primäre Einstieg für einen Schuhkarton ist **keine** Form, sondern eine Dropzone. 80 Scans
reinziehen; jeder wird sofort ein Entwurf (ULID vergeben, Medien angehängt, Thumbnail in die
Queue). Der Archivar landet in einer **Annotier-Queue**: Filmstreifen links, eine aktive Form
rechts, Zähler *„Foto 12 von 80 — 68 noch offen"*. Upload ist I/O-gebunden und langsam;
entkoppelt vom Denken rendern die Thumbnails im Worker weiter.
*Warum: die echte Arbeitseinheit ist ein physischer Stapel (die Migration zeigt 1–12 Objekte je
Datensatz, ein Karton = viele Datensätze).* **Kosten: mittel.**

### 3.2 „Wie voriges" — den letzten Artikel als lebende Vorlage duplizieren
Persistenter Button, der einen frischen Entwurf aus dem zuletzt von *diesem* Archivar
gespeicherten Artikel vorbefüllt — nur die batch-wiederholten Felder (`collection`,
`document_type`, `media_type`, `physical_location`, `creator`, `subject_place`, Datums-Jahrzehnt,
Custom-Keys). Titel, `ref_code`, Medien bleiben leer. „geerbt"-Chip pro übernommenem Feld;
Klick leert es.
*Warum: ein Schuhkarton ist homogen — 80 Fotos aus *einem* Gau, *einem* Ort, *einer* Ära; den
Standort-Pfad 80× tippen ist der Durchsatz-Killer.* **Kosten: billig.**

### 3.3 `ref_code`-Auto-Weiterzählen mit Live-Dublettenwarnung
Nach `Foto-1955/007` befüllt das nächste `ref_code`-Feld `Foto-1955/008` (numerischer Schwanz
inkrementiert, Nullpadding/Prefix erhalten), bleibt editierbar. Beim Tippen erscheint nach
Debounce ein Inline-Hinweis: *„⚠ schon vergeben: ‚Zeltlager Spessart' — trotzdem verwenden?"*.
**Blockt nie** (soft-unique: gewarnt, nicht blockiert) — die Warnung ist ein Fragment im `<span>`,
Speichern läuft trotzdem.
*Warum: der `ref_code` wird in Sequenz aufs Objekt geschrieben; Auto-Zählen passt zur Handbewegung,
die Soft-Warnung fängt den Fettfinger ohne Fail-Closed-Reibung.* **Kosten: billig.**

### 3.4 Datierung-Werkstatt — EDTF-Eingabe, die Findbuch-Deutsch spricht
Ein Textfeld `Datierung`. Darunter ein ruhiges Live-Echo mit geparster EDTF **und** deutschem
Klartext-Rücklesen (debounced):
- `Herbst 1962` → `1962-23` · „Herbst 1962" ✓ (Zeitspanne Sept–Nov)
- `um 1974` → `1974~` · „ca. 1974" ✓
- `50er Jahre` → `195X` · „1950er" ✓
- `nonen zit 1958` → ⚠ nicht erkannt — als Notiz/Freitext behalten?
Nimmt alle deutschen Unschärfeformen der Migration (`Monat YYYY`, Saisons, `Weihnachten`,
`Pfingsten`, `nach/vor`, `ca.`, Bereiche `1934–1962`, Tippfehler). Was EDTF nicht halten kann
(`Pfingsten`, `Ostern`), landet als Originalphrase in `custom["Datum_Original"]` — nichts geht verloren.
**Der Server-Parser (Part-3-Primitive) ist der Richter, nie ein JS-Date-Parser** — kein Drift
zwischen Eingabe, Speicherung und Suche.
*Warum: das ist DIE Signatur-Interaktion des Jobs (~300 Zeilen brauchen Datums-Urteil), das
Vokabular ist zutiefst deutsch; das Rücklesen in eigenen Worten schafft Vertrauen.*
**Kosten: mittel** (Parser existiert; UI ist dünnes Fragment-Echo). **Kein JS-Datepicker** —
EDTFs Saison/Intervall/Unschärfe hat keine sinnvolle Picker-UI.

### 3.5 Custom-Key-Recall — das Archiv lehrt sich sein eigenes Vokabular
Beim Custom-Feld autocompletet das **Key**-Feld aus zuvor genutzten Keys (frequenz-sortiert:
`Quelle`, `Notiz`, `Herkunft_Original`, `Anzahl_Objekte`, `Querverweis`); Werte stabiler Keys
(`Quelle` → `bolko`, `Burgarchiv`) schlagen ebenfalls vor. Hält die Folksonomie konvergent
gegen Drift (`Quelle` vs. `quelle` vs. `Herkunft`) und zeigt nebenbei, welcher Key reif für
Beförderung zu einem echten Feld ist (ADR 0009). Gleiche Autocomplete-Plumbing wie
Medienart/Dokumenttyp/Schlagwort.
*Warum: der freie Escape-Hatch (ADR 0009) driftet sonst und blockiert spätere Promotion.*
**Kosten: billig–mittel** (Archivar-scoped Distinct-Keys-Query — sicher, da alles Archivar-only).

### 3.6 „Meine Entwürfe" + Autosave-pro-Feld — nie Arbeit verlieren
Eine stehende Landefläche pro Archivar: **Meine Entwürfe**, nach Stapel und Alter gruppiert,
mit Vollständigkeits-Punkt (hat Medien / Titel / Datum / Sammlung) und „hier weiter". Dort lebt
ein halb-annotierter Schuhkarton zwischen zwei Sonntagen. Gepaart mit **Autosave-on-blur**:
jeder Feld-Blur PATCHt den Entwurf server-seitig; keine „Speichern"-Klippe, Draft ist die
Quelle der Wahrheit (echter Lifecycle-Zustand, kein ungespeicherter Puffer).
*Warum: Freiwillige arbeiten in unterbrochenen Sessions über Wochen; „wo war ich" ist ein echter
Kosten.* **Kosten: mittel.**

### 3.7 „Nur Signatur & Foto" — die Zwei-Feld-Schnellspur
Expliziter Minimal-Erfassungsmodus: Form kollabiert auf Medien + `ref_code` (+ geerbte Sammlung
aus 3.2). Speichern erzeugt einen bewusst unvollständigen Entwurf mit Filter **„nur Rohaufnahmen"**,
den eine spätere Session — oder ein anderer Freiwilliger — beschreibt.
*Warum: Digitalisieren und Beschreiben sind verschiedene Aufgaben, oft verschiedene Personen; so
kann ein Sonntag „alle 80 gescannt und nummeriert" sein, das Objekt ist sicher im System.*
**Kosten: billig.**

### 3.8 Vokabular-Comboboxen (Autocomplete-Arbeitspferd)
`media_type`, `document_type`, `tags`, `physical_location`, `subject_place`, `creator` sind alle
„Freitext + Autocomplete, seeded, offen für Neues". **Eine** wiederverwendbare server-getriebene
Combobox: tippen → debounced GET → `<ul>` von Treffern → Klick füllt; neuer Wert bei Blur bleibt
(offenes Vokabular, kein „Neu hinzufügen"-Zeremoniell). `physical_location`-Pfadsegmente
(`Magazin / Regal / …`) genauso.
*Warum: verhindert Vokabulardrift (`Schrifttum` vs. `Schriftgut`) ohne eine Liste zu erzwingen —
genau die „keine verwalteten Entitäten"-Regel.* **Kosten: billig** (amortisiert über 6 Felder).
*Alpine gerechtfertigt: Tastatur-Navigation der Dropdown-Liste (↑/↓/Enter/Esc); No-JS-Baseline
ist ein reines Textfeld ggf. mit nativem `<datalist>`.*

### 3.9 Tastatur-Spine + Inline-Validierung als Fragmente
Dokumentierte, entdeckbare Tastenkarte für die Katalog-Schleife: `Enter` → nächstes Feld;
`Ctrl+Enter` → Speichern & weiter; `Ctrl+D` → Wie voriges; `Alt+↓/↑` → nächstes Thumbnail;
`?` → Cheat-Sheet-Overlay mit deutschen Labels. **Additiv über** eine voll maus-bedienbare Form,
nie der einzige Pfad. Validierung ist pro Feld und beratend — als Fragment neben dem Feld beim
Blur, nie ein Full-Page-Repost, der Scroll/Nachbarfelder verliert. Die Form speichert immer als
Entwurf; Validierung *härtet* erst am Publish-Gate.
*Warum: 80 × ein Dutzend Felder ist ein Dateneingabe-Marathon; wer 40 Felder an ein schlechtes
Datum verliert, kommt nächsten Sonntag nicht wieder.* **Kosten: billig.**

### 3.10 Medien-Upload — der eine Ort für echtes JS-Budget
Uploads sind das Härteste: große Video/Audio/Scans, Freiwillige auf Heim-Anschlüssen.
- **No-JS-Baseline:** `<input type=file multiple>` + Submit. Funktioniert, blockiert die Seite,
  keine Fortschrittsanzeige. Akzeptabler Boden.
- **Enhanced:** Fortschrittsbalken pro Datei (HTMX: `hx-encoding` + `htmx:xhr:progress`).
- **Resumable/chunked:** echte JS-Komponente + Chunk-Assembly-Endpoint (heute ist `putLarge`
  eine Operation) — wahrscheinlich v1-deferred.
*Warum: ein 300-MB-Tonband über DSL braucht ein Lebenszeichen; stiller 4-Minuten-Hang liest sich
als „kaputt".* **Kosten: mittel→teuer** (Balken mittel, resumable teuer, flaggen).
**Divergenz — echt und entscheidend:** HTMX' XHR-Progress ist ausgetreten; Datastar (fetch/SSE)
macht Multipart-Progress weniger idiomatisch. **Der Upload-Screen ist der beste Stresstest für den
Prototyp** — der „harte" Gegenpart zum „leichten" Such-Screen.

---

## 4. Sammlungen (Verwaltung + Move)

### 4.1 Übernahme-/Umbettungs-Vorschau — Move als Sichtbarkeits-Gate
Ein Move ändert Sichtbarkeit (Roadmap Part 4). Ablauf: neuen Eltern-Knoten wählen → Server
rendert eine **Vorher/Nachher-Sichtbarkeits-Vorschau** über den betroffenen Teilbaum → der
Commit-Button lebt *in diesem zurückgegebenen Fragment*. Keine optimistische UI.
Framing als **Umbettung** (das archivische Wort fürs Umlagern) mit explizitem „geerbt von: …":
```
Umbettung: „Blätter St. Georg, Heft 18" (BA 242)
  von   Orden St. Georg / Zeitschrift
  nach  Öffentliche Schriften
  vorher   Mitglieder   (geerbt von: Orden St. Georg)
  nachher  Öffentlich ⚠ WEITER (geerbt von: Öffentliche Schriften)
  ⚠ 44 weitere Artikel dieser Serie werden ebenfalls öffentlich.
  [ Übernehmen ]  [ Abbrechen ]
```
**⚠ WEITER** feuert nur, wenn die Audience sich *weitet*, und zählt die Kollateral-Artikel im
Teilbaum. Nutzt dieselbe `effective_audience`-Funktion und dasselbe Widget wie der Publish-Flow.
*Warum: Umbettung in einem echten Archiv ändert, wer Zugang hat; die Vorschau *ist* das
Sicherheits-Gate.* **Kosten: mittel** (Kosten im Teilbaum-Walk, nicht in der UI; Reindex-Gate
ist Server-Sache).

### 4.2 Findbuch-Tektonik auch als Verwaltungs-Baum
Derselbe Bestand → Serie → Akte-Baum aus 1.7 dient dem Archivar zum Verwalten: lazy-expandiert,
mit audience-scoped Zählern, und **„ohne Bestand (196)"** als echter, bearbeitbarer Eimer für die
unzugeordneten Migrationszeilen — statt einer Datenqualitäts-Fußnote. Der Baum gibt der
Cascade-Audience einen räumlichen Ort: man *sieht*, wo ein Artikel in der Vererbungskette sitzt.
*Warum: Archivare denken in Bestand → Serie → Akte; ein Baum-mit-Zählern ist die Struktur des
gedruckten Findbuchs.* **Kosten: mittel.**

**BAN:** kein Drag-and-Drop-Baum-Reordering für den Move. Teuer in Hypermedia, brüchig ohne JS,
schlecht entdeckbar für ältere Freiwillige — und es *versteckt* die Expositions-Konsequenz, die
der Flow gerade sichtbar machen soll. `<select>` der Zielknoten + explizite Bestätigung ist
billiger *und* sicherer.

---

## 5. Publish-Flow (Entwurf → Veröffentlicht)

### 5.1 Der Publish-Moment — Sichtbarkeits-Vorschau als „Wer sieht das?"-Spiegel
Publizieren öffnet eine Vorschau, die die echte Frage des Archivars in Klartext beantwortet —
**nicht** über Rung-Namen, sondern über **menschen-förmige Ergebnisse**:
```
Veröffentlichen: 68 Fotos aus „Gau Franken"
Wer sieht das danach?
  ✓ Alle Mitglieder            (geerbt von Sammlung „Gruppen des DPB")
  ✓ Gruppe „Bundesführung"
  ✗ Öffentlich                 (nicht freigegeben)
⚠ 3 Artikel wären weiter sichtbar als ihre Sammlung:
    „Foto-1955/012" → nur Archivar, weil Standort fehlt   [ ansehen ]
[ Abbrechen ]        [ 65 veröffentlichen ]  (3 zurückgehalten)
```
**Server-berechnet, nie client-simuliert:** die Vorschau ruft dieselbe `effective_audience`-Funktion,
die auch durchsetzt — Vorschau und Durchsetzung sind derselbe Code-Pfad, die Vorschau kann nicht
lügen. Batch-Publish hält die Leaker und die den Feld-Floor verfehlenden zurück, publiziert den
Rest, sagt welche und warum — ein schlechter Datensatz blockiert nie die anderen 79.
*Warum: der höchststakige Moment eines sichtbarkeits-kontrollierten Archivs; Menschen
(„Mitglieder", benannte Gruppen) statt der Public⊃Members⊃Groups-Leiter passt zur Wärme-Latte.*
**Kosten: mittel** (Vorschau-Rechnung ist ohnehin Part-4-Gate; hier Präsentation + Teil-Anwendung).

### 5.2 Ein Vorschau-Widget für Publish *und* Move
Publish-Vorschau (5.1) und Move-Vorschau (4.1) sind **dasselbe Widget** über derselben Funktion
(Roadmap: beide laufen denselben Over-Exposure-Check). Der Archivar lernt *eine* „Wer sieht das?"-
Affordanz; es gibt genau eine kanonische `Effective Audience`-Rechnung (ADR 0001), nie eine
ad-hoc zweite.
*Warum: eine Interaktion, an zwei Stellen wiederverwendet; weniger zu lernen, weniger zu warten.*
**Kosten: mittel** (fällt mit 4.1/5.1 zusammen — kein Extra).

**BAN:** kein client-seitiger JS-Spiegel der Audience-Leiter für „sofortige" Vorschau. Das
dupliziert die eine Funktion, die singulär bleiben muss → das Marquee-Datenleck-Risiko. Voller
Server-Round-Trip bei `change` ist korrekt und für ein Formularsteuerelement schnell genug.

---

## Querschnitt (Cross-Cutting)

### Deutsche Terminologie
- **Primäre UI-Labels bleiben die CONTEXT.md-Begriffe:** *Artikel, Sammlung, Signatur, Sichtbarkeit,
  Schlagwort, Standort, Medienart, Dokumenttyp, Entwurf, Veröffentlicht.*
- **Archivische Wörter als Anzeige-Rahmung und Abschnitts-Überschriften** (keine Umbenennung des
  Domänenmodells): *Findbuch, Tektonik, Bestand, Serie, Datierung, Umbettung, Herkunft, Vermerk,
  Digitalisat, Katalogkarte / Zettel.* Diese lassen die App als *ein Archiv* lesen statt als
  CRUD-App mit deutschen Labels. **Offene Frage** unten: wie weit soll diese Rahmung gehen?
- **Feld-Floors als Abwesenheit, nie als ausgegrauter Hinweis** — ein Mitglied sieht die
  Standort-/Custom-Zeilen schlicht nicht; kein „🔒"-Affordance, das Existenz verrät. Deckt sich
  mit dem Existenz-Verbergen-Leak-Test (Part 4).

### No-JS / Progressive Enhancement
Jede Idee hat einen No-JS-Baseline. JS ist additiv. Genau drei Stellen rechtfertigen einen
Alpine-Level-Sprinkle: (a) Combobox-Tastaturnavigation (3.8), (b) Katalog-Tastenkürzel (3.9),
(c) Lightbox-Fokusfalle (2.3) — alle mit echtem Fallback-Pfad (Textfeld/`<datalist>`,
Maus-Aktion, echter Medien-Link).

### URL-as-State
Der Such-/Browse-Zustand lebt komplett in der Query-String (1.1). Jeder gefilterte Zustand ist
bookmarkbar und teilbar und löst in 10 Jahren ohne JS auf. Nummerierte Paginierung mit Seite in
der URL — **kein** Infinite-Scroll.

### Banned Patterns (vorab abgelehnt)
1. **Client-seitiger Spiegel der Audience-Leiter** (für „sofortige" Vorschau) → dupliziert die
   eine Funktion, Marquee-Leak-Risiko. Immer server-rechnen.
2. **Drag-and-Drop** überall (Baum-Move, Galerie-Reorder, Tag-Chips) → teuer, No-JS-feindlich,
   schlecht entdeckbar; beim Move versteckt es die Expositions-Konsequenz. Selects + Move-Buttons
   + explizite Bestätigung.
3. **Scroll-getriggertes Infinite-Scroll** → bricht Zurück-Button, No-JS, Footer; braucht
   gehaltenen Scroll-State. Nummerierte Seiten + opt-in „Weitere laden".
4. **Scoped Facettenzähler bei jedem Tastenanschlag neu rechnen** → das Aggregat ist die teure
   Query; Tastenanschläge tauschen nur Ergebnisse, Zähler nur bei Submit/Facetten-Klick.
5. **Optimistische UI bei sichtbarkeits-/schreib-relevanten Aktionen** (Publish, Move,
   Audience-Änderung) → ein falsches „hat geklappt / ist jetzt versteckt" ist ein
   Vertraulichkeits-Bug. Voller Round-Trip + server-gerenderte Bestätigung. Optimistisch nur für
   triviales Lokales (Caption-Edit).
6. **Live-„N Treffer" via WebSocket/SSE-Polling** → kein Concurrent-Writer-Druck (Handvoll
   Archivare, Full-Rebuild-Sync in v1); Request/Response-Zähler reicht.
7. **JS-EDTF-Parser / Datepicker** → würde vom kanonischen Parser driften; EDTF-Unschärfe hat
   keine sinnvolle Picker-UI. Text rein + Server-Echo.

### HTMX-vs-Datastar — Notizen für den Prototyp
- **Screens, die NICHT diskriminieren (in beiden gleich, egal welches):** Facettensuche + URL-State
  (1.1), Paginierung, Thumbnails (2.4), Inline-Caption-Edit, Sichtbarkeits-/Move-Vorschau
  (4.1/5.1) — alles reines Fragment-Swap-auf-Request.
- **Screens, die diskriminieren — im Prototyp doppelt bauen:**
  - **Katalogform mit Upload (3.10)** — Progress/Multipart ist HTMX-Heimspiel; testen, ob
    Datastars fetch/SSE-Modell Upload-Progress umständlich macht. Höchstes Signal.
  - **Combobox-schwere Autocomplete (3.8)** — HTMX+Alpine (zwei Paradigmen für ein Widget) vs.
    Datastar-Signals (ein Paradigma). Testet, ob Datastar den Alpine-Sprinkle auf null drückt.
  - **Debounced Suchbox (1.7)** — Event-Attribut-Debounce vs. Signal+Action-Modifier-Debounce;
    kleine, klärende Denkmodell-Sonde.
- **Datastars Live/SSE-Stärken sind in v1 ungenutzt** (keine Echtzeit-Kollaboration,
  Full-Rebuild-Sync). Den Prototyp nicht auf eine Fähigkeit gewichten, die das Archiv nicht
  braucht — gewichten auf Upload-Ergonomie und Combobox-State.

---

## Offene Fragen für den Inhaber (max. 8)

1. Wie weit soll die Findbuch-Rahmung gehen — nur Überschriften (*Bestand, Datierung, Herkunft*)
   oder das Layout ganzer Screens (Tektonik-Baum als Browse-Achse)?
2. Startseite: search-first (ein großes Suchfeld) oder browse-first (Tektonik + Einstiege) — oder
   der hybride Mittelweg (Suchfeld oben, Einstiege darunter)?
3. Kartenliste oder Thumbnail-Raster als Ergebnis-Standard — und soll auto-Raster bei foto-lastigen
   Trefferlisten kippen?
4. Ist „Ohne Datum (450)" ein erstklassiger Facetten-Filter (Bestand ehrlich sichtbar) oder eher
   dezent im Hintergrund?
5. Batch-Upload-first („Stapel anlegen", 3.1) als primärer Katalog-Einstieg, oder bleibt die
   Einzel-Artikel-Form der Haupteinstieg?
6. Publish-Vorschau menschen-förmig („Alle Mitglieder", benannte Gruppen) oder als
   Audience-Leiter-Stufen — welche Sprache trifft die Archivare?
7. Resumable/chunked Upload in v1 (teuer, `putLarge`/Chunk-Endpoint-Lücke) oder nur
   Fortschrittsbalken, resumable deferred?
8. Kuratierte Einstiege — dürfen Archivare sie später selbst bearbeiten (kleine Config), oder sind
   sie fix im Code?
