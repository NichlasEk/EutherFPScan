# libfprint och vägen till sudo

Den nya bilddrivrutinen `euther_vfs491` är byggd mot libfprint 1.94.9 och
testad isolerat och med riktiga svep. Registrering, rätt/fel finger och ny
verifiering efter avbrott har lyckats. Sudo-aktivering återstår enligt nedan.

## Bygg och verifiera

```sh
make test
python3 tools/build_libfprint.py
python3 tools/test_libfprint.py
python3 tools/check_fprintd.py
python3 tools/test_enroll_dbus.py
```

Byggskriptet hämtar Debians libfprint-källa med fast SHA-256. Utvecklingspaket
hämtas genom APT och packas upp i `build/sdk`, utan systeminstallation.
Versioner och kontrollsummor för de hämtade paketen sparas i
`build/sdk-packages.json`. Dessa paket följer datorns APT-versioner; SDK-delen
är inte ett versionslåst Debian-arkiv. C/C++-kompilator och pkg-config används
från värdsystemet. Testbildskonverteringen kräver ImageMagick (`magick`).

Byggloggen finns i `build/libfprint-build.log`. Biblioteket byggs med endast
Euther-drivrutinen och är avsett för denna dator. Det ersätter inte Debian-
paketet på disk. Ändrad libfprint-ABI eller fprintd-version kräver nya kontroller.

Mesons installationssteg körs först till `build/libfprint-stage` för att ta
bort byggkatalogernas RUNPATH. Installationsfilen i `build/libfprint-runtime`
kontrolleras med `readelf` och används även av integrationstesterna. Ingen
sökväg till det användarskrivbara SDK:t ska följa med till root-tjänsten.

## Installation och verklig registrering

Kör från projektmappen:

```sh
sudo bash tools/install_fprintd.sh
sudo python3 tools/enroll.py "$USER"
```

Installationen uppdaterar och startar om bildtjänsten, installerar vårt
libfprint i `/opt/eutherfpscan/fprint` och lägger till en systemd-drop-in för
fprintd. Bara fprintd får den privata bibliotekssökvägen och socketadressen.
Guiden använder Debians Python/Gio (`python3-gi`) och ansluter direkt till
fprintd. Tryck Enter när du är redo. Svep höger pekfinger **en gång per
uppmaning**, lyft fingret helt och vänta på nästa besked. Antalet moment läses
från fprintd; på denna dator rapporteras sex, inklusive dubblettkontrollen
före de fem registreringsstegen. Vid dålig kvalitet kan omsvep krävas.
Uppmaningar följer `finger-needed` och `EnrollStatus`; guiden pausar inte
tjänstens insamling mellan momenten. Ctrl+C stoppar registreringen och
släpper enheten. Bara `enroll-completed` räknas som lyckat slutresultat.

Guiden körs från projektmappen och kräver ingen ny tjänsteinstallation.
Den hanterar inga bildfiler eller mallar; lagringen sköts av fprintd.

Senaste hårdvarutestet 2026-09-05 kl. 09:09 bekräftade `USB_OPEN_OK` och
`IPC_READY`, men första insamlingen fick timeout efter 35 sekunder under
fprintds kontroll inför registrering. Orsaken till utebliven bild är ännu
inte fastställd. Det är inte bevis på fel finger eller fel svepteknik.
Vid nytt fel ska resultat och följande logg granskas före nästa försök:

```sh
sudo journalctl -u eutherfpscan -u fprintd -n 30 --no-pager
```

När registreringen lyckas:

```sh
fprintd-list "$USER"
fprintd-verify "$USER"
```

Kontrollera `verify-match` med registrerat finger. Kör verifieringen igen med
ett annat, oregistrerat finger och kontrollera `verify-no-match`. Ett fel eller
en timeout är inte ett bevis på att ett annat finger avvisas korrekt. Prova
också Ctrl+C under väntan och därefter en ny lyckad verifiering med rätt finger.
Detta behövs eftersom det äldre leverantörsbiblioteket kan reagera annorlunda
på avbrott än våra testkomponenter.

fprintd lagrar riktiga mallar i sin root-skyddade katalog `/var/lib/fprint`.
De hör inte hemma i Git. `captures/`, `private/`, `build/` och `vendor/` är
fortsatt ignorerade. Filer från din riktiga bildinsamling används inte av de
automatiska integrationstesterna.

## Hur drivrutinen arbetar

```text
fprintd → privat libfprint (euther_vfs491) → root-skyddad Unix-socket
                                            ↓
                           isolerad bildtjänst → VFS491
```

Drivrutinen är en `FpImageDevice`-underklass. Den använder libfprints virtuella
enhetsupptäckt som transportadapter, aktiverad via `FP_EUTHER_VFS491`. Detta
är inte libfprints generiska drivrutin för injektion av testbilder.
Varje insamling öppnar en anslutning till bildtjänsten och begär en ny bild.
Peer-UID måste överensstämma med processen: för root-körd fprintd krävs root.

Socket-I/O körs i en avbrytbar GTask-tråd. Bildstorlek, datalängd och EOF
valideras före överlämning till libfprint. Drivrutinen normaliserar bilden
med vertikal spegling och färginvertering enligt den äldre VFS-drivrutinen.
Libfprint extraherar minutier, registrerar fem svep och utför NBIS-matchning.
Standardtröskeln för matchning har inte sänkts.

Vid avbrott stängs anslutningen. Bildtjänsten upptäcker frånkopplingen och
stoppar den pågående hjälpprocessen. En tillfällig libfprint-instans som körs
som vanlig användare kan ansluta till en egen testserver, men har ingen
koppling till systemets root-körda fprintd eller sudo.

## Genomförda tester

- Tjugo enhetstester för hjälpare, sockettjänst, avbrott och guidens steg.
- Guiden testas på privat D-Bus med syntetiska status- och egenskapssignaler:
  sex moment, terminalt fel och Ctrl+C. Både `EnrollStop` och `Release`
  kontrolleras. Dessa tester använder ingen läsare eller fingeravtrycksmall.
- Fyra integrationstester genom det byggda libfprint: bildinsamling;
  femstegsregistrering, serialisering/återläsning, träff och utebliven träff;
  avbrott; felaktiga/trunkerade svar och extra data.
- Matchningstestet använder offentliga NIST-exempel från libfprints källarkiv,
  upprepade bilder av samma exempel och ett annat exempel. Det verifierar
  programflödet, inte träffsäkerhet för nya svep på den riktiga läsaren.
- Debians `/usr/libexec/fprintd` startas på en privat D-Bus och rapporterar
  `EutherFPScan Validity VFS491`. Ingen systemregistrering görs i detta test.
- Separat lokal kontroll: den redan sparade riktiga bilden `captures/first.pgm`
  passerade libfprints bildbearbetning som 200 × 255 pixlar. Ingen mall sparades;
  detta ersätter inte registrering och verifiering med nya svep.

## Sudo efter godkända hårdvarutester

Hårdvaruproven har nu lyckats: höger pekfinger är registrerat, rätt finger
gav `verify-match`, ett annat finger gav `verify-no-match`, och användarens
nya verifiering efter agentens Ctrl+C-prov gav `verify-match`.

Sudo-installationen är förberedd men ännu inte aktiverad. Förhandsgranska,
aktivera och prova i användarens synliga terminal:

```sh
python3 tools/install_sudo.py
sudo python3 tools/install_sudo.py --apply
sudo -k
sudo whoami
```

Svep registrerat finger vid uppmaningen. Resultatet ska vara `root`.
Gör sedan ett nytt `sudo -k` och `sudo whoami`, låt bli att svepa och
kontrollera att lösenord fungerar efter väntetiden. Regeln är
`auth sufficient pam_fprintd.so max-tries=1 timeout=15` före `common-auth`
enbart i `/etc/pam.d/sudo`. PAM kör alternativen i följd. Kontroller av konto,
session och sudoers-behörighet gäller fortfarande. Inga lösenord tas emot i chatten.

Skriptet kontrollerar att sudo och common-auth motsvarar granskade versioner,
sparar originalet root-skyddat i `/var/lib/eutherfpscan/pam-sudo.backup` och
ersätter sudo-filen atomiskt. Upprepad installation gör ingen ny ändring.
Återställ med:

```sh
sudo python3 tools/install_sudo.py --remove
```

Återställningen avbryts om PAM-filen har ändrats utanför skriptet.
Tester kör den riktiga libpam med syntetiska autentiseringsresultat och
privata konfigurationsfiler: träff, lösenordsfallback vid fel, avvisning när
båda alternativen misslyckas, och fortsatta kontokontroller. Ingen riktig
autentisering eller systemändring görs av testerna.

Agentens verktygsterminal visas inte som användarens vanliga terminal.
Ett framtida prov av sudo från agentens PTY måste därför föregås av ett
uttryckligt besked i chatten och en överenskommen tid att svepa. Ett osynligt
försök som får timeout är inte ett bevis på felaktig läsare.

För att återgå till Debians vanliga fprintd-bibliotek:

```sh
sudo rm /etc/systemd/system/fprintd.service.d/euther.conf
sudo systemctl daemon-reload
sudo systemctl restart fprintd
```

Detta tar inte bort registrerade mallar eller privata bilder.

Källor: [libfprints interna bild-API](https://fprint.freedesktop.org/libfprint-dev/libfprint-2-Internal-FpImageDevice.html),
[fprintds status- och egenskapssignaler](https://fprint.freedesktop.org/fprintd-dev/Device.html),
[Debians pam_fprintd](https://manpages.debian.org/trixie/libpam-fprintd/pam_fprintd.8.en.html).
