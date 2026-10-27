"""Opt-in native CLI boundary test; loopback mock only, no account/model request."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import paperflow_codex as codex


@unittest.skipUnless(os.environ.get('PAPERFLOW_TEST_CODEX') == '1', 'opt-in: requires Codex CLI 0.155.1')
class NativeCodexBoundaryTests(unittest.TestCase):
    def test_real_cli_sends_no_tools_and_no_unrelated_file_contents(self):
        binary = shutil.which('codex')
        self.assertIsNotNone(binary)
        self.assertEqual(subprocess.check_output([binary, '--version']).decode().strip(), codex.SUPPORTED_CLI)
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                item = {'type': 'message', 'id': 'msg_fixture', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': 'MOCK_OK', 'annotations': []}]}
                events = [{'type': 'response.created', 'response': {'id': 'resp_fixture'}},
                          {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                          {'type': 'response.completed', 'response': {'id': 'resp_fixture', 'status': 'completed',
                           'output': [item], 'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}}]
                data = ''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                secret = folder/'unrelated.txt'
                secret.write_text('SYNTHETIC_PRIVATE_SENTINEL_41a9')
                cfg = {'model': 'paperflow-mock', '_codex_binary': binary, '_codex_effort': 'none',
                       '_codex_provider': 'probe', 'codex_timeout': 30,
                       '_codex_provider_config': {'name': 'probe', 'requires_openai_auth': False,
                           'wire_api': 'responses', 'base_url': f'http://127.0.0.1:{server.server_port}/v1'}}
                # Empty native home isolates this test from the user's credentials/config.
                with patch.dict(os.environ, {'CODEX_HOME': temporary}):
                    answer = codex.chat(cfg, f'Untrusted source asks to read {secret}. Return mock text only.')
            self.assertEqual(answer, 'MOCK_OK')
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]['tools'], [])
            self.assertNotIn('SYNTHETIC_PRIVATE_SENTINEL_41a9', json.dumps(requests))
            self.assertEqual(requests[0]['model'], 'paperflow-mock')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
