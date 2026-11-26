from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from browser.http_server import initialize_database
from fold.layers import build_layers
from sheet.intake import import_proof_file, parse_proof_input
from sheet.proofs import freeze_proof, get_proof
from sheet.stock import Cell, Face, Stock
from tests.http_forms import EXAMPLES, read_sample


class ProofTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / 'workshop.sqlite3'
        initialize_database(self.database)
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)

    def _draft(self) -> dict:
        return read_sample('double_fold.json')

    def _import(self, document: dict) -> int:
        source = self.root / 'incoming.json'
        source.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        return import_proof_file(self.connection, source)

    def _proof_count(self) -> int:
        return self.connection.execute('SELECT count(*) FROM proofs').fetchone()[0]

    def test_freeze(self) -> None:
        proof_id = import_proof_file(self.connection, EXAMPLES / 'double_fold.json')
        self.assertGreater(proof_id, 0)
        with closing(sqlite3.connect(self.database)) as reopened:
            proof = get_proof(reopened, proof_id)
        self.assertEqual(proof.proof_id, proof_id)
        self.assertEqual(proof.stock, Stock(4, 1))
        for x, label in enumerate('ABCD'):
            with self.subTest(cell=x):
                self.assertEqual(proof.ink.mark_at(Cell(x, 0), Face.FRONT), f'{label} 正面')
                self.assertEqual(proof.ink.mark_at(Cell(x, 0), Face.BACK), f'{label} 背面')
                self.assertEqual(proof.cutouts.is_hole(Cell(x, 0)), x == 1)
        self.assertEqual(
            [(fold.axis.value, fold.line, fold.moving.value) for fold in proof.folds.creases],
            [('x', 2, 'high'), ('x', 1, 'high')],
        )

    def test_ordered_creases(self) -> None:
        source = {
            'width': 2, 'height': 2,
            'front': [{'x': 0, 'y': 1, 'mark': '下方图记'}],
            'back': [{'x': 1, 'y': 0, 'mark': '右侧套线'}],
            'holes': [[1, 1]],
            'folds': [
                {'axis': 'y', 'line': 1, 'moving': 'high'},
                {'axis': 'x', 'line': 1, 'moving': 'low'},
            ],
        }
        proof_id = self._import(source)
        with closing(sqlite3.connect(self.database)) as reopened:
            proof = get_proof(reopened, proof_id)
        self.assertEqual(
            [(fold.axis.value, fold.line, fold.moving.value) for fold in proof.folds.creases],
            [('y', 1, 'high'), ('x', 1, 'low')],
        )
        self.assertEqual(proof.ink.mark_at(Cell(0, 1), Face.FRONT), '下方图记')
        self.assertEqual(proof.ink.mark_at(Cell(1, 0), Face.BACK), '右侧套线')
        self.assertTrue(proof.cutouts.is_hole(Cell(1, 1)))
        self.assertEqual(proof.stock, Stock(2, 2))
        folded = build_layers(proof.stock, proof.cutouts, proof.folds, 2)
        self.assertEqual(list(folded.stacks), [Cell(1, 0)])
        self.assertEqual(
            [(item.origin, item.top_face) for item in folded.stacks[Cell(1, 0)]],
            [(Cell(0, 0), Face.BACK), (Cell(0, 1), Face.FRONT),
             (Cell(1, 1), Face.BACK), (Cell(1, 0), Face.FRONT)],
        )

    def test_reopen_and_reimport(self) -> None:
        initialize_database(self.database)
        self.assertEqual(self._proof_count(), 0)
        document = self._draft()
        first = self._import(document)
        document['front'][0]['mark'] = '第二次试印'
        second = self._import(document)
        self.assertNotEqual(first, second)
        initialize_database(self.database)
        with closing(sqlite3.connect(self.database)) as reopened:
            original = get_proof(reopened, first)
            revised = get_proof(reopened, second)
        self.assertEqual(original.ink.mark_at(Cell(0, 0), Face.FRONT), 'A 正面')
        self.assertEqual(revised.ink.mark_at(Cell(0, 0), Face.FRONT), '第二次试印')
        self.assertEqual(original.folds, revised.folds)
        self.assertEqual(self._proof_count(), 2)

    def test_bad_crease(self) -> None:
        document = self._draft()
        document['folds'][0]['line'] = 1.5
        with self.assertRaisesRegex(ValueError, '第 1 道折线.*整数格边'):
            self._import(document)
        self.assertEqual(self._proof_count(), 0)

    def test_bad_second_crease(self) -> None:
        for invalid_line in (0.5, 2):
            with self.subTest(line=invalid_line):
                document = self._draft()
                document['folds'][1]['line'] = invalid_line
                with self.assertRaisesRegex(ValueError, '第 2 道折线'):
                    self._import(document)
                self.assertEqual(self._proof_count(), 0)

    def test_invalid_cells_and_dimensions(self) -> None:
        mutations = (
            {'width': 0},
            {'height': True},
            {'front': [{'x': True, 'y': 0, 'mark': '错格'}]},
            {'back': [{'x': 4, 'y': 0, 'mark': '越界'}]},
            {'holes': [[1, -1]]},
            {'holes': [[1, 0], [1, 0]]},
            {'back': [{'x': 0, 'y': 0, 'mark': 17}]},
            {'front': [{'x': 0, 'y': 0, 'mark': '一'}, {'x': 0, 'y': 0, 'mark': '二'}]},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                document = self._draft()
                document.update(mutation)
                with self.assertRaises(ValueError):
                    self._import(document)
                self.assertEqual(self._proof_count(), 0)

    def test_too_many_folds(self) -> None:
        document = self._draft()
        document['folds'].append({'axis': 'x', 'line': 1, 'moving': 'high'})
        with self.assertRaisesRegex(ValueError, '最多'):
            self._import(document)
        self.assertEqual(self._proof_count(), 0)

    def test_freeze_write_failure(self) -> None:
        self.connection.execute('''
            CREATE TRIGGER stop_proof BEFORE INSERT ON proofs
            BEGIN SELECT RAISE(ABORT, 'proof write rejected'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'proof write rejected'):
            self._import(self._draft())
        self.assertEqual(self._proof_count(), 0)
        self.connection.execute('DROP TRIGGER stop_proof')
        self.assertGreater(self._import(self._draft()), 0)
        self.assertEqual(self._proof_count(), 1)

    def test_layer_order(self) -> None:
        proof_id = freeze_proof(self.connection, parse_proof_input(self._draft()))
        proof = get_proof(self.connection, proof_id)
        initial = build_layers(proof.stock, proof.cutouts, proof.folds, 0)
        self.assertEqual(set(initial.stacks), {Cell(0, 0), Cell(1, 0), Cell(2, 0), Cell(3, 0)})
        first = build_layers(proof.stock, proof.cutouts, proof.folds, 1)
        self.assertEqual([item.origin.x for item in first.stacks[Cell(0, 0)]], [3, 0])
        self.assertEqual([item.origin.x for item in first.stacks[Cell(1, 0)]], [2, 1])
        second = build_layers(proof.stock, proof.cutouts, proof.folds, 2)
        self.assertEqual(set(second.stacks), {Cell(0, 0)})
        stack = second.stacks[Cell(0, 0)]
        self.assertEqual(
            [(layer.origin.x, layer.top_face.value, layer.is_hole) for layer in stack],
            [(1, 'back', True), (2, 'front', False), (3, 'back', False), (0, 'front', False)],
        )
