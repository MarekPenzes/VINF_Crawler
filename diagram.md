# Diagram architektúry crawlera

Architektúra je inšpirovaná článkom
[HelloInterview - Web Crawler](https://www.hellointerview.com/learn/system-design/problem-breakdowns/web-crawler).
Je zmenšená na jeden proces a jednu doménu (worldfootball.com).

**Rozhranie systému:**
- **Vstup:** seed URL (hráč, tím a 5 líg).
- **Výstup:** HTML stránky hráčov s bio a tabuľkou štatistík v `data/html/`.

## 1. Architektúra

```mermaid
flowchart LR
    SEEDS["Seed URLs<br/>Saka, Arsenal, 5 líg"]
    FRONTIER["URL Frontier<br/>fronty: hráči, tímy, ligy<br/>náhodný výber"]
    FETCHER["URL Fetcher (curl_cffi ako Chrome)<br/>sleep 2-3 s, timeout 20 s<br/>blok → retry na konci"]
    WEB[("worldfootball.com")]
    PARSER["Parser (regex)<br/>odkazy + dedup"]
    FILTER{"hráč s bio<br/>a štatistikami?"}
    HTML[("data/html/<br/>stránky hráčov")]
    STATE[("state.json<br/>stav crawlu")]

    SEEDS --> FRONTIER --> FETCHER
    FETCHER <--> WEB
    FETCHER --> PARSER
    PARSER -- nové URL --> FRONTIER
    PARSER --> FILTER
    FILTER -- áno --> HTML
    FRONTIER <-.->|uloženie / pokračovanie| STATE
```

## 2. Spracovanie jednej stránky

```mermaid
flowchart TD
    A["next(): vyber URL z fronty<br/>prázdne fronty → neúspešné URL z logu"] --> C["HTTP GET, timeout 20 s<br/>1 pokus"]
    C --> G["zápis do crawl_log.tsv<br/>status, typ, veľkosť, čas, URL"]
    G --> D{"status?"}
    D -- "403 / 429 / 5xx / timeout<br/>alebo challenge = CF" --> F["chyba, URL ostane v logu<br/>→ retry na konci<br/>pauza 10 / 30 / 60 / 120 s"]
    D -- "200 OK" --> H["vytiahni všetky odkazy<br/>pridaj nové do front"]
    H --> I{"typ stránky?"}
    I -- "tím / liga" --> K["iba zdroj odkazov<br/>neukladá sa"]
    I -- "hráč" --> J{"má bio AND<br/>tabuľku štatistík?"}
    J -- "áno" --> L["uložiť data/html/id_slug.html<br/>saved++"]
    J -- "nie" --> M["preskočiť<br/>skipped++"]
    L --> N{"saved >= target?"}
    K --> N
    M --> N
    F --> N
    N -- "nie" --> O["každých 10 stránok ulož state.json<br/>sleep 2-3 s"] --> A
    N -- "áno" --> P["koniec, ulož state.json"]
```