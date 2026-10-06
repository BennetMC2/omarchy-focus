"""Model Context Protocol server over stdio: hands the agent's tool calls to the Bouncer service."""
import json
import os
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
                      'serverInfo': {'name': 'focus', 'version': '2.3.0-beta.1'}}
        elif method == 'tools/list': result = {'tools': TOOLS}
        elif method == 'tools/call':
            try:
                reply = common.request({'op': 'tool', 'name': params.get('name'), 'args': params.get('arguments') or {}, 'session': os.environ.get('FOCUS_SESSION', '')}, timeout=30)
                result = {'content': [{'type': 'text', 'text': reply['text']}]}
                if reply.get('image'): result['content'].append({'type': 'image', 'data': reply['image']['data'], 'mimeType': reply['image']['mime']})
            except (ValueError, OSError) as exc: result = {'content': [{'type': 'text', 'text': 'Refused: ' + str(exc)}], 'isError': True}
        else: result = {}
        send({'jsonrpc': '2.0', 'id': ident, 'result': result})
