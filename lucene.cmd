@echo off
rem Spusti prikaz main.py v Docker kontajneri s PyLucene (PyLucene nema balik pre Windows).
rem Priecinok projektu sa pripoji ako /app, data aj index ostavaju na disku v data/.
rem Pouzitie: lucene.cmd lucene-index
rem           lucene.cmd lucene-serve     (server pre vyhladavanie, koniec Ctrl+C)
rem           lucene.cmd lucene-compare
rem           lucene.cmd test
rem Vyhladavanie ide cez server, filtre s < a > by cmd v tomto subore bral ako presmerovanie:
rem           py main.py search goalkeeper "height>=195" --index lucene
setlocal
set PORTS=
rem port ako LUCENE_PORT v config.py, dostupny iba z tohto PC (127.0.0.1)
if /i "%~1"=="lucene-serve" set PORTS=-p 127.0.0.1:8765:8765
docker run --rm --init %PORTS% -e PYTHONUNBUFFERED=1 -e PYTHONDONTWRITEBYTECODE=1 -v "%~dp0.:/app" -w /app coady/pylucene:10.0.0 python main.py %*
