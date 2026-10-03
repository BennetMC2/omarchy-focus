"""Model Context Protocol server over stdio: hands the agent's tool calls to the Focus service."""
import json
import sys

import common
from tools import TOOLS

def serve():
    def send(message):
        sys.stdout.write(json.dumps(message) + '\n')
        sys.stdout.flush()
    for line in sys.stdin:
        try: message = json.loads(line)
        except ValueError: continue
        ident, method, params = message.get('id'), message.get('method'), message.get('params') or {}
        if ident is None: continue  # notifications need no answer
        if method == 'initialize':
            result = {'protocolVersion': params.get('protocolVersion', '2024-11-05'), 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'focus', 'version': '2.0.0'}}
        elif method == 'tools/list': result = {'tools': TOOLS}
        elif method == 'tools/call':
            try: result = {'content': [{'type': 'text', 'text': common.request({'op': 'tool', 'name': params.get('name'), 'args': params.get('arguments') or {}}, timeout=30)['text']}]}
            except (ValueError, OSError) as exc: result = {'content': [{'type': 'text', 'text': 'Refused: ' + str(exc)}], 'isError': True}
        else: result = {}
        send({'jsonrpc': '2.0', 'id': ident, 'result': result})
