# Anytime - Gym busy meter Bridge

Zet de live drukte van Anytime Fitness-clubs als sensoren in Home Assistant.

De bridge start de onofficiële [af-unofficial-mcp-server](https://github.com/Sajush00/af-unofficial-mcp-server)
(gebruikt de privé-API van de AF-app, kan zonder waarschuwing veranderen), vraagt
elke `AF_INTERVAL` seconden de bezetting op en pusht die via de HA REST API.

## Sensoren

| Entiteit | Waarde | Belangrijkste attributen |
|---|---|---|
| `sensor.af_drukte` | aantal mensen nu | `club`, `typical_count`, `ratio`, `verdict`, `verdict_message`, `rest_of_day` |
| `sensor.af_drukte_normaal` | gebruikelijk aantal dit uur | |
| `sensor.af_drukte_advies` | `go` / `wait` / `skip` | `message` |

Extra clubs via `AF_CLUBS` krijgen eigen sensoren, bv. `sensor.af_drukte_nl_1001`.

Let op: deze sensoren staan **niet** onder Instellingen → Entiteiten (geen unique_id),
wel onder **Ontwikkelaarshulpmiddelen → Toestanden**. Na een HA-herstart zijn ze
maximaal één interval "onbekend".

## Installatie

1. **Repo op de server zetten**
   - Komodo: maak een Stack in modus *Git Repo* met deze repo, of clone naar
     `/etc/komodo/repos/main/af-bridge` en gebruik *Files on Server*.
     De map moet binnen het bereik van Periphery liggen (`/etc/komodo/...`),
     anders krijg je `Failed to validate run directory ... No such file or directory`.
   - Zonder Komodo: `git clone` en verder in die map werken.

2. **Variabelen** (zie `.env.example`): `AF_HA_URL`, `AF_HA_TOKEN`, `AF_INTERVAL`, `AF_CLUBS`.
   Zet ze in `.env` naast `compose.yaml` of in je globale env van Komodo.
   - Gebruik het **IP-adres** van HA, geen `.local`-naam.
   - Het token moet van een **beheerder** zijn (Profiel → Beveiliging → Long-lived access tokens).
   - Elke variabele op een eigen regel; een token is ±183 tekens.

3. **Bouwen**
   ```
   docker compose build
   ```

4. **Eenmalig inloggen bij Anytime Fitness** (sms-code naar het telefoonnummer van je AF-account):
   ```
   docker compose run --rm af-bridge /app/af/.venv/bin/af-gym login --phone +316XXXXXXXX
   ```
   Het token komt in `/var/docker/af-bridge` en blijft bewaard bij updates.

5. **Testen zonder naar HA te sturen**
   ```
   docker compose run --rm af-bridge /app/af/.venv/bin/python /app/bridge.py --test
   ```
   Je hoort JSON te zien met o.a. `currentMemberCount`, `typicalCount` en `restOfDay`.

6. **Starten**: `docker compose up -d` (of Deploy in Komodo; na wijzigingen in
   `bridge.py`/`Dockerfile` deployen met `--build`).

De eerste logregel toont `HA_URL=..., tokenlengte=183`. Daarna per poll bv.
`sensor.af_drukte = 11 (normaal 6, skip)`.

## Problemen oplossen

| Log | Oorzaak / oplossing |
|---|---|
| `HA antwoordde 401 ... token ongeldig` | Token fout of ingetrokken. Snel vervangen, anders blokkeert HA het IP. |
| `HA antwoordde 403` | Het IP van de server staat in HA's `ip_bans.yaml`, of het token is van een niet-beheerder. Verwijder de ban en **herstart HA**. |
| `ConnectError` | `AF_HA_URL` niet bereikbaar vanuit de container. |
| `HA_URL en HA_TOKEN moeten gezet zijn` | Variabelen komen de container niet in. |
| `ophalen bij AF mislukt` | AF-sessie verlopen (opnieuw stap 4) of de app-API is veranderd. |

Snelle test van token en IP vanuit de container (verwacht `200 {"message":"API running."}`):
```
docker exec af-bridge /app/af/.venv/bin/python -c "import os,httpx; r=httpx.get(os.environ['AF_HA_URL']+'/api/', headers={'Authorization':'Bearer '+os.environ['AF_HA_TOKEN']}); print(r.status_code, r.text)"
```

## Dashboard

Markdown-kaart met advies, nu-vs-normaal en verwachting per uur:
[`dashboard/af-drukte-card.yaml`](dashboard/af-drukte-card.yaml).

## Onafhankelijk blijven van het originele project

De `Dockerfile` bouwt vanaf een vaste commit van de upstream repo. Fork die repo
op GitHub en zet je fork als bron, dan kun je blijven bouwen als het origineel
verdwijnt:
```
docker compose build --build-arg AF_REPO=https://github.com/JOUWNAAM/af-unofficial-mcp-server.git
```
of pas de standaardwaarde van `AF_REPO` in de `Dockerfile` aan.
