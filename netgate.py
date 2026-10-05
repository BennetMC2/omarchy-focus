"""The only way out of the agent jail: a gate that lets a jailed agent reach its own provider and nothing else.

The jail has no network of its own. Inside it, a small bridge listens on loopback and passes connections
over a Unix socket to the gate, which runs in the Focus service and checks every destination.
"""
import os
import select
import socket
import subprocess
import sys
import threading

# Where each agent's provider lives. A destination must be one of these names or a subdomain of one.
PROVIDER_HOSTS = {'codex': ('openai.com', 'chatgpt.com'), 'grok': ('x.ai', 'grok.com')}

def permitted(host, domains):
    host = host.lower().rstrip('.')
    return any(host == domain or host.endswith('.' + domain) for domain in domains)

def relay(a, b):
    """Copy bytes both ways until either side closes."""
    try:
        while True:
            ready, _, _ = select.select([a, b], [], [], 300)
            if not ready: break
            for source in ready:
                data = source.recv(65536)
                if not data: return
                (b if source is a else a).sendall(data)
    except OSError: pass
    finally:
        for end in (a, b):
            try: end.close()
            except OSError: pass

class Gate:
    """Accepts CONNECT requests on a Unix socket and opens only connections to the allowed provider on port 443."""
    def __init__(self, path, domains):
        self.path, self.domains, self.refused = str(path), tuple(domains), []
        try: os.unlink(self.path)
        except OSError: pass
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(self.path)
        os.chmod(self.path, 0o600)
        self.server.listen(32)
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try: conn, _ = self.server.accept()
            except OSError: return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        try:
            conn.settimeout(15)
            head = b''
            while b'\r\n\r\n' not in head and len(head) < 8192:
                chunk = conn.recv(4096)
                if not chunk: return conn.close()
                head += chunk
            words = head.split(b'\r\n', 1)[0].decode('latin-1').split()
            host, _, port = (words[1] if len(words) > 1 else '').rpartition(':')
            if len(words) < 2 or words[0] != 'CONNECT' or port != '443' or not permitted(host, self.domains):
                self.refused.append(words[1] if len(words) > 1 else '?')
                conn.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
                return conn.close()
            upstream = socket.create_connection((host, 443), timeout=15)
            conn.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
            conn.settimeout(None); upstream.settimeout(None)
            relay(conn, upstream)
        except OSError:
            try: conn.close()
            except OSError: pass

    def close(self):
        try: self.server.close()
        except OSError: pass
        try: os.unlink(self.path)
        except OSError: pass

def run_bridged(gate_path, command):
    """Inside the jail: listen on loopback, pass everything to the gate, and run the agent pointed at that."""
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(32)
    port = listener.getsockname()[1]
    def accept():
        while True:
            try: conn, _ = listener.accept()
            except OSError: return
            try:
                out = socket.socket(socket.AF_UNIX)
                out.connect(gate_path)
            except OSError:
                conn.close(); continue
            threading.Thread(target=relay, args=(conn, out), daemon=True).start()
    threading.Thread(target=accept, daemon=True).start()
    proxy = 'http://127.0.0.1:%d' % port
    env = {**os.environ, 'HTTPS_PROXY': proxy, 'https_proxy': proxy, 'HTTP_PROXY': proxy, 'http_proxy': proxy, 'ALL_PROXY': proxy, 'NO_PROXY': '', 'no_proxy': ''}
    return subprocess.run(command, env=env).returncode

if __name__ == '__main__':
    sys.exit(run_bridged(sys.argv[1], sys.argv[2:]))
