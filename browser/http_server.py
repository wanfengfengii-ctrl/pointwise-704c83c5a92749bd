import argparse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
from urllib.parse import parse_qsl, urlsplit

from browser.html_pages import PageResponse, page, problem
from browser.proof_pages import view_proof
from markup.annotations import initialize_annotations
from markup.review_pages import submit_annotation, view_unfolded
from release.history import initialize_reports
from release.http_reports import issue_report_response, read_report_response
from sheet.proof_store import initialize_proofs


class ProofServer(ThreadingHTTPServer):
    def __init__(self, port: int, database: Path) -> None:
        self.database = database
        self.stylesheet = Path(__file__).with_name('style.css').read_bytes()
        super().__init__(('127.0.0.1', port), ProofRequestHandler)


def _connect(database: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


def initialize_database(database: str | Path) -> None:
    with closing(_connect(database)) as connection, connection:
        initialize_proofs(connection)
        initialize_annotations(connection)
        initialize_reports(connection)


def _form_fields(encoded: str) -> dict[str, str]:
    pairs = parse_qsl(encoded, keep_blank_values=True, strict_parsing=True, errors='strict')
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError('请求字段不能重复')
    return fields


def _number(raw: str, label: str) -> int:
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f'{label}须为正整数') from error
    if value <= 0:
        raise ValueError(f'{label}须为正整数')
    return value


def _home() -> PageResponse:
    return page('打开校样或签出单', '''
<div class="home-forms">
<form method="get" action="/proofs">
<label>校样号<input type="number" name="proof_id" min="1" required></label>
<button type="submit">查看校样</button>
</form>
<form method="get" action="/reports">
<label>签出号<input type="number" name="report_id" min="1" required></label>
<button type="submit">领取签出单</button>
</form>
</div>
''')


class ProofRequestHandler(BaseHTTPRequestHandler):
    server: ProofServer

    def _send(self, status: int, mime: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_page(self, response: PageResponse) -> None:
        self._send(response.status, 'text/html; charset=utf-8', response.body.encode('utf-8'))

    def _get_page(
        self, connection: sqlite3.Connection, path: str, fields: dict[str, str],
    ) -> PageResponse:
        if path == '/':
            return _home()
        if path == '/proofs':
            proof_id = _number(fields.pop('proof_id', ''), '校样号')
            return view_proof(connection, proof_id, fields)
        if path == '/reports':
            return read_report_response(connection, _number(fields.get('report_id', ''), '签出号'))
        parts = path.split('/')
        if len(parts) == 3 and parts[1] == 'proofs':
            return view_proof(connection, _number(parts[2], '校样号'), fields)
        if len(parts) == 4 and parts[1] == 'proofs' and parts[3] == 'unfolded':
            return view_unfolded(connection, _number(parts[2], '校样号'))
        if len(parts) == 3 and parts[1] == 'reports':
            return read_report_response(connection, _number(parts[2], '签出号'))
        return problem(404, '页面不存在')

    def do_GET(self) -> None:
        try:
            target = urlsplit(self.path)
            if target.path == '/style.css':
                self._send(200, 'text/css; charset=utf-8', self.server.stylesheet)
                return
            fields = _form_fields(target.query)
            with closing(_connect(self.server.database)) as connection:
                response = self._get_page(connection, target.path, fields)
        except ValueError as error:
            response = problem(400, str(error))
        except sqlite3.Error:
            response = problem(500, '读取工坊数据失败')
        self._send_page(response)

    def _read_form(self) -> dict[str, str]:
        length = int(self.headers.get('Content-Length', ''))
        if length < 0:
            raise ValueError('表单长度无效')
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError('表单内容不完整')
        return _form_fields(body.decode('utf-8'))

    def do_POST(self) -> None:
        try:
            path = urlsplit(self.path).path
            if path not in ('/annotations', '/reports'):
                self._send_page(problem(404, '页面不存在'))
                return
            if self.headers.get_content_type() != 'application/x-www-form-urlencoded':
                self._send_page(problem(415, '请提交网页表单'))
                return
            fields = self._read_form()
            with closing(_connect(self.server.database)) as connection:
                if path == '/annotations':
                    response = submit_annotation(connection, fields)
                else:
                    response = issue_report_response(connection, _number(fields.get('proof_id', ''), '校样号'))
        except ValueError as error:
            response = problem(400, str(error))
        except sqlite3.Error:
            response = problem(500, '保存工坊数据失败')
        self._send_page(response)


def make_server(database: str | Path, port: int = 8000) -> ProofServer:
    path = Path(database).resolve()
    initialize_database(path)
    return ProofServer(port, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='启动榆巷纸样工坊')
    parser.add_argument('--db', required=True, type=Path, help='工坊 SQLite 文件')
    parser.add_argument('--port', type=int, default=8000, help='本机 HTTP 端口')
    args = parser.parse_args(argv)
    with make_server(args.db, args.port) as server:
        print(f'工坊已启动：http://127.0.0.1:{server.server_port}/', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
