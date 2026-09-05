# Automatisk start och hårdvarusession

Status: en riktig bild på 200 × 255 pixlar lyckades 2026-09-05 kl. 08:19.
Tjänsten är installerad och aktiverad vid uppbootning, men en senare uppdatering
misslyckades vid start när läsaren bytte USB-adress. En korrigering är nu
testad lokalt och väntar på installation och hårdvaruverifiering.
Ingen inloggningsintegration eller automatisk insamling ingår.

## Installera

Från projektmappen, efter `make test` och `python3 tools/prepare_compat.py`:

```sh
sudo bash tools/install_service.sh
```

Lösenordet anges i din egen terminal. Skriptet kopierar program och privata
bibliotek till `/opt/eutherfpscan`, installerar systemd-filen och startar
tjänsten. Det aktiverar start vid uppbootning först efter ett lyckat
statusanrop genom daemonens socket. Ingen kod körs från din hemkatalog av den
installerade tjänsten. Ändringar i repot kräver att installationsskriptet körs igen.

`IPC_READY` betyder att daemonen skapade sin interna kommunikation, inte att
en fungerande fingeravtrycksbild har verifierats. Systemd-status `active`
räcker inte som bevis på fungerande läsare. Vid misslyckad start ska loggarna
granskas innan nästa försök. Tjänsten gör inga automatiska omstarter vid fel.

```sh
sudo systemctl status eutherfpscan --no-pager
sudo journalctl -u eutherfpscan -n 60 --no-pager
sudo python3 /opt/eutherfpscan/tools/service.py --status
systemctl is-enabled eutherfpscan
```

## Första bilden

När statusanropet fungerar, kör följande och svep ett finger över läsaren
inom 35 sekunder:

```sh
mkdir -p captures
sudo python3 /opt/eutherfpscan/tools/capture.py \
  --timeout 45 --output "$PWD/captures/first.pgm" -- \
  python3 /opt/eutherfpscan/tools/service.py --request
```

Resultatet är en PGM-bild med rättighet `0600`, ägd av root eftersom kommandot
körs med sudo. Befintliga bilder skrivs inte över. Bildorienteringen är ännu
inte kalibrerad. Lägg bilder i `captures/`, som ignoreras av Git. `private/`,
`vendor/` och `build/` ignoreras också; inga bilder är spårade i det granskade läget.

## Isolering och livscykel

Tjänsten identifierar exakt en USB-enhet med `138a:003d` vid start. En
värdprocess följer sysfs var 100 ms och underhåller en filtrerad katalog med
läsarens aktuella USB-enhetsnod under `/run/eutherfpscan/usb`. Obsoleta noder
tas bort innan ersättare läggs till. Katalogen exponeras skrivskyddad som
sandboxens `/dev/bus/usb`; aliaset under `/run/eutherfpscan/usb` är också
skrivskyddat. Daemon och hjälpare delar privat
IPC och `/tmp`; nätverk, processnamnrymd och övriga USB-enheter är isolerade.
Sysfs är läsbart för enhetsupptäckt. Privat leverantörstillstånd ligger i
`/var/lib/eutherfpscan/etc` och exponeras som sandboxens `/etc`.
Kontrollsocketen under `/run/eutherfpscan` är endast åtkomlig för root.

Systemd stoppar hela processgruppen, och sandboxens PID-namnrymd tar hand
om forkade daemonprocesser. Vid omstart av datorn startas endast daemonen;
en bild tas bara efter ett uttryckligt capture-anrop. Nya USB-adresser syns
utan omstart av sandboxen. Leverantörsdaemonens återhämtning efter
återanslutning/vila samt riktig uppbootning återstår att hårdvarutesta.

Det gamla `validity-sensor setowner -doinit`, leverantörens udev-skript och
firmwarefiler installeras inte av detta skript.

## Stäng av automatisk start

```sh
sudo systemctl disable --now eutherfpscan
```

Det bevarar programfiler och privat tillstånd. Ingen ändring av PAM,
fprintd eller Debian-systembiblioteken görs av installationen.

## Genomförda kontroller

- Tio tester passerar, inklusive en syntetisk socket-session med flera
  insamlingar, felaktigt kommando, rättigheter och nedstängning.
- `systemd-analyze verify systemd/eutherfpscan.service` passerar.
- Bash-syntax och Python-kompilering passerar.
- Leverantörsdaemonen startades i en separat sandbox utan USB; det gav
  uppstartsmeddelande och vissa IPC-filer men ingen färdig readiness-markör.
  Det är inte ett lyckat hårdvarutest.
- Användaren installerade tjänsten med sudo. Agenten verifierade därefter
  `active` och `enabled`; agentens sudo-session kräver fortfarande lösenord.

## USB-adressbyte vid senaste uppdateringen

Journalen visar start mot `003/005` kl. 08:46:48 följt av utebliven IPC-markör.
Efter felet visade `lsusb` samma läsare på `003/006`, med enhetsnoden skapad
kl. 08:46; `003/005` fanns inte längre. Den tidigare bind-mounten av en enda
nod kunde inte följa detta byte. Den filtrerade USB-katalogen ersätter denna
statiska koppling. Inga reset-, setowner- eller firmwarekommandon har körts.

Fjorton tester passerar efter korrigeringen, inklusive en riktig bubblewrap-
sandbox med syntetiska nodfiler: den ser att `003/005` försvinner och `003/006`
tillkommer, och båda katalogvägarna förblir skrivskyddade. Skapande av riktiga
USB-teckenenheter kräver root och verifieras vid användarens installation.

## Diagnostik efter första timeouten

Första försöket gav `ERROR: Capture timed out`. Den då installerade versionen
bevarade inte stderr vid timeout, så felet säger inte vilket steg som fastnade.
Hjälparen skriver nu `EUTHER_STAGE` före varje leverantörsanrop och
`EUTHER_RESULT` efter initierings- och capture-anrop. Föräldern inkluderar de
senaste 2048 diagnostikbyten i timeoutsvaret, aldrig bilddata.

Uppdatera med `sudo bash tools/install_service.sh` och gör sedan ett nytt
insamlingsförsök enligt ovan. Installationen startar om den gamla daemonen
så nästa försök får en ny IPC-session. Rapportera sista `EUTHER_STAGE` och
eventuella returkoder. `capture_wait_for_swipe` betyder att capture-funktionen
anropades; det bevisar inte ensamt att hårdvaran är redo.
