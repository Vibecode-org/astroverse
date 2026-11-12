"""Deterministic real HTTP SBDB envelope; generates one bounded row at a time."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

FIELDS = ['full_name', 'pdes', 'a', 'per', 'diameter']


def chunks(count, *, fault=None, change=None):
    yield b'{"signature":{"source":"NASA/JPL SBDB Query API","version":"1.0"},"count":"' + str(count).encode() + b'","data":['
    for i in range(count):
        if fault == 'cut' and i == count//2:
            return
        ordinal = i
        if fault == 'duplicate' and i == 1:
            i = 0
        row = [f'Synthetic asteroid {i:07d}', str(i), '2.5', '1000', '1' if change != i else '2']
        if fault == 'bad' and i == 0:
            row[2] = 'NaN'
        if fault == 'wide' and i == 0:
            row[0] = 'X'*5000
        yield (b',' if ordinal else b'') + json.dumps(row, separators=(',', ':')).encode()
    yield b'],"fields":' + json.dumps(FIELDS).encode() + b'}'


@contextmanager
def serve(count=3, *, fault=None, change=None, body=None):
    class Handler(BaseHTTPRequestHandler):
        attempts = 0
        def log_message(self, *args):
            pass
        def do_GET(self):
            Handler.attempts += 1
            if fault == 'redirect':
                self.send_response(302)
                self.send_header('Location', self.path)
                self.end_headers()
                return
            if fault in {'503', '400'}:
                self.send_error(int(fault))
                return
            if fault == 'timeout':
                time.sleep(.15)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            if fault == 'length':
                self.send_header('Content-Length', '999999')
            self.end_headers()
            try:
                for chunk in ([body] if body is not None else chunks(count, fault=fault, change=change)):
                    self.wfile.write(chunk)
                    if fault == 'hang':
                        self.wfile.flush()
                        time.sleep(2)
                if fault == 'cut':
                    self.connection.shutdown(socket.SHUT_RDWR)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/sbdb_query.api', Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
