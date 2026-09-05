# Automatisk start och hårdvarusession

Status: tjänst och installationsskript är förberedda och testade med syntetisk
hårdvara. Installation och riktig USB-insamling väntar på lokal sudo-körning.
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

Tjänsten identifierar exakt en USB-enhet med `138a:003d` vid start och ger
sandboxen åtkomst till just den enhetsnoden. Daemon och hjälpare delar privat
IPC och `/tmp`; nätverk, processnamnrymd och övriga USB-enheter är isolerade.
Sysfs är läsbart för enhetsupptäckt. Privat leverantörstillstånd ligger i
`/var/lib/eutherfpscan/etc` och exponeras som sandboxens `/etc`.
Kontrollsocketen under `/run/eutherfpscan` är endast åtkomlig för root.

Systemd stoppar hela processgruppen, och sandboxens PID-namnrymd tar hand
om forkade daemonprocesser. Vid omstart av datorn startas endast daemonen;
en bild tas bara efter ett uttryckligt capture-anrop. Om läsaren får en ny
USB-adress efter återanslutning eller vila behövs en tjänsteomstart. Detta
och riktig uppbootning är ännu inte hårdvarutestade.

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
- `sudo -n true` kräver lösenord på datorn. Ingen systeminstallation eller
  aktivering av automatisk start har därför utförts av agenten.
