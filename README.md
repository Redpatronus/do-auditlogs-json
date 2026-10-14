# DO Audit Scraper

Sťahuje **audit log z DigitalOcean** (Security → History) a priebežne ho zapisuje do súboru
**NDJSON** (jedna JSON udalosť na riadok). Je určený na beh na serveri a ako vstup pre **Wazuh**
(integrácia je ďalšia fáza).

Inšpirované [ionsec/DO-Audit-Log-Scraper](https://github.com/ionsec/DO-Audit-Log-Scraper).

## Ako to funguje

DigitalOcean nemá API na audit logy (API token sem nestačí), dáta sú len vo webovej konzole.
Scraper preto:

1. spustí prehliadač (Playwright / Chromium) a prihlási sa (e-mail + heslo + TOTP kód),
2. otvorí `https://cloud.digitalocean.com/security/history`,
3. zachytí odpovede GraphQL operácie `GetAuditActions`, ktoré si stránka načíta sama (presný čas,
   unikátne ID, akcia, používateľ, IP), a prepína strany tlačidlom „next",
4. zapíše len **nové** udalosti (deduplikácia podľa ID od DigitalOcean).

Prihlásená session (cookies) sa ukladá a opakovane používa, takže sa neprihlasuje pri každom behu.

> Nejde o oficiálne API. Ak DigitalOcean zmení stránku alebo GraphQL, scraper sa bude musieť
> upraviť. Používajte ho len na vlastný účet a podľa podmienok DigitalOcean.

## Požiadavky

- Python **3.11+** (macOS: `brew install python@3.12`; Ubuntu: `apt install python3.12 python3.12-venv`)
- Účet DigitalOcean s prihlásením e-mailom a heslom + 2FA cez **TOTP** (authenticator app).
  Účty cez Google / GitHub SSO nie sú podporované.
- Linux server: balík `xvfb` (virtuálny displej, inštaluje ho `setup.sh`).

Odporúčanie: vytvorte **samostatného člena tímu** s minimálnymi (read-only) právami a vlastným TOTP
secretom, nie osobný owner účet.

## Inštalácia (macOS aj Linux)

```bash
./scripts/setup.sh          # nájde Python >= 3.11, vytvorí .venv, nainštaluje závislosti a Chromium,
                            # na Linuxe aj xvfb, a vytvorí .env (práva 600)
source .venv/bin/activate
make test                   # voliteľné: spustí testy
```

Na Linuxe bez roota spustite po `setup.sh` ešte raz `sudo .venv/bin/playwright install-deps chromium`.

## Nastavenie

Všetko sa nastavuje v súbore `.env` (vzor: `.env.example`), formát `KLÚČ=hodnota`, bez medzier okolo
`=`, bežne bez úvodzoviek. Hodnoty so špeciálnymi znakmi (`#`, `$`) dajte do jednoduchých
úvodzoviek: `DOAL_PASSWORD='ab#c$d'`. Súbor `.env` nikdy necommitujte.

### Prihlasovacie údaje (povinné)

| Premenná | Popis |
|---|---|
| `DOAL_EMAIL` | e-mail účtu DigitalOcean |
| `DOAL_PASSWORD` | heslo |
| `DOAL_TOTP_SECRET` | textový kľúč pod QR kódom pri zapnutí 2FA (písmená A–Z a číslice 2–7). Akceptuje sa aj celé `otpauth://…` URI. **Nie** záložné kódy. |

TOTP secret získate pri zapnutí authenticator app v Account → Security (voľba „can't scan / enter
manually"). Zobrazí sa len raz, preto ho uložte. Záložné (recovery) kódy držte bokom, scraper ich
nepotrebuje.

### Ostatné

| Premenná | Predvolené | Popis |
|---|---|---|
| `DOAL_SESSION_MAX_AGE_DAYS` | `7` | Po koľkých dňoch sa uložená session zahodí a prihlási sa nanovo. |
| `DOAL_SESSION_MAX_AGE_HOURS` | prázdne | To isté v hodinách. **Nastavte iba jedno z týchto dvoch**; keď sú obe prázdne, platí 7 dní. Hodnota nemá presiahnuť dobu platnosti session nastavenú v DigitalOcean. |
| `DOAL_HEADLESS` | `false` | `true` = bez okna. **Headless blokuje Cloudflare**, nechajte `false`. |
| `DOAL_OUTPUT_PATH` | `data/audit_logs.ndjson` | výstupný súbor |
| `DOAL_STATE_PATH` | `data/state.json` | stav deduplikácie (videné ID) |
| `DOAL_STORAGE_STATE_PATH` | `data/storage_state.json` | uložená session (cookies, **tajné**) |
| `DOAL_MAX_PAGES` | `100` | maximum strán na jeden beh (1 strana = 25 udalostí) |
| `DOAL_PAGE_DELAY_S` | `1.5` | pauza medzi stranami; pri chybách (rate limit) zvýšte |
| `DOAL_NAV_TIMEOUT_MS` | `45000` | timeout navigácie |
| `DOAL_LOG_LEVEL` | `INFO` | úroveň logovania |
| `DOAL_LOG_JSON` | `true` | logy ako JSON (na stderr) |

Selektory (`DOAL_TABLE_SELECTOR`, `DOAL_NEXT_BUTTON_SELECTOR` a `DOAL_*_SELECTOR` pre login) sú
nastaviteľné pre prípad, že DigitalOcean zmení stránku.

## Použitie

```bash
source .venv/bin/activate

do-audit login-test --headed   # 1. len test prihlásenia (heslo + TOTP), okno ostane otvorené
do-audit check                 # 2. overí, že session / stránka s logom funguje
do-audit scrape                # 3. stiahne nové udalosti do data/audit_logs.ndjson
```

| Príkaz | Čo robí |
|---|---|
| `do-audit login-test [--headed]` | Čerstvé prihlásenie bez scrapovania. Vypíše `LOGIN OK` alebo `LOGIN FAILED: <dôvod>`. |
| `do-audit check [--headed]` | Overí uloženú session / prihlási sa a otvorí stránku Security History. |
| `do-audit scrape [--headed]` | Stiahne a zapíše nové udalosti. |
| `do-audit login` | Záloha: ručné prihlásenie v okne a uloženie session (ak by automatické prihlásenie zlyhalo). |

`--headed` zobrazí okno prehliadača, hodí sa pri ladení. Skratky: `make check`, `make scrape`.

**Návratové kódy:** `0` OK, `2` prihlásenie/session zlyhali (na toto nastavte alert), iné nenulové
= iná chyba (podrobnosti v logu).

### Opakované spúšťanie (inkrementálne)

Prvý beh stiahne celú históriu. Ďalšie behy načítajú stranu 1 a zapíšu **len udalosti, ktoré ešte
nemajú zaznamenané ID**. Ak je na strane 1 jedna nová udalosť a ostatné staré, zapíše sa jedna.
Keď nie je nič nové, výsledok je `new_events: 0`. Zápis prebehne až po úplnom dokončení behu, takže
chyba uprostred nezanechá v dátach medzeru. Začať odznova: zmažte **spolu** `data/state.json` a
`data/audit_logs.ndjson`.

## Výstup

`data/audit_logs.ndjson`, jedna udalosť na riadok, od najstaršej po najnovšiu:

```json
{"event_id":"01M4TG1KT82GZA05YN9H7JASGE","action":"droplet.create","resource_type":"Droplet","resource_id":"608642988","user":"Alice Example","user_email":"alice@example.com","ip_address":"203.0.113.10","timestamp_utc":"2026-10-13T11:23:26Z","scraped_at":"2026-10-14T08:15:00.123456Z","source":"digitalocean_audit"}
```

Súbor obsahuje mená, e-maily a IP adresy, berte ho ako citlivé dáta.

## Nasadenie na server

**systemd (Ubuntu):**

```bash
sudo useradd -r -m -d /opt/do-audit doaudit
# nahrajte projekt do /opt/do-audit, ako používateľ doaudit spustite ./scripts/setup.sh a upravte .env
sudo cp deploy/do-audit.service deploy/do-audit.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now do-audit.timer       # beh každých 15 minút
systemctl list-timers do-audit.timer
journalctl -u do-audit.service -f                # logy
```

Server nemá displej, preto scraper sám spustí virtuálny (Xvfb) a v ňom bežný, nie headless, Chromium.
Cloudflare môže výzvu zopakovať pre IP adresu datacentra, ostrý beh treba overiť priamo na serveri.

**Docker:** `docker build -t do-audit .` a potom
`docker run --rm --env-file .env -v $PWD/data:/data do-audit scrape`.

## Bezpečnosť

- `.env` (heslo, TOTP secret) a `data/storage_state.json` (cookies = prístup k účtu bez hesla)
  chráňte: práva `600`, vlastník len používateľ služby, nikdy v gite. `.gitignore` ich vynecháva.
- Heslo aj TOTP secret ležia na jednom serveri, takže 2FA je tam prakticky jednofaktorová. Preto
  samostatný read-only účet a krátky `DOAL_SESSION_MAX_AGE_*`.
- Pri úniku zmeňte heslo a obnovte 2FA v DigitalOcean.
- Súbory v `data/debug/` (screenshoty, HTML) môžu obsahovať e-maily, nezdieľajte ich.

## Riešenie problémov

| Príznak | Príčina / riešenie |
|---|---|
| `missing/empty: DOAL_…` | prázdna hodnota v `.env`; `do-audit` spúšťajte z koreňa projektu, odkiaľ sa `.env` číta |
| `DOAL_TOTP_SECRET is not valid base32` | zlý kľúč; treba textový kľúč pod QR kódom (A–Z, 2–7), nie kód z aplikácie ani záložný kód |
| `Cloudflare bot challenge…` | headless režim; nastavte `DOAL_HEADLESS=false` (na serveri Xvfb). Ak výzvu dostanete aj tak, použite `do-audit login` a session skopírujte |
| `2FA code not accepted twice` | zlý secret alebo nepresný čas systému |
| `audit_graphql_error` / `next_page_retry` | dočasná chyba alebo rate limit; zvýšte `DOAL_PAGE_DELAY_S` |
| `audit table not found` / `no valid GetAuditActions response` | zmenila sa stránka; pozrite `data/debug/*.png` a `.html` a upravte selektory |
| `cannot start Xvfb` | `sudo apt install xvfb` |

## Štruktúra projektu

```
src/do_audit_scraper/
  config.py    nastavenia (DOAL_*)         parser.py   GraphQL odpoveď → AuditEvent
  browser.py   Playwright, login, strany   storage.py  NDJSON + dedup stav
  scraper.py   inkrementálny beh           cli.py      príkazy do-audit
  models.py    AuditEvent
deploy/        systemd service + timer     scripts/    setup.sh
tests/         testy (pytest)              Dockerfile, Makefile, pyproject.toml
```

## Vývoj

```bash
make test        # pytest
make lint        # ruff
```

## Plán

- Fáza 2: integrácia do **Wazuh** (`localfile` s `log_format json`, decodery a pravidlá).
- Voliteľne: doplnkový kolektor cez oficiálne API (`/v2/actions`) s read-only tokenom.
