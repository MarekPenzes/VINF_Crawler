# Diagram architektúry

- **1-2: crawler** (fáza 1)
- **3-4: Spark, wiki dump a join** (fáza 3)

Architektúra crawlera je inšpirovaná článkom
[HelloInterview - Web Crawler](https://www.hellointerview.com/learn/system-design/problem-breakdowns/web-crawler).
Je zmenšená na jeden proces a jednu doménu (worldfootball.com).

**Rozhranie systému:**
- **Vstup:** seed URL (hráč, tím a 5 líg).
- **Výstup:** HTML stránky hráčov s tabuľkou štatistík v `data/html/` (bio nie je podmienka, text doplní wiki).

## 1. Architektúra crawlera

```mermaid
flowchart LR
    SEEDS["Seed URLs<br/>Saka, Arsenal, 5 líg"]
    FRONTIER["URL Frontier<br/>fronty: hráči, tímy, ligy<br/>náhodný výber"]
    FETCHER["URL Fetcher (curl_cffi ako Chrome)<br/>sleep 2-3 s, timeout 20 s<br/>blok → retry na konci"]
    WEB[("worldfootball.com")]
    PARSER["Parser (regex)<br/>odkazy + dedup"]
    FILTER{"hráč s tabuľkou<br/>štatistík?"}
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
    I -- "hráč" --> J{"má tabuľku<br/>štatistík?"}
    J -- "áno" --> L["uložiť data/html/id_slug.html<br/>saved++"]
    J -- "nie" --> M["preskočiť<br/>skipped++"]
    L --> N{"saved >= target?"}
    K --> N
    M --> N
    F --> N
    N -- "nie" --> O["každých 10 stránok ulož state.json<br/>sleep 2-3 s"] --> A
    N -- "áno" --> P["koniec, ulož state.json"]
```

## 3. Spark pipeline

Spark beží lokálne (`local[*]`, 8 vlákien). Nadpis bloku je príkaz a súbor s kódom.

```mermaid
flowchart TD
    subgraph EX["py main.py spark-extract (spark_extract.py)"]
        direction LR
        HTML[("data/html/<br/>18 823 HTML")] --> EXT["regex extraktor<br/>16 partícií"] --> PT[("players.tsv<br/>career.tsv")]
    end

    subgraph WK["py main.py wiki (wiki_extract.py, parser wikitext.py)"]
        DUMP[("enwiki dump<br/>24 GB bz2")] --> READ["čítanie po stránkach<br/>bz2 bloky paralelne"]
        READ --> JVM{"filter v JVM:<br/>článok (ns 0) s infoboxom<br/>football biography?"}
        JVM -- "nie" --> DROP["zahodiť"]
        JVM -- "áno" --> PARTS[("data/wiki/football/<br/>215 561 stránok, 1,8 GB")]
        PARTS --> PARSE["regex parser<br/>infobox, dátum, výška, kariéra,<br/>reprezentácia, Career total,<br/>úvodný text, kategórie"]
        PARSE --> DEDUP["duplicity podľa id stránky<br/>reduceByKey"] --> WT[("wiki_players.tsv<br/>215 561 hráčov")]
    end

    subgraph JN["py main.py join (wiki_join.py)"]
        JOIN["páry: join na dátume narodenia<br/>+ porovnanie mien"] --> FULL["full outer join<br/>hráči + páry + wiki stránky"]
        FULL --> JT[("joined.tsv, 221 912 riadkov<br/>12 477 z oboch zdrojov<br/>6 346 iba worldfootball<br/>203 089 iba wiki")]
    end

    PT --> JOIN
    WT --> JOIN
```

## 4. Join hráčov s wiki

worldfootball nemá odkaz na Wikipédiu, samotné meno nestačí (menovci, mononymy, iný prepis).
Kľúčom páru je dátum narodenia a na dvojiciach s rovnakým dátumom sa porovnajú mená.
Nakoniec full outer join, aby sa nestratil žiadny hráč ani wiki stránka.

```mermaid
flowchart TD
    P[("players.tsv<br/>18 593 s dátumom narodenia")] --> EQ
    W[("wiki_players.tsv<br/>208 206 s dátumom narodenia")] --> EQ
    EQ["equi-join na birth_date<br/>(Spark SQL)"] --> S["name_score (Python UDF)<br/>tokeny bez diakritiky a častíc<br/>presne alebo podobný prepis (difflib)"]
    S --> C{"sedia aspoň 2 tokeny?<br/>(mononym: presne)"}
    C -- "nie" --> X["iná osoba<br/>Paul Martin / John Martin"]
    C -- "áno" --> PAIRS["12 501 dvojíc<br/>skóre = priemerná podobnosť"]
    PAIRS --> B1["pre hráča najvyššie skóre<br/>remíza = vynechať"]
    B1 --> B2["pre stránku najvyššie skóre<br/>remíza = vynechať,<br/>okrem skóre 1 (duplicitný profil)"]
    B2 --> M["páry hráč - stránka<br/>12 477 hráčov, 12 472 stránok"]
    M --> L["left join so všetkými hráčmi<br/>(hráč bez páru: wiki stĺpce prázdne)"]
    P --> L
    L --> FO["full outer join na wiki_id<br/>(+ wiki stránky bez hráča)"]
    W --> FO
    FO --> J[("joined.tsv, 221 912 riadkov<br/>source: both 12 477,<br/>worldfootball 6 346, wiki 203 089")]
```