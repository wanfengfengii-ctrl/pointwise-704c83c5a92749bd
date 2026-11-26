from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tests.http_forms import HTTPWorkshop, read_sample


class BrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.site = HTTPWorkshop(Path(directory.name) / 'workshop.sqlite3')
        self.addCleanup(self.site.close)

    def test_unfolded_faces(self) -> None:
        proof_id = self.site.sample('unfolded_faces.json')
        front = self.site.view(proof_id)
        back = self.site.view(proof_id, side='back')
        self.assertEqual((front.status, back.status), (200, 200))
        self.assertEqual(front.page().marks, {
            (0, 0): '左列封面线', (1, 0): '中列换色标', (2, 0): '右列裁切线',
        })
        self.assertEqual(back.page().marks, {
            (0, 0): '右列背面字样', (1, 0): '未印图记', (2, 0): '左列背面套线',
        })
        for side, reply in [('front', front), ('back', back)]:
            for x in range(3):
                with self.subTest(side=side, x=x):
                    self.assertEqual(reply.page().selection_at(x, 0).fields, {
                        'proof_id': str(proof_id), 'step': '0', 'side': side, 'x': str(x), 'y': '0',
                    })

    def test_blank_solid_still_occludes(self) -> None:
        document = read_sample('double_fold.json')
        document['holes'] = []
        document['back'] = [mark for mark in document['back'] if mark['x'] != 1]
        proof_id = self.site.freeze(document)
        view = self.site.view(proof_id, 2)
        self.assertEqual(view.status, 200)
        self.assertEqual(view.page().marks, {(0, 0): '未印图记'})
        result = self.site.post_form(view.page().selection_at(0, 0), '检查空白纸面')
        self.assertEqual(result.status, 201, result.body)
        self.assertEqual(len(result.page().notes), 1)
        self.assertEqual(result.page().notes[0][1:], (1, 0, 'back', '检查空白纸面'))

    def test_unknown_step(self) -> None:
        proof_id = self.site.sample('double_fold.json')
        reply = self.site.view(proof_id, 3)
        self.assertEqual(reply.status, 400)
        self.assertIn('折步不存在', reply.body)
        self.assertEqual(reply.page().forms, [])
        for query in ('step=-1&side=front', 'step=1.5&side=front', 'step=2&side=left'):
            with self.subTest(query=query):
                reply = self.site.request('GET', f'/proofs/{proof_id}?{query}')
                self.assertEqual(reply.status, 400)
                self.assertEqual(reply.page().forms, [])

    def test_unknown_proof(self) -> None:
        proof_id = self.site.sample('double_fold.json')
        for missing in (proof_id + 100, 1 << 80):
            with self.subTest(proof_id=missing):
                reply = self.site.view(missing, 2)
                self.assertEqual(reply.status, 404)
                self.assertIn('校样不存在', reply.body)
                self.assertEqual(reply.page().forms, [])

    def test_two_sided_fold(self) -> None:
        document = read_sample('double_fold.json')
        proof_id = self.site.sample('double_fold.json')
        front = self.site.view(proof_id, 2, 'front')
        back = self.site.view(proof_id, 2, 'back')
        self.assertEqual((front.status, back.status), (200, 200))
        front_page, back_page = front.page(), back.page()
        self.assertEqual(front_page.marks, {(0, 0): 'C 正面'})
        self.assertEqual(back_page.marks, {(0, 0): 'A 背面'})
        self.assertEqual((len(front_page.forms), len(back_page.forms)), (1, 1))
        front_form = front_page.selection_at(0, 0)
        back_form = back_page.selection_at(0, 0)
        common = {'proof_id': str(proof_id), 'step': '2', 'x': '0', 'y': '0'}
        self.assertEqual(front_form.fields, {**common, 'side': 'front'})
        self.assertEqual(back_form.fields, {**common, 'side': 'back'})

        back_receipt = self.site.post_form(back_form, '反看套线')
        front_receipt = self.site.post_form(front_form, '正看露色')
        self.assertEqual(back_receipt.status, 201, back_receipt.body)
        self.assertEqual(front_receipt.status, 201, front_receipt.body)
        back_notes, front_notes = back_receipt.page().notes, front_receipt.page().notes
        self.assertEqual((len(back_notes), len(front_notes)), (1, 1))
        receipts = back_notes + front_notes
        self.assertGreater(receipts[0][0], 0)
        self.assertGreater(receipts[1][0], receipts[0][0])
        expected = [(0, 0, 'back', '反看套线'), (2, 0, 'front', '正看露色')]
        actual = [note[1:] for note in receipts]
        self.assertEqual(actual, expected)

        unfolded = self.site.unfolded(proof_id)
        self.assertEqual(unfolded.status, 200)
        unfolded_notes = sorted(unfolded.page().notes)
        self.assertEqual(unfolded_notes, receipts)
        issued = self.site.issue(proof_id)
        self.assertEqual(issued.status, 201, issued.body)
        issued_page = issued.page()
        self.assertEqual(issued_page.report_proof_id, proof_id)
        self.assertEqual(issued_page.notes, receipts)
        self.assertIsNotNone(issued_page.report_id)
        history = self.site.report(issued_page.report_id)
        self.assertEqual(history.status, 200)
        history_notes = history.page().notes
        self.assertEqual(history_notes, receipts)

        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v5',
            'input': {
                'proof': document,
                'forms': [back_form.fields, front_form.fields],
                'text': ['反看套线', '正看露色'],
            },
            'expected': expected,
            'actual': actual,
            'downstream_expected': {'unfolded': expected, 'issued': expected, 'history': expected},
            'downstream_actual': {
                'unfolded': [note[1:] for note in unfolded_notes],
                'issued': [note[1:] for note in issued_page.notes],
                'history': [note[1:] for note in history_notes],
            },
            'code_paths': [
                'browser/grid_view.py', 'browser/selection.py', 'fold/layers.py', 'fold/visibility.py',
                'markup/target.py', 'markup/annotations.py', 'markup/unfolded.py', 'release/freeze.py',
                'release/history.py',
            ],
            'oracle': '手算终叠自上而下为 B 背面孔、C 正面、D 背面、A 正面。正看穿 B 得 C，反看从 A 的背面遇到实纸。各下游还须保留 HTTP 回执的批注号码与原文。',
        }, ensure_ascii=False), flush=True)

    def test_solid_b_changes_only_front_target(self) -> None:
        document = read_sample('double_fold.json')
        document['holes'] = []
        proof_id = self.site.freeze(document)
        for side, mark, origin_x in [('front', 'B 背面', 1), ('back', 'A 背面', 0)]:
            with self.subTest(side=side):
                preview = self.site.view(proof_id, 2, side)
                self.assertEqual(preview.status, 200)
                self.assertEqual(preview.page().marks, {(0, 0): mark})
                reply = self.site.post_form(preview.page().selection_at(0, 0), f'{side} 批注')
                self.assertEqual(reply.status, 201, reply.body)
                self.assertEqual(len(reply.page().notes), 1)
                self.assertEqual(reply.page().notes[0][1:], (origin_x, 0, 'back', f'{side} 批注'))

    def test_saved_form_uses_original_step(self) -> None:
        proof_id = self.site.sample('double_fold.json')
        old = self.site.view(proof_id, 0, 'front')
        old_form = old.page().selection_at(0, 0)
        middle = self.site.view(proof_id, 1, 'front')
        latest = self.site.view(proof_id, 2, 'back')
        self.assertEqual((old.status, middle.status, latest.status), (200, 200, 200))
        self.assertEqual(old.page().marks[(0, 0)], 'A 正面')
        self.assertEqual(middle.page().marks[(0, 0)], 'D 背面')
        self.assertEqual(latest.page().marks[(0, 0)], 'A 背面')
        receipt = self.site.post_form(old_form, '原纸页留存')
        self.assertEqual(receipt.status, 201, receipt.body)
        self.assertEqual(receipt.page().notes[0][1:], (0, 0, 'front', '原纸页留存'))

    def test_uneven_fold_mirrors_negative_projection(self) -> None:
        document = read_sample('double_fold.json')
        document['width'] = 5
        document['folds'] = document['folds'][:1]
        document['holes'] = [[3, 0]]
        document['front'].append({'x': 4, 'y': 0, 'mark': 'E 正面'})
        document['back'].append({'x': 4, 'y': 0, 'mark': 'E 背面'})
        proof_id = self.site.freeze(document)
        front = self.site.view(proof_id, 1, 'front')
        back = self.site.view(proof_id, 1, 'back')
        self.assertEqual((front.status, back.status), (200, 200))
        self.assertEqual(front.page().marks, {(0, 0): 'E 背面', (1, 0): 'A 正面', (2, 0): 'C 背面'})
        self.assertEqual(back.page().marks, {(0, 0): 'B 背面', (1, 0): 'A 背面', (2, 0): 'E 正面'})
        for preview, x, face in [(front, 0, 'back'), (back, 2, 'front')]:
            reply = self.site.post_form(preview.page().selection_at(x, 0), '越界折回')
            self.assertEqual(reply.status, 201, reply.body)
            self.assertEqual(reply.page().notes[0][1:], (4, 0, face, '越界折回'))

    def test_empty_selection(self) -> None:
        solid_id = self.site.sample('double_fold.json')
        document = read_sample('double_fold.json')
        document['holes'] = [[x, 0] for x in range(4)]
        empty_id = self.site.freeze(document)
        for side in ('front', 'back'):
            with self.subTest(side=side):
                empty = self.site.view(empty_id, 2, side)
                self.assertEqual(empty.status, 200)
                self.assertEqual(empty.page().marks, {(0, 0): '空处'})
                self.assertEqual(empty.page().forms, [])
                form = self.site.view(solid_id, 2, side).page().selection_at(0, 0)
                fields = {**form.fields, 'proof_id': str(empty_id), 'text': '空处不得保存'}
                rejection = self.site.request(form.method.upper(), form.action, fields)
                self.assertEqual(rejection.status, 422, rejection.body)
                self.assertEqual(rejection.page().notes, [])
        unfolded = self.site.unfolded(empty_id)
        self.assertEqual(unfolded.status, 200)
        self.assertEqual(unfolded.page().notes, [])
        issued = self.site.issue(empty_id)
        self.assertEqual(issued.status, 201)
        self.assertEqual(issued.page().notes, [])
        self.assertEqual(self.site.unfolded(solid_id).page().notes, [])

    def test_unresolvable_selection(self) -> None:
        proof_id = self.site.sample('double_fold.json')
        form = self.site.view(proof_id, 2).page().selection_at(0, 0)
        fields = {**form.fields, 'text': '不可解释的选择'}
        missing_step = dict(fields)
        del missing_step['step']
        cases = [
            (missing_step, 400), ({**fields, 'side': 'edge'}, 400),
            ({**fields, 'x': 'west'}, 400), ({**fields, 'step': '3'}, 400),
            ({**fields, 'text': '   '}, 400), ({**fields, 'x': '-1'}, 422),
            ({**fields, 'y': '1'}, 422), ({**fields, 'proof_id': str(proof_id + 100)}, 404),
        ]
        for payload, status in cases:
            with self.subTest(payload=payload):
                reply = self.site.request(form.method.upper(), form.action, payload)
                self.assertEqual(reply.status, status, reply.body)
                self.assertEqual(reply.page().notes, [])
        self.assertEqual(self.site.unfolded(proof_id).page().notes, [])

    def test_annotation_write_failure_has_no_receipt(self) -> None:
        proof_id = self.site.sample('double_fold.json')
        form = self.site.view(proof_id, 2).page().selection_at(0, 0)
        with closing(sqlite3.connect(self.site.database)) as connection:
            connection.execute('''
                CREATE TRIGGER stop_annotation BEFORE INSERT ON annotations
                BEGIN SELECT RAISE(ABORT, 'annotation write rejected'); END
            ''')
        rejected = self.site.post_form(form, '写失败的意见')
        self.assertEqual(rejected.status, 500)
        self.assertIn('批注保存失败', rejected.body)
        self.assertEqual(rejected.page().notes, [])
        self.assertEqual(self.site.unfolded(proof_id).page().notes, [])
