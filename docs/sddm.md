# System Regis IV för SDDM

En första QML-version av inloggningsskärmen är byggd i samma mörkblå och
guldfärgade stil som registerappen. Den har användarval med manuell inmatning,
sessionsval, fingerknapp, lösenordsfält och visning av SDDM:s PAM-meddelanden.

## Förhandsvisa

```sh
python3 tools/preview_sddm.py
python3 tools/preview_sddm.py --screenshot build/sddm-preview.png
```

Förhandsvisningen använder den installerade `sddm-greeter-qt6` i testläge
och en separat demokomponent. Ingen systemkonfiguration ändras, inga
fingeravtryck läses och inga inloggningar utförs. Skriv inte ditt riktiga
lösenord i demon. Välj ett simulerat resultat längst ned, tryck på
fingerknappen och använd **Börja om** för nästa prov.

`sddm/regis/Main.qml` är det riktiga temat och använder SDDM:s `login()` och
dess signaler. `Preview.qml` används enbart av demonstrationsverktyget.
Temat har fingerknappen avstängd som standard tills PAM-integrationen är
installerad och provad.

## Vad denna SDDM-version kan göra

Lokalt verifierat 2026-09-06: Debian 13.6, HP ProBook 4340s, USB `138a:003d`,
SDDM `0.21.0+git20250502.4fe234b-2`. fprintd:s Euther-drop-in finns installerad.
Varken `/etc/pam.d/sddm` eller dess `common-auth` aktiverade fingeravtryck.
Tidigare riktiga fingersvep och sudo-resultat finns i [libfprint.md](libfprint.md);
inga nya hårdvaruprov gjordes under temabygget.

Den granskade upstream-koden vid `4fe234b` visar:

- `GreeterProxy::login(user, password, session)` startar en autentisering.
  Temat kan inte välja en separat PAM-tjänst eller avbryta ett pågående försök.
- `informationMessage` förmedlar PAM:s informations- och felmeddelanden.
  Temat visar texten som vanlig text, utan att tolka den som HTML eller
  dra slutsatsen att en fingerträff innebär färdig inloggning.
- `Display::startAuth()` avvisar nya försök medan ett annat är aktivt.
  `slotRequestChanged()` svarar med lösenordet som skickades vid start;
  det går inte att lägga till ett lösenord halvvägs genom försöket från temat.
- `loginSucceeded` används för godkänd inloggning. Fel visas generellt:
  de kan bero på annat än att fingret inte matchar.

Första integrationen använder därför **finger först, lösenord därefter**.
Fingerknappen skickar tomt lösenord och startar PAM. Vid utebliven träff
misslyckas försöket normalt när lösenordssteget också misslyckas.
Användaren kan därefter göra ett nytt försök med lösenord. Den knappen skickar
lösenordet från början, men PAM gör fortfarande fingerkontrollen först.
Väntan är cirka 15 sekunder plus eventuell annan PAM-fördröjning.
Inget automatiskt upprepat försök eller falsk avbrytknapp finns.

Omedelbar växling eller parallella metoder kräver arbete i SDDM:s backend och
kommunikationsprotokoll, utöver temat. Denna version gör inga sådana ändringar.

## Förberedd PAM-ändring

Förhandsgranska den exakta diffen:

```sh
python3 tools/install_sddm_pam.py
```

Skriptet lägger följande före `common-auth`, **efter** befintlig `pam_nologin`
och spärren mot root-inloggning:

```pam
auth sufficient pam_fprintd.so max-tries=1 timeout=15
```

Det kontrollerar SHA-256 för de granskade originalfilerna, sparar en
root-skyddad säkerhetskopia i `/var/lib/eutherfpscan/pam-sddm.backup` och
ersätter endast SDDM:s PAM-fil atomiskt. `common-auth` ändras inte.
Ändrade original eller en avvikande säkerhetskopia stoppar installationen.

Aktivering är ett separat steg inför ett överenskommet inloggningsprov:

```sh
sudo python3 tools/install_sddm_pam.py --apply
```

Återställning från en terminal eller TTY:

```sh
sudo python3 tools/install_sddm_pam.py --remove
```

Skriptet vägrar skriva över PAM-filen om den ändrats efter installationen.
Ingen omstart av SDDM utförs av skriptet.

## Nästa steg inför aktivering

### Gemensam installation och återställning

`tools/install_sddm.py` installerar nu temat och PAM tillsammans. Det sparar
även originalet av `/etc/sddm.conf` i
`/var/lib/eutherfpscan/sddm.conf.backup`. För denna granskade konfiguration
läggs `[Theme] Current=regis` och den explicita temakatalogen till i huvudfilen,
som har företräde framför fragment. Den befintliga Autologin-sektionen lämnas kvar.

```sh
python3 tools/install_sddm.py
sudo python3 tools/install_sddm.py --apply
```

Temat installeras först som root-ägda filer (utan demokomponenten), sedan PAM,
och sist aktiveras temavalet. Ett fel vid aktiveringen återställer de kända
konfigurationsändringarna från försöket. Avvikande originalfiler stoppar skriptet.
Ingen tjänst startas om och ingen utloggning utförs.

Återställ **både temaval och PAM** från en terminal eller TTY:

```sh
sudo python3 /home/nichlase/EutherFPScan/tools/install_sddm.py --remove
```

Temafilerna behålls inaktiva. Återställningen vägrar skriva över
konfigurationsfiler som ändrats utanför installationen.
Ytterligare två isolerade tester verifierar konfigurationsdrift, installation,
återställning och återställning av PAM efter ett simulerat aktiveringsfel.

1. Prova den visuella demon och kontrollera tangentbordsnavigeringen.
2. Bekräfta läsarens nuvarande funktion med ett överenskommet fingersvep.
3. Behåll en inloggad terminal/TTY och kontrollera lösenordsinloggning där.
4. Kör den gemensamma installationen ovan.
5. Läs tillbaka PAM, SDDM-konfigurationen och temafilerna innan utloggning.
6. Prova efter en planerad omstart: rätt finger, fel finger, ingen svepning följt
   av lösenord, och frånvarande läsare. Starta inte om SDDM under pågående arbete.

KWallet kan behöva lösenord separat: fingerinloggningen ger inget lösenord
till dess PAM-modul. Skärmlås, diskkryptering och sudo styrs separat.
Den första temaversionen saknar skärmtangentbord, layoutväljare och strömknappar;
den ska granskas på datorns riktiga skärm innan den ersätter Breeze.

## Verifiering och kvarvarande begränsningar

2026-09-06: `make test` gav **28 godkända tester**. Nya tester använder riktig
libpam med privata konfigurationsfiler och syntetiska modulresultat: träff,
misslyckat finger, otillgänglig modul, lösenordsreserv, avvisning av båda
metoderna, nekad kontokontroll, spärrad root och global inloggningsspärr.
Originalets root-villkor testas med riktig `pam_succeed_if`. Fingerläsaren och
systemets PAM-filer används inte av testerna. Testerna kräver en miljö där
PAM:s systemanrop tillåts; sandlådan gav PAM_SYSTEM_ERR även i befintliga tester.

Produktionskomponenten laddades utan QML-fel i SDDM:s testläge. Demons PNG
renderades med Qt:s mjukvarurenderare och granskades visuellt. Dessa kontroller
bekräftar inte verklig autentisering, tjänsternas uppstart vid boot, KWallet
eller hur läsarens felmeddelanden samspelar med SDDM:s signaler. Särskilt
PAM-fel kan ge `loginFailed` före det slutliga resultatet; återförsök efter
sådana fel behöver provas på riktigt före dagligt bruk.

Källor:

- [SDDM:s tema-API vid 4fe234b](https://github.com/sddm/sddm/blob/4fe234b/docs/THEMING.md)
- [GreeterProxy.h](https://github.com/sddm/sddm/blob/4fe234b/src/greeter/GreeterProxy.h)
- [Display.cpp](https://github.com/sddm/sddm/blob/4fe234b/src/daemon/Display.cpp)
- [Debians pam_fprintd](https://manpages.debian.org/trixie/libpam-fprintd/pam_fprintd.8.en.html)

## Installerat 2026-09-06

Användaren provade och godkände demon och godkände därefter aktivering.
Den gemensamma installationen kördes med sudo i en synlig terminal och gav
`REGIS_INSTALL_OK`. Installationsutskriften finns i `build/sddm-install.log`.
Alla åtta installerade temafiler lästes tillbaka byte för byte och hade
root som ägare samt läge 0644; demokomponenten är inte installerad.
SDDM-konfigurationen och PAM motsvarade exakt de föreslagna ändringarna.
Det installerade temat laddades utan QML-fel i SDDM:s testläge.
De fyra riktade PAM/installations-testerna passerade efter tillägget.

**Starta om datorn när allt arbete är sparat inför det riktiga provet.**
SDDM läser huvudkonfigurationen vid uppstart, så enbart utloggning är inte
ett säkert sätt att ladda det nya temavalet. Ingen omstart utfördes här.
SDDM och Euther-tjänsten var fortsatt aktiva efter installationen.

Prova fingerknappen med ett registrerat finger. Prova sedan lösenordsreserven
utan att svepa; fingerkontrollen kan lägga till cirka 15 sekunders väntan.
Om greeter-temat inte fungerar: byt till TTY med Ctrl+Alt+F3, logga in och
kör återställningskommandot ovan. Starta sedan om datorn för att återgå till
föregående temaval. Verklig SDDM-inloggning och lösenordsreserv är ännu inte
bekräftade.

Källkod för konfigurationsinläsningen:
[ConfigReader.h](https://github.com/sddm/sddm/blob/4fe234b/src/common/ConfigReader.h)
och [Display.cpp](https://github.com/sddm/sddm/blob/4fe234b/src/daemon/Display.cpp).
