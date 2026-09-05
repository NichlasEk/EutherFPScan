# VFS491: granskning inför Debian 13

Granskat 2026-09-05. Slutsats: en portning är tekniskt tänkbar, men den gamla
drivrutinen kan inte användas direkt. Första milstolpen bör vara fristående
bildinsamling i en isolerad kompatibilitetsmiljö. Hårdvarufunktion är ännu oprövad.

## Granskade artefakter

- [rindeals källkod](https://github.com/rindeal/libfprint-vfs_proprietary-driver/tree/4f26cc8c51bd61fda9fcac27c9fa37c9ae54bad2),
  commit `4f26cc8c51bd61fda9fcac27c9fa37c9ae54bad2`.
- Debian-källpaket `libfprint 1:1.94.9-1`, hämtat med `apt-get source --download-only libfprint`.
- [HP SP84530](https://ftp.hp.com/pub/softpaq/sp84501-85000/sp84530.tar), hämtat från
  adressen i rindeals byggskript. SHA-256:
  `dc9128f965532dd0140d9bcf662ef7a4180ba5fd182c5f8056119c0e967c0364`.
  Denna kontrollsumma identifierar hämtningen; den är inte en separat signaturkontroll.
- HP-arkivet innehåller `Validity-Sensor-Setup-4.5-136.0.x86_64.rpm`.

Källor och uppackade binärer granskades under `/tmp`, utanför projektet.
Ingen RPM installerades och ingen leverantörsbinär kördes.

## Vad den gamla drivrutinen faktiskt gör

```text
libfprint → öppen drivrutin → separat capture-helper
                                   ↓
                         libvfsFprintWrapper.so
                                   ↓
                              vcsFPService → USB-läsare
```

`vfs_proprietary.c` identifierar VFS491. Hjälpprogrammet anropar
`vfs_wait_for_service`, väljer matcher, öppnar enheten och anropar `vfs_capture`.
Det hämtar bildens bredd, höjd och data från wrapperbiblioteket och skickar dem
via pipes till föräldraprocessen. Den öppna koden implementerar alltså inte
VFS491:s USB-protokoll.

Samtliga elva wrapperfunktioner som deklareras i `vfsFprintWrapper.h` återfanns
som exporterade symboler i HP-paketets 64-bitarsbibliotek. Detta stöder att
paketet passar hjälpprogrammets gränssnitt, men bevisar inte fungerande körning.

## Binärberoenden på den här datorn

`readelf -d` användes för statisk inspektion och jämfördes med `ldconfig -p`.
Ingen `ldd` eller dynamisk inläsning av leverantörskoden användes.

| Direkt beroende | vcsFPService | Wrapper | I datorns loader-cache |
| --- | --- | --- | --- |
| `libusb-0.1.so.4` | Ja | Ja | Saknas |
| `libcrypto.so.0.9.8` | Ja | Ja | Saknas |
| `libssl.so.0.9.8` | Ja | Ja | Saknas |
| `libusb-1.0.so.0` | Ja | Nej | Finns |

Båda är x86-64 ELF och kräver även vanliga glibc-bibliotek. De har RPATH till
leverantörens gamla byggkataloger under `/usr/src/4_5_1xx/`.
Fullständig beroendeupplösning och ABI-kompatibilitet återstår att verifiera.
OpenSSL 3 på datorn uppfyller inte ett beroende på SONAME `libssl.so.0.9.8`;
ett namnbyte eller en symlänk löser inte ABI-skillnaden.

## Skillnader mot libfprint 1.94.9

| Gammal implementation | Nödvändigt arbete |
| --- | --- |
| `struct fp_img_driver`, `struct fp_img_dev` | Implementera en `FpImageDevice`-underklass och klassmetoder |
| `fpi_imgdev_*`, heltalsfel | Använd dagens `fpi_image_device_*` och `GError` |
| Blockerande `capture_helper_wait_until_finished()` i activate | Asynkron process- och pipehantering integrerad med GLib |
| Lokala callbackdata på activate-funktionens stack | Tillstånd med livstid knuten till enheten/operationen |
| Enkel deactivate utan hantering av pågående capture | Avbryt, städa processer och slutför operationer även mitt i insamling |
| Metadata som native C-strukturer | Definiera ett tydligt protokoll och hantera partiella läsningar |

Nuvarande interna API kräver att bilddrivrutinen klarar `deactivate` under
pågående insamling. Debian-kodens `fp-device.c` öppnar också USB-enheten före
USB-drivrutinens egen open-metod. Samspelet med daemonens USB-åtkomst behöver
provas; det är inte fastställt att detta orsakar en konflikt.

Den gamla bildkontrollen begränsar dimensioner och datalängd var för sig men
kontrollerar inte `längd == bredd × höjd`. En ny implementation behöver även
övre storleksgräns, överflödskontroll och robust felhantering. Hjälparens
alarmuttryck kan ge `alarm(0)` när tidsbudgeten löpt ut, vilket avaktiverar
alarmet; den nya föräldraprocessen bör äga en oberoende timeout.

## Licens och initiering

Den granskade öppna C-koden anger LGPL-2.1-or-later. Vid återanvändning ska
copyright, licenstext och ändringsinformation följa med. Licensen för den öppna
koden ger inte automatiskt distributionsrätt till HP:s binärer. Deras
distributionsvillkor är inte fastställda i denna granskning; binärer har inte
kopierats till Git-projektet.

HP-paketet innehåller också `validity-sensor`, `HPUsbVFS491.img`, init- och
udev-skript. Paketets README beskriver `validity-sensor setowner -doinit` som en
åtgärd som ändrar en osäkrad sensor till secure mode. Detta är ingen
diagnosåtgärd och ingick inte i undersökningen. Behovet av sådan initiering på
den här datorn är okänt.

## Genomförd byggkontroll

```sh
gcc -Wall -Wextra -c \
  /tmp/euther-vfs-review/vfs_proprietary/capture-helper/main.c \
  -o /tmp/euther-vfs-helper.o
```

Kompileringen lyckades, med varningar om oanvända parametrar. Detta är en
objektfilskontroll: ingen länkning, start av daemon, bildinsamling eller
libfprint-portning har verifierats.

## Nästa byggsteg och godkännandekriterier

1. Ta fram en reproducerbar privat kompatibilitetsmiljö med spårbara
   OpenSSL 0.9.8- och libusb 0.1-beroenden. Kontrollera ELF-beroenden före körning.
   Behåll Debian 13:s systembibliotek.
2. Bygg en fristående hjälpare med timeout från föräldraprocessen, robust IPC
   och validerad bildstorlek. Prova felvägar med syntetiska bilder:
   avbruten överföring, ogiltiga dimensioner, timeout och processavslut.
3. Prova därefter daemon och bildinsamling med läsaren. Milstolpen är en riktig
   bild med rimliga dimensioner och en andra lyckad insamling efter avbrott.
   Biometriska bilder och råa USB-spår ska hållas lokala.
4. Först när insamlingen fungerar: implementera och bygg en `FpImageDevice`-port
   mot Debian-versionen, följt av registrering och verifiering genom fprintd.

Om kompatibilitetsmiljön inte fungerar är alternativet att kartlägga protokollet
med en fungerande leverantörsstack och skriva en öppen USB-implementation.
Den nu granskade koden räcker inte för att implementera det protokollet.

## Ytterligare referenser

- [Projektets avslutsbesked från 2020](https://github.com/rindeal/libfprint-vfs_proprietary-driver/issues/8)
- [Nuvarande interna FpImageDevice-API](https://fprint.freedesktop.org/libfprint-dev/libfprint-2-Internal-FpImageDevice.html)
- [Debians libfprint-källpaket](https://tracker.debian.org/pkg/libfprint)
