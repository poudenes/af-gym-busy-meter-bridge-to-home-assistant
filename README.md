# Anytime Fitness Drukte voor Home Assistant

Zet de live drukte van Anytime Fitness-clubs als sensoren in Home Assistant.
Een custom integration, installeerbaar via HACS.

> Gebruikt de onofficiële privé-API van de AF-app (gebaseerd op
> [af-unofficial-mcp-server](https://github.com/Sajush00/af-unofficial-mcp-server), MIT).
> Die API kan zonder waarschuwing veranderen.

## Installatie via HACS

1. HACS → menu (⋮) → **Custom repositories**
   - Repository: `https://github.com/poudenes/af-gym-busy-meter-bridge-to-home-assistant`
   - Type: **Integration**
2. Zoek **Anytime Fitness Drukte**, installeer en **herstart Home Assistant**.
3. Instellingen → Apparaten & diensten → **Integratie toevoegen** → *Anytime Fitness Drukte*.
4. Vul het telefoonnummer van je AF-account in (`06…` mag, dat wordt `+316…`) en daarna de sms-code.

Handmatig kan ook: kopieer `custom_components/af_drukte` naar `config/custom_components/` en herstart.

## Sensoren

Per club komt er een apparaat met drie sensoren. De entity_id's zijn gelijk aan die van de vroegere Docker-bridge, dus bestaande dashboards blijven werken.

| Entiteit | Waarde | Attributen |
|---|---|---|
| `sensor.af_drukte` | aantal mensen nu | `club`, `af_number`, `typical_count`, `ratio`, `verdict`, `verdict_message`, `rest_of_day`, `updated` |
| `sensor.af_drukte_normaal` | gebruikelijk aantal dit uur | |
| `sensor.af_drukte_advies` | `go-now` / `good-time` / `normal` / `wait` / `skip` (of `no-live-data` / `no-baseline`) | `message` |

Extra clubs krijgen eigen sensoren, bv. `sensor.af_drukte_nl_1001`.

Het advies vergelijkt het live aantal met het gebruikelijke aantal voor dit uur:
≤ 50 % `go-now`, ≤ 85 % `good-time`, ≤ 115 % `normal`, ≤ 150 % `wait`, daarboven `skip`.
Het uur wordt bepaald met de tijdzone van Home Assistant.

## Opties

Instellingen → Apparaten & diensten → Anytime Fitness Drukte → **Configureren**:

- **Extra clubs**: kies uit de clubs binnen 25 km van je thuisclub, of typ een clubnummer (bv. `NL-1001`).
- **Interval**: hoe vaak de drukte wordt opgehaald (standaard 300 s, minimaal 60 s).

## Sessie verlopen

De integratie ververst het AF-token zelf. Verloopt de sessie toch, dan krijg je in Home Assistant een melding
**Opnieuw configureren**. Je krijgt dan een nieuwe sms-code en daarna draait alles weer.

## Dashboard

Markdown-kaart met advies, nu-vs-normaal en verwachting per uur: [`af-drukte-card.yaml`](af-drukte-card.yaml).

## Overstappen van de Docker-bridge

Gebruikte je eerder de Docker-bridge uit deze repo? Installeer dan de integratie, stop de container
en trek het long-lived access token in dat de bridge gebruikte (Profiel → Beveiliging).
De oude bridge staat nog in de git-geschiedenis (tag `docker-bridge`).

## Ontwikkelen

```
pip install pytest-homeassistant-custom-component
python -m pytest
```

## Nieuwe versie uitbrengen

1. Verhoog `version` in `custom_components/af_drukte/manifest.json` (bv. `1.0.1`).
2. Commit en push.
3. Maak een GitHub-release met tag `v1.0.1`. HACS ziet die release als update.
