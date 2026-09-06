# Handoff – System Regis IV / SDDM

Uppdaterad 2026-09-06. Börja här efter omstart eller vid nästa arbetspass.

## Nuvarande läge

Regis-temat och fingerautentisering för SDDM är **installerade på
utvecklingsdatorn**, HP ProBook 4340s med Debian 13.6 och
SDDM `0.21.0+git20250502.4fe234b-2`.
Användaren godkände förhandsvisningen och därefter installationen.
**Verklig inloggning genom SDDM är ännu inte bekräftad.** Ingen omstart eller
utloggning utfördes under installationen.

- Läsaren är Validity VFS491 (`138a:003d`). fprintd hittade Euther-enheten
  och fyra registrerade fingrar för det lokala kontot vid kontrollen.
- `/usr/share/sddm/themes/regis` innehåller åtta root-ägda filer, läge 0644.
  Filinnehållet kontrollerades byte för byte. `Preview.qml` är inte installerad.
- `/etc/sddm.conf` väljer `Current=regis` och
  `ThemeDir=/usr/share/sddm/themes` under `[Theme]`.
- `/etc/pam.d/sddm` använder `pam_fprintd.so max-tries=1 timeout=15`
  som `sufficient` före `common-auth`, efter nologin- och root-spärrarna.
  `common-auth` är oförändrad. Lösenordsreserv och kontokontroller finns kvar.
- SDDM och Euther-tjänsten var fortsatt aktiva efter installationen.

## Nästa steg – riktigt inloggningsprov

1. Spara allt arbete och starta om datorn när användaren är redo. SDDM läser
   huvudkonfigurationen vid uppstart; enbart utloggning räcker inte säkert
   för att ladda det nya temavalet.
2. Kontrollera att Regis visas. Välj rätt konto och skrivbordssession.
3. Tryck **Logga in med fingeravtryck** och svep ett registrerat finger
   vid läsarens uppmaning. Bekräfta att skrivbordet faktiskt öppnas.
4. Vid ett separat inloggningsprov, ange lösenord och använd
   **Logga in med lösenord**, utan att svepa. Det kan ta cirka 15 sekunder
   extra eftersom PAM provar fingerkontrollen först.
5. Prova därefter fel finger och uteblivet svep. Avbryt felsökningen vid
   oväntade fel och granska loggen före upprepade försök.

Starta inte läsarprov i agentens osynliga terminal utan att samordna med
användaren. Be aldrig om lösenord eller biometriska data i chatten.

Efter ett misslyckat prov, samla lokalt:

```sh
systemctl status sddm eutherfpscan fprintd --no-pager
sudo journalctl -b -u sddm -u eutherfpscan -u fprintd -n 100 --no-pager
```

fprintd kan avslutas normalt när den är inaktiv. Det är inte i sig ett fel.
Dokumentera vad användaren såg, om skrivbordet öppnades och om lösenordet
fungerade. Granska loggar innan eventuella utdrag läggs i Git.

## Återställning om inloggningen strular

Byt till TTY med **Ctrl+Alt+F3** och logga in med ditt vanliga konto.
Från denna dator:

```sh
cd /home/nichlase/EutherFPScan
sudo python3 tools/install_sddm.py --remove
```

Skriptet återställer både SDDM-konfigurationen och PAM. Starta därefter om
datorn när allt arbete är sparat för att ladda föregående tema.
Säkerhetskopior finns root-skyddade på datorn:

- `/var/lib/eutherfpscan/sddm.conf.backup`
- `/var/lib/eutherfpscan/pam-sddm.backup`

Återställningen vägrar skriva över filer som ändrats efter installationen.
Inaktiva temafiler behålls. Fingeravtryck och sudo-inställningar ändras inte.
Om skriptet stoppar: granska skillnaderna och säkerhetskopiorna innan ändring.

## Kod, tester och begränsningar

- [docs/sddm.md](docs/sddm.md): granskning, installation, begränsningar och källor.
- `sddm/regis/`: riktigt SDDM-tema samt separat demo.
- `tools/preview_sddm.py`: säker demo; resultaten är simulerade.
- `tools/install_sddm.py`: gemensam installation, kontroll och återställning.
- `tools/install_sddm_pam.py`: separat PAM-hjälpare.
- `tests/test_sddm*.py`: PAM-flöden, konfigurationsdrift och återställning.

Senaste `make test`: **30 tester godkända**. Det installerade temat laddades
utan QML-fel i SDDM:s testläge. Användaren bekräftade den interaktiva demon.
Detta ersätter inte verkliga inloggningsprov.

SDDM-versionen saknar tema-API för parallella metoder och omedelbar
avbrytning. PAM-meddelanden visas, men fel kan signaleras före slutresultatet;
återförsök efter sådana fel återstår att prova. KWallet kan behöva lösenord
separat. Skärmlås och diskkryptering ingår inte i denna ändring.

Git innehåller källkod och instruktioner. Installerade systemfiler,
säkerhetskopior, fingeravtrycksmallar och innehållet i `build/`, `private/`
och `captures/` följer inte med en klon. Installationsskripten är avsiktligt
bundna till granskade originalkonfigurationer på denna dator; kör dem inte
blint på en annan installation.
