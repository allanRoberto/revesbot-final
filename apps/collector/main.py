#!/usr/bin/env python3
import threading
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

from collector_ws_pragmatic import Pragmatic
from collector_ws_evolution import Evolution
from collector_ws_miguel import Results
from collector_ws_ezugi import Ezugi

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"🟢 Collector rodando")


def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    logging.info(f"Dummy HTTP server listening on port {port}")
    server.serve_forever()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s: %(message)s"
    )

    # Instancia collectors
    pragmatic = Pragmatic()
    evolution = Evolution()
    results = Results()
    ezugi     = Ezugi()

    # Cria threads para collectors e dummy server
    threads = [
        threading.Thread(target=pragmatic.start, name="PragmaticCollector"),
        threading.Thread(target=evolution.start, name="EvolutionCollector"),
        threading.Thread(target=results.start, name="ResultsCollector"),
        threading.Thread(target=ezugi.start,     name="EzugiCollector"),
    ]

    # Marca como daemon e inicia todas
    for thread in threads:
        thread.daemon = True
        thread.start()

    # Aguarda encerramento ou interrupção
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        logging.info("Shutdown requested. Exiting...")


if __name__ == "__main__":
    main()