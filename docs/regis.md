# System Regis IV

Ett svenskt GTK 3-gränssnitt till EutherFPScan och fprintd. Mörkblått, guld,
tre kronor och ljusa kretslinjer möter ett register med tio valbara fingrar.

## Installera och öppna

Kör som din vanliga skrivbordsanvändare, utan sudo:

```sh
python3 tools/install_gui.py
```

Öppna **System Regis IV** i startmenyn. Installationen ligger i
`~/.local/share/system-regis-iv`, med en startmenypost i
`~/.local/share/applications/se.euther.SystemRegisIV.desktop`.
Appikonen installeras i användarens hicolor-ikontema. Startmenypostens namn
matchar appens Wayland-ID så att aktivitetsfältet visar Regis-sigillet.
Kör installationskommandot igen efter uppdateringar av projektet.
Från källkoden kan appen startas med `python3 tools/regis.py`.

Appen behöver `python3-gi`, `gir1.2-gtk-3.0` och den fungerande
[fprintd-integrationen](libfprint.md). Dessa finns på utvecklingsdatorn.

## Användning

- Välj användare till vänster. Ditt eget register hämtas vid start.
  **Läs alla register** hämtar status för alla listade användare.
- Välj ett finger och **Registrera finger**. Tryck **Börja** när du är redo
  och följ uppmaningarna för varje svep. fprintd kan begära sex moment:
  en dubblettkontroll och fem registreringssvep.
- **Verifiera** testar ett registrerat finger och visar träff eller ingen träff.
- **Radera finger** visar användare och finger i en bekräftelsedialog.
  Bara det valda fingret raderas. Redan skickad radering kan inte återkallas.
- **Avbryt** stoppar pågående registrering/verifiering och släpper läsaren.

Listan omfattar det egna kontot, root och vanliga lokala inloggningskonton
(UID 1000–65533, utan nologin/false-skal). Appen skapar inga användarkonton.
Systemets vanliga Polkit-dialog kan begära behörighet, särskilt när du
hanterar någon annans register. Appen körs inte som root.
Ett register som inte kunnat läsas visas som okänt, aldrig som tomt.

fprintd kan avslutas när den är inaktiv. **Anslut** hämtar då tjänsten och
aktuella uppgifter igen. Fingeravtrycken lagras av fprintd; GUI:n läser inga
bildfiler eller mallfiler och ändrar inte PAM- eller sudo-inställningar.

## Verifiering

```sh
python3 tools/test_regis.py
EUTHER_TEST_GUI=1 GDK_BACKEND=x11 python3 tools/test_regis.py
make test
```

GUI-testläget kör tio tester på en privat D-Bus med syntetiska register.
Det kontrollerar bland annat behörighetsfel, rätt användare vid radering,
bekräftelsedialogen, svepuppmaningar, avbrott och tidiga statussignaler.
Inga riktiga avtryck ändras av testerna.

2026-09-05: tio GUI/backend-tester och 26 befintliga tester passerade.
Den nya klienten läste även utvecklingsdatorns verkliga register och hittade
`right-index-finger` för `nichlase`. Registrering och radering via GUI på
den verkliga läsaren återstår att prova; tidigare CLI-registrering,
verifiering och sudo-autentisering är bekräftade.

En tydligt märkt förhandsvisning med exempeldata kan sparas utan fprintd:

```sh
GDK_BACKEND=x11 python3 tools/regis.py --preview build/regis-preview.png
```

API-referenser: [fprintd Device](https://fprint.freedesktop.org/fprintd-dev/Device.html)
och [GtkApplication](https://docs.gtk.org/gtk3/class.Application.html).
