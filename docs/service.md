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

`IPC_READY` kräver nu både readiness-fil och en levande `vcsFPService` i
sandboxens processnamnrymd. Det betyder att daemonen skapade sin interna kommunikation, inte att
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
läsarens aktuella USB-enhetsnod under `/dev/eutherfpscan-usb-*/usb` i en
slumpnamngiven privat katalog med rättighet `0700`. `/dev` tillåter
enhetsåtkomst; `/run` har `nodev` och får inte användas som källa. Obsoleta noder
tas bort innan ersättare läggs till. Katalogen exponeras med `--dev-bind` som
sandboxens `/dev/bus/usb`, med enhetsåtkomst tillåten. Den katalogvägen är
skrivbar; processens capabilities tas uttryckligen bort med `--cap-drop ALL`
så att den inte kan skapa nya teckenenheter. Aliaset under
`/run/eutherfpscan/usb` är skrivskyddat. Daemon och hjälpare delar privat
IPC och `/tmp`; nätverk, processnamnrymd och övriga USB-enheter är isolerade.
Sysfs är läsbart för enhetsupptäckt. Privat leverantörstillstånd ligger i
`/var/lib/eutherfpscan/etc` och exponeras som sandboxens `/etc`.
Kontrollsocketen under `/run/eutherfpscan` är endast åtkomlig för root.
Den tillfälliga spegelkatalogen tas bort vid normalt avslut och hanterade
uppstartsfel. Ett SIGKILL kan lämna katalogen kvar till nästa uppbootning;
nya starter återanvänder aldrig en gammal katalog.

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

Det första testet av denna korrigering använde vanliga filer som nodattrapper.
Det visade att adressbyten syntes, men kunde inte kontrollera faktisk
teckenenhetsåtkomst. Det var otillräckligt: se nästa avsnitt.

## Korrigering av nodev-regression

Nästa hårdvarustart kl. 08:53 misslyckades också. En lokal reproduktion med
`/dev/null` visade att Bubblewrap `--remount-ro` lade till `nodev` och gav
`EACCES` vid öppning, trots föregående `--dev-bind`. Den inställningen har
tagits bort från USB-vägen. Ett nytt regressionstest använder en riktig
teckenenhet (`/dev/null`) och kontrollerar både lyckad öppning och `CapEff=0`.
Sexton tester passerar nu. Hårdvarustarten måste fortfarande verifieras.

Vid start kontrollerar sandboxen synliga teckenenheter genom `open(O_RDWR)`
och omedelbar `close`, utan överföring, reset eller initiering. Lyckad
kontroll ger `USB_OPEN_OK`. Ett fel visas innan leverantörsdaemonen startas.
En privat `/dev/log` samlar högst 24 uppstartsmeddelanden à 1024 byte och
skriver dem som `VENDOR_STARTUP` om daemonstarten misslyckas. Efter readiness
raderas bufferten och fortsatta loggmeddelanden dräneras utan att sparas.

Raden `sensor temporarily absent` kl. 08:53:29 kom från den gamla
städningsloggningen, inte från observerad frånkoppling. Städningen loggas nu
uttryckligen som `cleared during shutdown`.

## Åtkomst nekad före daemonstart kl. 08:59

Den senaste starten misslyckades redan i öppningskontrollen med `EACCES`.
På värden är `/run` monterad med `nodev`, medan `/dev` saknar den flaggan.
Spegeln skapas under `/run`; det tidigare teckenenhetstestet använde `/dev`
som källa och täckte därför inte denna skillnad.

Kör följande diagnostik före ytterligare installation eller daemonstart:

```sh
sudo python3 tools/check_usb_sandbox.py
```

Den skapar tillfälliga privata speglar under både `/run` och `/dev` med
samma rättigheter och mount-argument som tjänsten. Noderna är kopior av
`/dev/null` (1:3), aldrig USB-enheter. Resultatet visar mount-flaggor,
rättigheter och öppningsfel inifrån sandboxen. Tillfälliga filer tas bort
vid normal avslutning och hanterade fel. Ingen tjänst startas om.
Användarens root-test bekräftade att `/run` gav `EACCES` och att `/dev`
gav `open: OK`, båda med uid 0, nodrättighet `0600` och inga capabilities.
Mount-informationen visade `nodev` på den första enhetsmounten men inte på
den andra. Tjänstens spegel har därför flyttats till en temporär privat
katalog under `/dev`, med samma mount-argument som i diagnostiken.
Städning vid normalt avslut och uppstartsfel testas automatiskt.
Installation och ny daemonstart med den riktiga läsaren återstår.

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

## Försvunnen daemon och returkod 54

Ett senare direktförsök gav `EUTHER_RESULT wait_service 54`. Statisk
disassemblering av den installerade wrappern visar att funktionen först
kör `pidof vcsFPService` och sedan väntar på readiness-filen. Båda
väntelooparnas felvägar returnerar 54; det är inte ett svep- eller matchningsfel.
En samtidig processkontroll visade att `vcsFPService` saknades medan
Python-supervisorn fortfarande körde. En kvarlämnad readiness-fil räckte
tidigare för att fortsätta rapportera redo.

Tjänsten kontrollerar nu levande, icke-zombie daemonprocesser vid uppstart,
varje varv i socketloopen (0,5 sekunders accept-timeout) och före ett kommando.
Även under insamling kontrolleras daemonen var 0,2 sekund. Insamlingens
yttersta tidsgräns är fortfarande 35 sekunder. Försvunnen daemon ger `VFS_DAEMON_GONE` och felstatus,
utan automatisk omstart. Vid insamlingsfel loggas endast vitlistade
`EUTHER_STAGE`-namn och numeriska `EUTHER_RESULT`, aldrig fria leverantörsloggar
eller bilddata. Ett processtest verifierar att en kvarlämnad readiness-fil
inte döljer att daemonen dött. Totalt 24 enhetstester passerar.

Den granskade kernelloggen visade endast en äldre `fprint-check`-segfault,
inte en daemonkrasch. Tjänstens cgroup hade noll OOM-händelser. Orsaken till
daemonens försvinnande är ännu inte fastställd. Uppdatera med
`sudo bash tools/install_service.sh` och gör ett guidat försök med
`sudo python3 tools/enroll.py "$USER"`. Granska de nya stegraderna i journalen
vid fel innan ytterligare försök.

Vid försöket kl. 09:49 lyckades `wait_service`, `set_matcher` och
`device_init`, alla med returkod 0. Timeouten kom inne i `vfs_capture`, och
daemonen saknades vid kontrollen efteråt. Den loggen fastställer inte om
daemonen dog före eller efter att hjälparen dödades vid timeout.

Supervisorn är nu en Linux subreaper, så att den kan läsa exitstatus även
för daemonens forkade barn. `VFS_DAEMON_EXIT` rapporterar exitkod eller
signal. `VFS_DAEMON_BEFORE_HELPER_CLEANUP alive=...` visar om daemonen levde
omedelbart innan hjälparens processgrupp städades. Testerna använder en
forkad syntetisk daemon med egen session, kontrollerar att `SIGTERM`
rapporteras och att ett daemonfel avbryter insamling före dess timeout.
Denna diagnostik ändrade inte signalhantering eller vendor-anrop; efterföljande
SIGPIPE-resultat och åtgärd beskrivs nedan.

Den [äldre hjälparens källkod](https://github.com/rindeal/libfprint-vfs_proprietary-driver/blob/4f26cc8c51bd61fda9fcac27c9fa37c9ae54bad2/vfs_proprietary/capture-helper/main.c#L126)
beskriver kommunikationslåsning efter hårt avbruten capture. Det är en möjlig
förklaring till efterföljande fel, inte ett bevis på orsaken till första timeouten.
Se även [Linux subreaper-API](https://man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html).

## Bekräftad SIGPIPE under capture

Kl. 09:56:10 rapporterade den adopterade daemonen `signal=SIGPIPE`, cirka två
sekunder efter capture-start. Före hjälparstädning var daemonen redan borta.
`wait_service`, `set_matcher` och `device_init` hade returnerat 0. Det bekräftar
att den observerade processdöden föregick timeout och hjälparstädning.
Vilken anslutning som bröts är ännu inte fastställt.

Starten av enbart `vcsFPService` använder nu `restore_signals=False`, med en
kontroll att Python-supervisorn ignorerar SIGPIPE. Därmed överlever daemonen
signalen och skrivningen kan returnera `EPIPE`. Detta ändrar inte ett
misslyckat skrivresultat till framgång. Timeout, processövervakning och
bildvalidering gäller fortfarande. Andra subprocesser använder tidigare
signalpolicy. Flaggan bevarar även Pythons övriga ignorerade signaler, såsom
SIGXFSZ, i daemonen; kärnans resursgränser ändras inte.

Ett kompilerat C-test dör av SIGPIPE med standardstarten men får EPIPE och
överlever med den nya daemonstarten. Detta testar exec-arvet; ett Pythonbarn
vore otillräckligt eftersom Python själv ignorerar SIGPIPE. Ändringen har
ännu inte verifierats med riktiga fingersvep och löser inte bevisligen orsaken
till den brutna anslutningen. Ingen skillnad i signalpolicy har belagts mot
den tidigare lyckade bildinsamlingen; detta är en ny kompatibilitetsåtgärd.

Referenser: [Pythons restore_signals](https://docs.python.org/3/library/subprocess.html#subprocess.Popen),
[Linux signalhantering](https://man7.org/linux/man-pages/man7/signal.7.html).

## Avgränsad IPC-spårning efter kvarstående timeout

Kl. 09:59 var daemonen fortfarande levande när capture fick timeout.
SIGPIPE-åtgärden hindrade processdöden men gav ännu ingen bild. Nästa test
spårar IPC-systemanrop från daemonen, dess trådar och capture-hjälparen:

```sh
sudo python3 tools/diagnose_ipc.py "$USER"
```

Skriptet gör en omstart, ansluter strace till enbart daemonen och den inre
supervisorn och kör guiden. Tidsgränsen är fyra minuter och spårningen
begränsas till 10 000 systemanrop. Läs-/skriv-, meddelande- och ioctl-buffertar
visas som råa pekare, aldrig avkodade byte. Inga generella exec-argument eller
USB-payloads dumpas. Öppnade sökvägar, filbeskrivare, anropsnummer och returkoder
är synliga. Spårning kan påverka timing; ett lyckat spårat test måste följas
av verifiering utan spårning.

Rapporterna sparas under `private/ipc-*` (katalog `0700`, filer `0600`) och
överlämnas till sudo-användaren för lokal granskning. De är Git-ignorerade.
Strace kopplas loss efteråt; skriptet ändrar ingen permanent tjänstekonfiguration.
Ingen ytterligare omstart eller nytt försök görs automatiskt.

På denna arbetsstation är Debian strace 6.13+ds-1 redan uppackad under
`build/strace-sdk/root`, utan systeminstallation. Vid ny checkout förbereds den så här:

```sh
mkdir -p build/strace-sdk
cd build/strace-sdk
apt-get download strace=6.13+ds-1
dpkg-deb -x strace_6.13+ds-1_amd64.deb root
cd ../..
python3 tools/diagnose_ipc.py --self-test
```

Skriptet verifierar den körbara filens SHA-256 före omstart. Självtestet
använder syntetiska bytes och en bruten pipe: det kräver synligt EPIPE och
att testpayloaden saknas i spåret. Full anslutning till root-tjänsten återstår
att verifiera med användarens sudo-session. Referens:
[straces raw- och attach-alternativ](https://man7.org/linux/man-pages/man1/strace.1.html).
