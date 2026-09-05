# Fristående prototyp på Debian 13 amd64

Prototypen bygger lokalt, laddar wrappern utan hårdvaruåtkomst och kan ta emot
en validerad bild från en separat process. Testerna använder syntetiska data.
VFS491-bildinsamling och inloggning är ännu inte verifierade.

## Bygg och testa

Förutsättningar: Debian 13 amd64 med `python3`, `gcc`, `make`, `perl`, `cpio`,
`dpkg-deb` och `bwrap` (paketet `bubblewrap`). Verktygen fanns på utvecklingsdatorn.

```sh
make test
python3 tools/prepare_compat.py
python3 tools/probe.py
python3 tools/probe.py --lazy
```

Förberedelseskriptet hämtar HP SP84530, OpenSSL 0.9.8zh och Debians
`libusb-0.1-4` med fasta SHA-256-kontroller. OpenSSL-kontrollsumman jämfördes
med [utgivarens checksumma](https://www.openssl.org/source/old/0.9.x/openssl-0.9.8zh.tar.gz.sha256),
och libusb-kontrollsumman med datorns APT-metadata för version
`2:0.1.12-35+b1`. HP-kontrollsumman identifierar den granskade nedladdningen.

Alla nedladdningar och byggresultat hamnar i `build/`. Endast wrappern och
daemonen extraheras till `private/`; inga installationsskript körs.
Inget installeras i systemets bibliotekskataloger. Byggloggen finns i
`build/compat-build.log`. OpenSSL byggs med `make -j1 build_libs`, eftersom
parallell körning i detta gamla byggsystem kan försöka länka innan
`libcrypto.a` har skapats. `Configure` startas uttryckligen med Perl.

Dessa historiska bibliotek är avsedda för den lokala prototypen, inte för
Debians nätverkstjänster. De gamla beroendena laddas bara i den isolerade
processen via dess `LD_LIBRARY_PATH`.

## Laddningstestets resultat

- Strikt test (`--probe`, `RTLD_NOW`) misslyckas på `mssAdaptiveMatcherOpen`.
- Statisk inspektion visar också odefinierade `mssDpOpen`, `mssCogentOpen` och
  `mssFingercellOpen` i wrappern. Den gamla drivrutinens byggfil använder
  `--allow-shlib-undefined`.
- Test med fördröjd bindning (`--probe-lazy`, `RTLD_LAZY`) laddar wrappern och
  hittar de elva API-funktioner som hjälparen behöver.

Fördröjd bindning innebär att kvarstående symbolfel kan uppstå först när en
viss kodväg används. Resultatet bevisar inte att capture fungerar. Inga
wrapper-API-funktioner anropas av probe; `dlopen` kan däremot köra bibliotekets
initieringskod. Därför körs testet med privat nätverk, IPC, processnamnrymd,
tomt `/tmp` och en syntetisk `/dev`, utan värddatorns hemkatalog eller USB.
Ingen värd-daemon blir åtkomlig via IPC. Testet har en timeout på tio sekunder.

## Hjälpare och överföring

`src/capture.c` bygger till `build/euther-capture` utan leverantörsbibliotek
vid länkningen. Vid `--capture` laddas wrappern med fördröjd bindning.
ABI-underlaget kommer från källan angiven i [granskningen](driver-review.md).

Bildprotokollet på stdout är:

| Fält | Format |
| --- | --- |
| Magic | Fyra byte: `EFP1` |
| Bredd | 32 bitar, big-endian |
| Höjd | 32 bitar, big-endian |
| Bilddata | Exakt bredd × höjd byte |

Båda dimensionerna måste vara 1–2048. Leverantörens stdout omdirigeras till
stderr innan biblioteket laddas. Föräldraprocessen `tools/capture.py` läser
partiella leveranser, begränsar bilddata och diagnostik, och avslutar
processgruppen vid timeout eller fel. Bilden sparas först efter lyckat
processavslut och validering, som PGM med filrättighet `0600`. En befintlig
fil skrivs aldrig över. Pixelorientering och färginvertering är ännu inte
anpassade till riktig hårdvara.

Anropsformen för en framtida hårdvarusession är:

```text
python3 tools/capture.py --output captures/test.pgm -- <isolerad capture-process>
```

Detta är avsiktligt en anropsbeskrivning: en launcher med USB-åtkomst och
samordnad daemon finns inte ännu. Starta inte hjälparen direkt för att
kringgå föräldraprocessens timeout.

## Verifiering och nästa steg

Åtta tester täcker partiell överföring, ogiltiga dimensioner/längder, timeout,
ny insamling efter timeout, processfel, stängda pipes med kvarhängande process,
utdatagränser samt privat filskapande utan överskrivning. Ett av testerna
bygger ett syntetiskt wrapperbibliotek och kör hela C-hjälparen, inklusive
störande stdout och felaktig bildmetadata. Kompileringen använder
`-Wall -Wextra -Werror`.

Nästa steg är en separat hårdvarulauncher: ge enbart VFS491:s USB-enhet
åtkomst, dela privat IPC och `/tmp` mellan daemon och hjälpare, och samla
begränsade loggar. Daemonens enhetsbehörighet, beteende och eventuella
initieringskrav behöver verifieras. Inga `setowner`- eller firmwarekommandon
ingår i prototypen. En fysisk fingersvepning behövs för den första riktiga bilden.
