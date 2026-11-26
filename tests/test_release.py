from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tests.http_forms import HTTPWorkshop


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.site = HTTPWorkshop(Path(directory.name) / 'workshop.sqlite3')
        self.addCleanup(self.site.close)

    def _annotate(self, proof_id: int, side: str, x: int, text: str) -> tuple:
        preview = self.site.view(proof_id, 0, side)
        self.assertEqual(preview.status, 200)
        response = self.site.post_form(preview.page().selection_at(x, 0), text)
        self.assertEqual(response.status, 201, response.body)
        notes = response.page().notes
        self.assertEqual(len(notes), 1)
        return notes[0]

    def _report_count(self) -> int:
        with closing(sqlite3.connect(self.site.database)) as connection:
            return connection.execute('SELECT count(*) FROM reports').fetchone()[0]

    def test_issue_and_read(self) -> None:
        proof_id = self.site.sample('unfolded_faces.json')
        first = self._annotate(proof_id, 'front', 0, '正面封面线')
        rear_text = '背面套线 <偏左> & 需改\n二次核对'
        second = self._annotate(proof_id, 'back', 2, rear_text)
        third = self._annotate(proof_id, 'front', 0, '同格正面第二笔')
        self.assertEqual([note[1:] for note in (first, second, third)], [
            (0, 0, 'front', '正面封面线'), (0, 0, 'back', rear_text),
            (0, 0, 'front', '同格正面第二笔'),
        ])
        unfolded = self.site.unfolded(proof_id)
        self.assertEqual(unfolded.status, 200)
        self.assertEqual(unfolded.page().notes, [first, third, second])
        self.assertIn('&lt;偏左&gt; &amp; 需改', unfolded.body)
        first_issue = self.site.issue(proof_id)
        self.assertEqual(first_issue.status, 201, first_issue.body)
        first_page = first_issue.page()
        self.assertEqual(first_page.report_proof_id, proof_id)
        self.assertEqual(first_page.notes, [first, second, third])
        self.assertIsNotNone(first_page.report_id)
        self.assertIn('原纸 3 × 1 格', first_issue.body)
        self.assertIn('原件无折线', first_issue.body)
        initial_pickup = self.site.report(first_page.report_id)
        self.assertEqual(initial_pickup.status, 200)
        self.assertEqual(initial_pickup.body, first_issue.body)

        late = self._annotate(proof_id, 'front', 2, '签出后补记右列裁切线')
        self.assertEqual(late[1:], (2, 0, 'front', '签出后补记右列裁切线'))
        second_issue = self.site.issue(proof_id)
        self.assertEqual(second_issue.status, 201, second_issue.body)
        second_page = second_issue.page()
        self.assertEqual(second_page.report_proof_id, proof_id)
        self.assertIsNotNone(second_page.report_id)
        self.assertNotEqual(first_page.report_id, second_page.report_id)
        self.assertEqual(second_page.notes, [first, second, third, late])
        self.assertEqual(self.site.report(first_page.report_id).body, first_issue.body)

        self.site.restart()
        first_reopened = self.site.report(first_page.report_id)
        second_reopened = self.site.report(second_page.report_id)
        self.assertEqual((first_reopened.status, second_reopened.status), (200, 200))
        self.assertEqual(first_reopened.body, first_issue.body)
        self.assertEqual(second_reopened.body, second_issue.body)
        self.assertEqual(sorted(self.site.unfolded(proof_id).page().notes), [first, second, third, late])
        self.assertEqual(self._report_count(), 2)

    def test_empty_release(self) -> None:
        proof_id = self.site.sample('double_fold.json')
        issued = self.site.issue(proof_id)
        self.assertEqual(issued.status, 201)
        snapshot = issued.page()
        self.assertEqual(snapshot.report_proof_id, proof_id)
        self.assertEqual(snapshot.notes, [])
        self.assertIn('签出时没有正式批注', issued.body)
        self.assertLess(issued.body.index('x=2'), issued.body.index('x=1'))
        self.assertEqual(self.site.report(snapshot.report_id).body, issued.body)

    def test_unknown_unfold_or_issue(self) -> None:
        known = self.site.sample('unfolded_faces.json')
        unknown = known + 100
        unfolded = self.site.unfolded(unknown)
        self.assertEqual(unfolded.status, 404)
        self.assertEqual(unfolded.page().forms, [])
        response = self.site.request('POST', '/reports', {'proof_id': str(unknown)})
        self.assertEqual(response.status, 404)
        self.assertIsNone(response.page().report_id)
        self.assertEqual(self._report_count(), 0)

    def test_save_failure(self) -> None:
        proof_id = self.site.sample('unfolded_faces.json')
        earlier = self.site.issue(proof_id)
        self.assertEqual(earlier.status, 201)
        self.assertEqual(self._report_count(), 1)
        with closing(sqlite3.connect(self.site.database)) as connection:
            connection.execute('''
                CREATE TRIGGER stop_report BEFORE INSERT ON reports
                BEGIN SELECT RAISE(ABORT, 'report write rejected'); END
            ''')
        rejected = self.site.issue(proof_id)
        self.assertEqual(rejected.status, 500)
        self.assertIn('校样单签存失败', rejected.body)
        self.assertIsNone(rejected.page().report_id)
        self.assertEqual(self._report_count(), 1)
        self.assertEqual(self.site.report(earlier.page().report_id).body, earlier.body)
        with closing(sqlite3.connect(self.site.database)) as connection:
            connection.execute('DROP TRIGGER stop_report')
        retry = self.site.issue(proof_id)
        self.assertEqual(retry.status, 201)
        self.assertNotEqual(retry.page().report_id, earlier.page().report_id)
        self.assertEqual(self._report_count(), 2)

    def test_unknown_report(self) -> None:
        self.assertEqual(self.site.report(1).status, 404)
        proof_id = self.site.sample('unfolded_faces.json')
        issued = self.site.issue(proof_id)
        self.assertEqual(issued.status, 201)
        existing_id = issued.page().report_id
        missing = self.site.report(existing_id + 100)
        self.assertEqual(missing.status, 404)
        self.assertIn('签出单不存在', missing.body)
        self.assertIsNone(missing.page().report_id)
        self.assertEqual(self.site.report(existing_id).body, issued.body)
        self.assertEqual(self._report_count(), 1)
