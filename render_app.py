import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

def run_sync():
    print("Starte ABRP Sync Loop (5-Minuten-Takt)...", flush=True)
    while True:
        abrp_token = os.environ.get("ABRP_TOKEN", "")
        os.system(f'python leapmotor_to_abrp.py --abrp-token "{abrp_token}" --once')
        time.sleep(300)

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Leapmotor ABRP Sync is active!")

if __name__ == '__main__':
    # Starte den Sync in einem separaten Hintergrund-Thread
    t = threading.Thread(target=run_sync, daemon=True)
    t.start()
    
    # Starte einen Dummy-Webserver, damit Render den Service als "Gesund" einstuft
    port = int(os.environ.get("PORT", 10000))
    print(f"Starte Dummy-Webserver auf Port {port}...", flush=True)
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()
