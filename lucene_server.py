"""Vyhladavaci server nad Lucene indexom. JVM a index sa otvoria raz pri starte, kazdy dalsi dopyt
potom trva milisekundy namiesto noveho kontajnera a JVM pri kazdom vyhladavani (5-10 s).

Spustenie v Docker kontajneri: lucene.cmd lucene-serve (koniec Ctrl+C)
Dopyty z Windows:              py main.py search goalkeeper "height>=195" --index lucene
Pred novym lucene.cmd lucene-index treba server zastavit, drzi otvorene subory indexu.

API: POST /search, telo JSON {"text": "goalkeeper", "filters": ["height>=195"], "top": 10}
     -> 200 {"total": pocet, "results": [[skore, popis hraca], ...]}, pri chybe 400 {"error": "..."}"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import LUCENE_PORT
from filters import FilterError, parse_filter
from lucene_search import LuceneEngine, QueryError

# v kontajneri sa musi pocuvat na vsetkych rozhraniach, inak Docker port neprepoji;
# lucene.cmd ho na hostitelovi zverejni iba na 127.0.0.1, z inych PC v sieti dostupny nie je
HOST = "0.0.0.0"


class SearchHandler(BaseHTTPRequestHandler):
    """Jeden HTTP dopyt -> LuceneEngine.answer(); engine je v self.server.engine."""

    def do_POST(self):
        if self.path != "/search":
            self.reply(404, {"error": f"neznama cesta {self.path}"})
            return
        start = time.perf_counter()
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            text, raw_filters = request["text"], request["filters"]
            filters = [parse_filter(arg) for arg in raw_filters]
            total, rows = self.server.engine.answer(text, filters, int(request["top"]))
        except (FilterError, QueryError) as error:
            self.reply(400, {"error": str(error)})
            return
        except (ValueError, KeyError, TypeError):
            self.reply(400, {"error": 'zly format dopytu, ocakava sa JSON {"text", "filters", "top"}'})
            return
        self.reply(200, {"total": total, "results": rows})
        elapsed = (time.perf_counter() - start) * 1000
        print(f'"{text}" {" ".join(raw_filters)} -> {total} hracov ({elapsed:.1f} ms)')

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Bez standardneho access logu, kazdy dopyt vypise do_POST."""


def run():
    """Jednovlaknovy server: PyLucene vlakno s JVM netreba pripajat a dopyty su aj tak kratke."""
    server = HTTPServer((HOST, LUCENE_PORT), SearchHandler)
    server.engine = LuceneEngine()
    print(f"Lucene server: {server.engine.reader.numDocs()} dokumentov, port {LUCENE_PORT}. "
          f'Dopyty: py main.py search ... --index lucene, koniec: Ctrl+C')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Server zastaveny.")
    finally:
        server.server_close()
        server.engine.reader.close()


def main(argv=None):
    argparse.ArgumentParser(description="HTTP server pre vyhladavanie v Lucene indexe "
                                        "(spustat cez lucene.cmd lucene-serve).").parse_args(argv)
    run()


if __name__ == "__main__":
    main()
