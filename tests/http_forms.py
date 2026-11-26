from contextlib import closing
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.client import HTTPConnection
import json
from pathlib import Path
import re
import sqlite3
from threading import Thread
from urllib.parse import urlencode

from browser.http_server import make_server
from sheet.intake import import_proof_file, parse_proof_input
from sheet.proofs import freeze_proof


EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


def read_sample(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding='utf-8'))


@dataclass
class HTMLForm:
    method: str
    action: str
    fields: dict[str, str] = field(default_factory=dict)
    text_fields: list[str] = field(default_factory=list)


class WorkshopPage(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.forms: list[HTMLForm] = []
        self.notes: list[tuple[int, int, int, str, str]] = []
        self.marks: dict[tuple[int, int], str] = {}
        self.report_id: int | None = None
        self.report_proof_id: int | None = None
        self.cut_plan_id: int | None = None
        self.cut_plan_proof_id: int | None = None
        self.cut_steps: list[dict] = []
        self.shared_holes: int | None = None
        self._form: HTMLForm | None = None
        self._location: tuple[str, int, int, str] | None = None
        self._display: tuple[int, int] | None = None
        self._mark: list[str] | None = None
        self._note: tuple[int, list[str]] | None = None
        self._cut_step: dict | None = None
        self.feed(source)
        self.close()

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        if 'data-report-id' in attrs:
            self.report_id = int(attrs['data-report-id'])
            self.report_proof_id = int(attrs['data-proof-id'])
        if 'data-cut-plan-id' in attrs:
            self.cut_plan_id = int(attrs['data-cut-plan-id'])
            self.cut_plan_proof_id = int(attrs['data-proof-id'])
        if 'data-shared-holes' in attrs:
            self.shared_holes = int(attrs['data-shared-holes'])
        if tag == 'li' and 'data-order' in attrs:
            exposed = None
            if 'data-exposed-x' in attrs:
                exposed = (
                    int(attrs['data-exposed-x']), int(attrs['data-exposed-y']),
                    attrs['data-exposed-face'],
                )
            self._cut_step = {
                'order': int(attrs['data-order']),
                'fold_step': int(attrs['data-fold-step']),
                'side': attrs['data-side'],
                'display': (int(attrs['data-display-x']), int(attrs['data-display-y'])),
                'origin': (int(attrs['data-origin-x']), int(attrs['data-origin-y'])),
                'face': attrs['data-face'],
                'exposed': exposed,
                'outcome': attrs.get('data-outcome'),
                'lines': [],
            }
        if 'data-face' in attrs and 'data-x' in attrs and 'data-y' in attrs:
            self._location = tag, int(attrs['data-x']), int(attrs['data-y']), attrs['data-face']
        if tag == 'td' and 'data-display-x' in attrs:
            self._display = int(attrs['data-display-x']), int(attrs['data-display-y'])
        if tag == 'p' and self._display is not None and attrs.get('class') == 'cell-mark':
            self._mark = []
        if tag == 'p' and 'data-annotation-id' in attrs:
            if self._location is None:
                raise AssertionError('批注未锚定原纸面')
            self._note = int(attrs['data-annotation-id']), []
        if tag == 'form':
            self._form = HTMLForm(attrs.get('method', 'get'), attrs.get('action', ''))
        if self._form is not None:
            if tag == 'input' and attrs.get('type') == 'hidden':
                name = attrs['name']
                if name in self._form.fields:
                    raise AssertionError(f'表单字段重复：{name}')
                self._form.fields[name] = attrs.get('value', '')
            if tag == 'textarea' and 'name' in attrs:
                self._form.text_fields.append(attrs['name'])

    def handle_data(self, data: str) -> None:
        if self._cut_step is not None and data.strip():
            self._cut_step['lines'].append(data.strip())
        if self._note is not None:
            self._note[1].append(data)
        if self._mark is not None:
            self._mark.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'form' and self._form is not None:
            self.forms.append(self._form)
            self._form = None
        if tag == 'p' and self._note is not None:
            annotation_id, text = self._note
            _, x, y, face = self._location
            self.notes.append((annotation_id, x, y, face, ''.join(text)))
            self._note = None
        if tag == 'p' and self._mark is not None:
            self.marks[self._display] = ''.join(self._mark)
            self._mark = None
        if tag == 'li' and self._cut_step is not None:
            self.cut_steps.append(self._cut_step)
            self._cut_step = None
        if tag == 'td':
            self._display = None
        if self._location is not None and tag == self._location[0]:
            self._location = None

    def selection_at(self, x: int, y: int) -> HTMLForm:
        forms = [form for form in self.forms if (
            form.fields.get('x') == str(x) and form.fields.get('y') == str(y)
        )]
        if len(forms) != 1:
            raise AssertionError(f'显示格 ({x}, {y}) 应有一个选格表单，实际有 {len(forms)} 个')
        return forms[0]

    def issue_form(self) -> HTMLForm:
        forms = [form for form in self.forms if form.action.endswith('/issue')]
        if len(forms) != 1:
            raise AssertionError(f'草稿页应有一个签出表单，实际有 {len(forms)} 个')
        return forms[0]


@dataclass(frozen=True)
class HTTPReply:
    status: int
    body: str

    def page(self) -> WorkshopPage:
        return WorkshopPage(self.body)


class HTTPWorkshop:
    def __init__(self, database: Path) -> None:
        self.database = database
        self._server = None
        self._thread = None
        self.start()

    def start(self) -> None:
        self._server = make_server(self.database, port=0)
        self._thread = Thread(target=self._server.serve_forever, kwargs={'poll_interval': 0.05})
        self._thread.start()

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise AssertionError('HTTP 服务线程未退出')
            self._server = None
            self._thread = None

    def restart(self) -> None:
        self.close()
        self.start()

    def sample(self, filename: str) -> int:
        with closing(sqlite3.connect(self.database)) as connection:
            return import_proof_file(connection, EXAMPLES / filename)

    def freeze(self, document: dict) -> int:
        with closing(sqlite3.connect(self.database)) as connection:
            return freeze_proof(connection, parse_proof_input(document))

    def request(self, method: str, path: str, fields: dict[str, str] | None = None) -> HTTPReply:
        connection = HTTPConnection('127.0.0.1', self._server.server_port, timeout=5)
        with closing(connection):
            if fields is None:
                connection.request(method, path)
            else:
                connection.request(method, path, body=urlencode(fields), headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                })
            response = connection.getresponse()
            return HTTPReply(response.status, response.read().decode('utf-8'))

    def view(self, proof_id: int, step: int = 0, side: str = 'front') -> HTTPReply:
        query = urlencode({'step': step, 'side': side})
        return self.request('GET', f'/proofs/{proof_id}?{query}')

    def post_form(self, form: HTMLForm, text: str | None = None) -> HTTPReply:
        fields = dict(form.fields)
        if text is not None:
            if len(form.text_fields) != 1:
                raise AssertionError('选格表单须有一个批注输入框')
            fields[form.text_fields[0]] = text
        return self.request(form.method.upper(), form.action, fields)

    def unfolded(self, proof_id: int) -> HTTPReply:
        return self.request('GET', f'/proofs/{proof_id}/unfolded')

    def issue(self, proof_id: int) -> HTTPReply:
        unfolded = self.unfolded(proof_id)
        if unfolded.status != 200:
            raise AssertionError(f'无法打开待签展开图：{unfolded.status}')
        forms = unfolded.page().forms
        if len(forms) != 1:
            raise AssertionError('展开图须有一个签出表单')
        return self.post_form(forms[0])

    def report(self, report_id: int) -> HTTPReply:
        return self.request('GET', f'/reports/{report_id}')

    def trial_desk(self, proof_id: int, step: int = 0, side: str = 'front') -> HTTPReply:
        query = urlencode({'step': step, 'side': side})
        return self.request('GET', f'/proofs/{proof_id}/cut-plans?{query}')

    def open_draft(self, proof_id: int) -> tuple[int, HTTPReply]:
        reply = self.request('POST', '/cut-plans', {'proof_id': str(proof_id)})
        if reply.status != 201:
            return 0, reply
        draft_id = _draft_id_from(reply.body)
        return draft_id, reply

    def draft(self, draft_id: int, step: int = 0, side: str = 'front') -> HTTPReply:
        query = urlencode({'step': step, 'side': side})
        return self.request('GET', f'/cut-plans/{draft_id}?{query}')

    def trial_step(self, form: HTMLForm) -> HTTPReply:
        return self.post_form(form)

    def cut_plan(self, plan_id: int) -> HTTPReply:
        return self.request('GET', f'/cut-reports/{plan_id}')


def _draft_id_from(source: str) -> int:
    match = re.search(r'data-draft-id="(\d+)"', source)
    if match is None:
        raise AssertionError('成功页缺少草稿号')
    return int(match.group(1))
