# libfprint och vägen till sudo

Den nya bilddrivrutinen `euther_vfs491` är byggd mot libfprint 1.94.9 och
testad isolerat. Debians riktiga fprintd kan upptäcka enheten med detta
bibliotek. Registrering med nya svep från läsaren återstår före sudo-aktivering.

## Bygg och verifiera

```sh
make test
python3 tools/build_libfprint.py
python3 tools/test_libfprint.py
python3 tools/check_fprintd.py
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
sudo fprintd-enroll -f right-index-finger "$USER"
```

Installationen uppdaterar och startar om bildtjänsten, installerar vårt
libfprint i `/opt/eutherfpscan/fprint` och lägger till en systemd-drop-in för
fprintd. Bara fprintd får den privata bibliotekssökvägen och socketadressen.
Vänta på instruktionen och svep höger pekfinger fem gånger vid registreringen;
vid dålig kvalitet kan fler svep krävas. Avsluta med Ctrl+C vid upprepade fel
och granska resultatet före nya försök.

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

- Elva tester för hjälpare, sockettjänst och avbrott.
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

Nästa steg är att lägga `pam_fprintd` före lösenordsautentiseringen enbart
för sudo, med lösenord kvar som reserv efter fel eller timeout. PAM är ännu
oförändrat. Fingeravtryck och lösenord erbjuds normalt i följd i denna PAM-
stack, inte samtidigt. Slutprovet måste köras från agentens egen PTY med en
ny sudo-autentisering och ett uttryckligt fingersvep.

För att återgå till Debians vanliga fprintd-bibliotek:

```sh
sudo rm /etc/systemd/system/fprintd.service.d/euther.conf
sudo systemctl daemon-reload
sudo systemctl restart fprintd
```

Detta tar inte bort registrerade mallar eller privata bilder.

Källor: [libfprints interna bild-API](https://fprint.freedesktop.org/libfprint-dev/libfprint-2-Internal-FpImageDevice.html),
[Debians pam_fprintd](https://manpages.debian.org/trixie/libpam-fprintd/pam_fprintd.8.en.html).
