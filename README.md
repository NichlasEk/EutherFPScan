# EutherFPScan

Projekt för att få fingeravtrycksläsaren i en HP ProBook 4340s att fungera
på Debian 13. Status: en fristående prototyp och lokala kompatibilitetsbibliotek
finns. Bildöverföringen är testad med syntetiska data; riktig bildinsamling och
fingeravtrycksregistrering är ännu inte verifierade.

Den äldre drivrutinen och HP:s originalbinärer är nu granskade.
Se [portningsbedömning och byggsteg](docs/driver-review.md). Hjälpprogrammets
C-kod kompilerar, men binärerna kräver äldre bibliotek som saknas på datorn.

Vi bygger nu dessa bibliotek lokalt. Se [prototypens bygginstruktioner och
testresultat](docs/prototype.md). Kör `make test` för tester utan hårdvaruåtkomst.

[Systemd-tjänst och första hårdvarusession](docs/service.md) är förberedda.
Installera med `sudo bash tools/install_service.sh` från projektmappen.
Automatisk start aktiveras först när tjänstens interna kommunikation fungerar.

## Verifierat på utvecklingsdatorn, 2026-09-05

| Komponent | Resultat |
| --- | --- |
| Dator | HP ProBook 4340s |
| System | Debian GNU/Linux 13 (trixie), 13.5 |
| Kärna | 6.12.86+deb13-amd64 |
| USB-läsare | Validity Sensors VFS491, `138a:003d` |
| fprintd | `1.94.5-2`, installerat |
| libfprint-2-2 | `1:1.94.9-1`, installerat |
| `fprintd-list "$USER"` | `No devices available` |

USB-enheten upptäcks av Linux. Den installerade fingeravtrycksstacken exponerar
ingen läsare. Modellens USB-ID saknas också i libfprints aktuella lista över
stödda enheter i utvecklingsversionen, kontrollerad samma datum.

## Utvecklingsväg

1. Granska den äldre VFS491-drivrutinens källkod, binärberoenden och licenser.
2. Bedöm om stödet kan portas till dagens libfprint eller om USB-protokollet
   behöver kartläggas för en ny implementation.
3. Få bildinsamling att fungera i en isolerad prototyp på Debian 13.
4. Integrera registrering och verifiering med libfprint/fprintd när insamlingen
   fungerar. Inloggningsintegration kommer därefter.

Det äldre projektet anger uttryckligen stöd för `138a:003d`, men är beroende
av proprietära binärer. Det är en referens för fortsatt granskning, inte en
verifierad lösning för Debian 13.

## Upprepa grunddiagnosen

```sh
lsusb -d 138a:003d
cat /etc/os-release
cat /sys/class/dmi/id/product_name
apt-cache policy fprintd libfprint-2-2
fprintd-list "$USER"
```

Grunddiagnosen registrerar inga fingeravtryck. Inga systempaket eller
inloggningsinställningar har ändrats under den första undersökningen.

## Källor

- [libfprint: Supported Devices](https://fprint.freedesktop.org/supported-devices.html)
- [Äldre VFS-drivrutin med uttryckligt VFS491-stöd](https://github.com/rindeal/libfprint-vfs_proprietary-driver)
