"""Demonstrate the cut-plan browser hand-off on a temporary workshop database.

Runs two scenarios with real HTTP form round-trips:

1. 旧页承接：甲 reviews B then C on row 0; 乙 signs B away first; 甲's old
   form still signs, marking step 1 as 先前完成 and adding only C.
2. 中途验口拒签：甲 reviews B then C; 乙 signs both away; 甲's submission is
   rejected at step 1 with no new cut or plan.

Exits non-zero if any expectation fails.
"""
from contextlib import closing
from html.parser import HTMLParser
from http.client import HTTPConnection
import sqlite3
import sys
import tempfile
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode
import re

from browser.http_server import make_server
from sheet.intake import import_proof_file


EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


class _Page(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.forms: list[tuple[str, str, dict[str, str]]] = []
        self.steps: list[dict] = []
        self.shared_holes: int | None = None
        self.plan_id: int | None = None
        self._form: tuple[str, str, dict[str, str]] | None = None
        self._step: dict | None = None
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attributes) -> None:
        attrs = dict(attributes)
        if 'data-shared-holes' in attrs:
            self.shared_holes = int(attrs['data-shared-holes'])
        if 'data-cut-plan-id' in attrs:
            self.plan_id = int(attrs['data-cut-plan-id'])
        if tag == 'li' and 'data-order' in attrs:
            exposed = None
            if 'data-exposed-x' in attrs:
                exposed = (int(attrs['data-exposed-x']), int(attrs['data-exposed-y']),
                           attrs['data-exposed-face'])
            self._step = {
                'order': int(attrs['data-order']),
                'origin': (int(attrs['data-origin-x']), int(attrs['data-origin-y'])),
                'face': attrs['data-face'],
                'exposed': exposed,
                'outcome': attrs.get('data-outcome'),
            }
        if tag == 'form':
            self._form = (attrs.get('method', 'get'), attrs.get('action', ''), {})
        if self._form is not None and tag == 'input' and attrs.get('type') == 'hidden':
            self._form[2][attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag) -> None:
        if tag == 'form' and self._form is not None:
            self.forms.append(self._form)
            self._form = None
        if tag == 'li' and self._step is not None:
            self.steps.append(self._step)
            self._step = None

    def selection(self, y: int = 0) -> tuple[str, str, dict[str, str]]:
        cells = [form for form in self.forms if form[2].get('x') == '0' and form[2].get('y') == str(y)]
        if len(cells) != 1:
            raise AssertionError(f'期望显示格 (0, {y}) 一个选格表单，实际 {len(cells)} 个')
        return cells[0]

    def issue_form(self) -> tuple[str, str, dict[str, str]]:
        forms = [form for form in self.forms if form[1].endswith('/issue')]
        if len(forms) != 1:
            raise AssertionError(f'期望一个签出表单，实际 {len(forms)} 个')
        return forms[0]


class _Client:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.server = make_server(database, port=0)
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05})
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method: str, path: str, fields: dict[str, str] | None = None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        with closing(connection):
            if fields is None:
                connection.request(method, path)
            else:
                connection.request(method, path, body=urlencode(fields), headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                })
            response = connection.getresponse()
            body = response.read().decode('utf-8')
        return response.status, body, _Page(body)

    def open_draft(self, proof_id: int) -> tuple[int, _Page]:
        status, body, page = self.request('POST', '/cut-plans', {'proof_id': str(proof_id)})
        assert status == 201, (status, body)
        match = re.search(r'data-draft-id="(\d+)"', body)
        assert match is not None
        return int(match.group(1)), page

    def draft_page(self, draft_id: int) -> _Page:
        status, _, page = self.request('GET', f'/cut-plans/{draft_id}?step=2&side=front')
        assert status == 200, status
        return page

    def trial(self, form) -> _Page:
        status, body, page = self.request('POST', form[1], form[2])
        assert status == 200, (status, body)
        return page

    def issue(self, form):
        return self.request('POST', form[1], form[2])

    def holes(self, proof_id: int) -> int:
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute(
                'SELECT count(*) FROM cut_holes WHERE proof_id = ?', (proof_id,),
            ).fetchone()[0]

    def plans(self) -> int:
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute('SELECT count(*) FROM cut_plans').fetchone()[0]


def _review_two_steps(client: _Client, proof_id: int) -> tuple[int, _Page]:
    draft_id, _ = client.open_draft(proof_id)
    page = client.trial(client.draft_page(draft_id).selection())
    page = client.trial(page.selection())
    return draft_id, page


def _sign_one(client: _Client, proof_id: int, steps: int) -> None:
    draft_id, _ = client.open_draft(proof_id)
    page = client.draft_page(draft_id)
    for _ in range(steps):
        page = client.trial(page.selection())
    status, body, page = client.issue(page.issue_form())
    assert status == 201, (status, body)


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / 'demo.sqlite3'
        client = _Client(database)
        try:
            carry_proof = _freeze(database)
            draft_id, reviewed = _review_two_steps(client, carry_proof)
            preview = [(step['origin'], step['face'], step['exposed'])
                       for step in reviewed.steps]
            _sign_one(client, carry_proof, 1)  # 乙 signs B away first.
            holes_before = client.holes(carry_proof)
            status, body, page = client.issue(reviewed.issue_form())
            outcomes = [step['outcome'] for step in page.steps]
            carry = {
                'draft': draft_id,
                'preview': preview,
                'sign_status': status,
                'outcomes': outcomes,
                'exposed': [step['exposed'] for step in page.steps],
                'holes_added_by_this_plan': client.holes(carry_proof) - holes_before,
                'plan_id': page.plan_id,
            }
            expected_preview = [((1, 0), 'back', (2, 0, 'front')),
                                ((2, 0), 'front', (3, 0, 'back'))]
            if status != 201:
                failures.append(f'旧页承接签出失败：{status}')
            if preview != expected_preview:
                failures.append(f'预览不符：{preview}')
            if outcomes != ['prior', 'new']:
                failures.append(f'办理结果不符：{outcomes}')
            if carry['exposed'] != [(2, 0, 'front'), (3, 0, 'back')]:
                failures.append(f'逐步露面不符：{carry["exposed"]}')
            if carry['holes_added_by_this_plan'] != 1:
                failures.append(f'本单应只新增一个裁口，实际 {carry["holes_added_by_this_plan"]}')

            conflict_proof = _freeze(database)
            conflict_id, conflict_review = _review_two_steps(client, conflict_proof)
            _sign_one(client, conflict_proof, 2)  # 乙 signs B and C away.
            plans_before = client.plans()
            holes_before = client.holes(conflict_proof)
            status, body, page = client.issue(conflict_review.issue_form())
            conflict = {
                'draft': conflict_id,
                'sign_status': status,
                'mentions_first_step': '第 1 步' in body,
                'new_plan': page.plan_id is not None,
                'holes_unchanged': client.holes(conflict_proof) == holes_before,
                'plans_unchanged': client.plans() == plans_before,
            }
            if status != 409:
                failures.append(f'中途验口应拒签 409，实际 {status}')
            if '第 1 步' not in body:
                failures.append('拒签页未指出第一步冲突')
            if page.plan_id is not None:
                failures.append('拒签仍产生了签单')
            if not conflict['holes_unchanged']:
                failures.append('拒签仍新增了裁口')
            if not conflict['plans_unchanged']:
                failures.append('拒签仍新增了签单记录')
        finally:
            client.close()

    print('DEMO 旧页承接（他人先签走 B）：')
    print(f'  草稿 #{carry["draft"]} 预览：' + '；'.join(
        f'裁 {origin} {face} 露 {exposed}' for origin, face, exposed in carry['preview']))
    print(f'  签出 HTTP {carry["sign_status"]}，办理结果 {carry["outcomes"]}，'
          f'逐步露面 {carry["exposed"]}，本单新增裁口 {carry["holes_added_by_this_plan"]} 个，'
          f'签单 #{carry["plan_id"]}。')
    print('DEMO 中途验口拒签（他人已签走 B、C）：')
    print(f'  草稿 #{conflict["draft"]} 签出 HTTP {conflict["sign_status"]}，'
          f'指出第一步：{conflict["mentions_first_step"]}，'
          f'无新签单：{not conflict["new_plan"]}，'
          f'裁口不变：{conflict["holes_unchanged"]}，签单数不变：{conflict["plans_unchanged"]}。')
    if failures:
        for failure in failures:
            print(f'DEMO FAIL {failure}', file=sys.stderr)
        return 1
    print('DEMO PASS')
    return 0


def _freeze(database: Path) -> int:
    with closing(sqlite3.connect(database)) as connection:
        return import_proof_file(connection, EXAMPLES / 'cut_plans.json')


if __name__ == '__main__':
    raise SystemExit(main())
