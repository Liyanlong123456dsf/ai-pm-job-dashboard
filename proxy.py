#!/usr/bin/env python3
"""轻量 CORS 代理 - 转发 AI 对话请求到 Kimi API"""
import http.server
import urllib.request
import json

PORT = 8766
KIMI_URL = 'https://api.kimi.com/coding/v1/messages'

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        req = urllib.request.Request(
            KIMI_URL,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': self.headers.get('x-api-key', ''),
                'anthropic-version': '2023-06-01',
            },
            method='POST'
        )

        try:
            resp = urllib.request.urlopen(req)
            self.send_response(200)
            self._cors()
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self._cors()
            self.end_headers()
            self.wfile.write(e.read())

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')

    def log_message(self, format, *args):
        pass  # 静默日志

if __name__ == '__main__':
    server = http.server.HTTPServer(('127.0.0.1', PORT), ProxyHandler)
    print(f'CORS 代理运行在 http://127.0.0.1:{PORT}')
    server.serve_forever()
