from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tests.http_forms import HTTPWorkshop, read_sample


class CutPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.site = HTTPWorkshop(Path(directory.name) / 'workshop.sqlite3')
        self.addCleanup(self.site.close)
        self.proof_id = self.site.sample('cut_plans.json')

    def _count(self, table: str) -> int:
        with closing(sqlite3.connect(self.site.database)) as connection:
            return connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]  # noqa: S608

    def _holes(self) -> list[tuple[int, int]]:
        with closing(sqlite3.connect(self.site.database)) as connection:
            return connection.execute(
                'SELECT x, y FROM cut_holes WHERE proof_id = ? ORDER BY y, x', (self.proof_id,),
            ).fetchall()

    def _draft_with_front_step(self, display_y: int, step: int = 2) -> int:
        draft_id, reply = self.site.open_draft(self.proof_id)
        self.assertEqual(reply.status, 201, reply.body)
        page = self.site.draft(draft_id, step, 'front').page()
        response = self.site.trial_step(page.selection_at(0, display_y))
        self.assertEqual(response.status, 200, response.body)
        return draft_id

    def _issue_draft(self, draft_id: int) -> tuple:
        page = self.site.draft(draft_id, 2, 'front').page()
        response = self.site.post_form(page.issue_form())
        return response, response.page()

    def test_trial_desk_and_draft_isolation(self) -> None:
        desk = self.site.trial_desk(self.proof_id, 2, 'front')
        self.assertEqual(desk.status, 200)
        self.assertEqual(desk.page().marks, {(0, 0): 'B 背面', (0, 1): 'F 背面'})
        self.assertEqual(desk.page().shared_holes, 0)
        defaults = self.site.request('GET', f'/proofs/{self.proof_id}/cut-plans')
        self.assertEqual(defaults.status, 200)
        self.assertEqual(defaults.page().marks, {(x, y): mark for (x, y), mark in {
            (0, 0): 'A 正面', (1, 0): 'B 正面', (2, 0): 'C 正面', (3, 0): 'D 正面',
            (0, 1): 'E 正面', (1, 1): 'F 正面', (2, 1): 'G 正面', (3, 1): 'H 正面',
        }.items()})

        draft_id, opened = self.site.open_draft(self.proof_id)
        self.assertEqual(opened.status, 201, opened.body)
        self.assertEqual(opened.page().shared_holes, None)
        draft_page = self.site.draft(draft_id, 2, 'front').page()
        self.assertEqual(draft_page.marks, {(0, 0): 'B 背面', (0, 1): 'F 背面'})

        # Another draft issues B; the open draft keeps showing its own review paper.
        other_id = self._draft_with_front_step(0)
        issue_other, other_page = self._issue_draft(other_id)
        self.assertEqual(issue_other.status, 201, issue_other.body)
        self.assertEqual(other_page.cut_steps[0]['origin'], (1, 0))
        self.assertEqual(other_page.cut_steps[0]['exposed'], (2, 0, 'front'))

        still_draft = self.site.draft(draft_id, 2, 'front').page()
        self.assertEqual(still_draft.marks, {(0, 0): 'B 背面', (0, 1): 'F 背面'})
        self.assertEqual(still_draft.shared_holes, None)
        shared = self.site.trial_desk(self.proof_id, 2, 'front').page()
        self.assertEqual(shared.marks, {(0, 0): 'C 正面', (0, 1): 'F 背面'})
        self.assertEqual(shared.shared_holes, 1)

    def test_two_step_preview_and_new_cuts(self) -> None:
        draft_id, opened = self.site.open_draft(self.proof_id)
        self.assertEqual(opened.status, 201, opened.body)
        page = self.site.draft(draft_id, 2, 'front').page()

        first = self.site.trial_step(page.selection_at(0, 0))
        self.assertEqual(first.status, 200, first.body)
        steps = first.page().cut_steps
        self.assertEqual(len(steps), 1)
        self.assertEqual(
            (steps[0]['fold_step'], steps[0]['side'], steps[0]['display'],
             steps[0]['origin'], steps[0]['face'], steps[0]['exposed']),
            (2, 'front', (0, 0), (1, 0), 'back', (2, 0, 'front')),
        )

        second = self.site.trial_step(first.page().selection_at(0, 0))
        self.assertEqual(second.status, 200, second.body)
        steps = second.page().cut_steps
        self.assertEqual(len(steps), 2)
        self.assertEqual(
            (steps[1]['origin'], steps[1]['face'], steps[1]['exposed']),
            ((2, 0), 'front', (3, 0, 'back')),
        )

        # Before signing, the shared paper still shows B across another tab.
        outside = self.site.trial_desk(self.proof_id, 2, 'front').page()
        self.assertEqual(outside.marks[(0, 0)], 'B 背面')
        self.assertEqual(outside.shared_holes, 0)

        issued, plan = self._issue_draft(draft_id)
        self.assertEqual(issued.status, 201, issued.body)
        self.assertEqual(plan.cut_plan_proof_id, self.proof_id)
        self.assertIsNotNone(plan.cut_plan_id)
        self.assertEqual([step['outcome'] for step in plan.cut_steps], ['new', 'new'])
        self.assertEqual([step['origin'] for step in plan.cut_steps], [(1, 0), (2, 0)])
        self.assertEqual([step['exposed'] for step in plan.cut_steps],
                         [(2, 0, 'front'), (3, 0, 'back')])
        self.assertEqual(self._holes(), [(1, 0), (2, 0)])
        self.assertEqual(self.site.trial_desk(self.proof_id, 2, 'front').page().marks[(0, 0)],
                         'D 背面')

        picked = self.site.cut_plan(plan.cut_plan_id)
        self.assertEqual(picked.status, 200)
        self.assertEqual(picked.body, issued.body)

        self.site.restart()
        reopened = self.site.cut_plan(plan.cut_plan_id)
        self.assertEqual(reopened.status, 200)
        self.assertEqual(reopened.body, issued.body)
        self.assertEqual(self._count('cut_plans'), 1)

    def test_old_form_carryover_marks_prior_and_adds_only_c(self) -> None:
        # 甲 reviews the two-step plan before anyone else signs.
        draft_id, opened = self.site.open_draft(self.proof_id)
        self.assertEqual(opened.status, 201, opened.body)
        page = self.site.draft(draft_id, 2, 'front').page()
        page = self.site.trial_step(page.selection_at(0, 0)).page()
        self.site.trial_step(page.selection_at(0, 0))

        # 乙 signs away row 0 B and row 1 F before 甲 submits the old form.
        for display_y in (0, 1):
            other = self._draft_with_front_step(display_y)
            response, _ = self._issue_draft(other)
            self.assertEqual(response.status, 201, response.body)

        issued, plan = self._issue_draft(draft_id)
        self.assertEqual(issued.status, 201, issued.body)
        self.assertEqual([step['outcome'] for step in plan.cut_steps], ['prior', 'new'])
        self.assertEqual([step['origin'] for step in plan.cut_steps], [(1, 0), (2, 0)])
        self.assertEqual(plan.cut_steps[0]['exposed'], (2, 0, 'front'))
        self.assertEqual(plan.cut_steps[1]['exposed'], (3, 0, 'back'))
        # 本单只新增 C；行 1 的 F 早已是孔，故露出 G。
        self.assertEqual(sorted(self._holes()), [(1, 0), (1, 1), (2, 0)])
        row_one = self.site.trial_desk(self.proof_id, 2, 'front').page().marks
        self.assertEqual(row_one[(0, 1)], 'G 正面')

        picked = self.site.cut_plan(plan.cut_plan_id)
        self.assertEqual(picked.status, 200)
        self.assertIn('先前完成', picked.body)
        self.assertIn('新增裁口', picked.body)

    def test_conflict_at_first_step_when_both_already_cut(self) -> None:
        draft_id, opened = self.site.open_draft(self.proof_id)
        self.assertEqual(opened.status, 201, opened.body)
        page = self.site.draft(draft_id, 2, 'front').page()
        page = self.site.trial_step(page.selection_at(0, 0)).page()
        self.site.trial_step(page.selection_at(0, 0))

        # 乙 signs B then C; 甲's final exposure would still be D, but step 1 breaks.
        other = self._draft_with_front_step(0)
        other_page = self.site.draft(other, 2, 'front').page()
        second = self.site.trial_step(other_page.selection_at(0, 0))
        self.assertEqual(second.status, 200, second.body)
        response, other_plan = self._issue_draft(other)
        self.assertEqual(response.status, 201, response.body)
        self.assertEqual([step['origin'] for step in other_plan.cut_steps], [(1, 0), (2, 0)])

        holes_before = self._holes()
        plans_before = self._count('cut_plans')
        rejected, _ = self._issue_draft(draft_id)
        self.assertEqual(rejected.status, 409, rejected.body)
        self.assertIn('第 1 步', rejected.body)
        self.assertIsNone(rejected.page().cut_plan_id)
        self.assertEqual(self._holes(), holes_before)
        self.assertEqual(self._count('cut_plans'), plans_before)
        # The draft is untouched and can be reviewed again.
        self.assertEqual(len(self.site.draft(draft_id, 2, 'front').page().cut_steps), 2)

    def test_conflict_at_later_step_leaves_earlier_trial_only_in_draft(self) -> None:
        # 甲 opens the draft while shared paper is still uncut and trials row 1 F,
        # then row 0 B and C.
        draft_id, opened = self.site.open_draft(self.proof_id)
        self.assertEqual(opened.status, 201, opened.body)
        page = self.site.draft(draft_id, 2, 'front').page()
        page = self.site.trial_step(page.selection_at(0, 1)).page()
        page = self.site.trial_step(page.selection_at(0, 0)).page()
        self.site.trial_step(page.selection_at(0, 0))
        self.assertEqual(len(self.site.draft(draft_id, 2, 'front').page().cut_steps), 3)

        # 乙 now signs B and C on row 0.
        other = self._draft_with_front_step(0)
        other_page = self.site.draft(other, 2, 'front').page()
        self.site.trial_step(other_page.selection_at(0, 0))
        response, _ = self._issue_draft(other)
        self.assertEqual(response.status, 201, response.body)

        holes_before = self._holes()
        plans_before = self._count('cut_plans')
        rejected, _ = self._issue_draft(draft_id)
        self.assertEqual(rejected.status, 409, rejected.body)
        self.assertIn('第 2 步', rejected.body)
        self.assertEqual(self._holes(), holes_before)
        self.assertEqual(self._count('cut_plans'), plans_before)
        # Row 1 F was never added to shared paper; the draft still shows its trial.
        self.assertIn('F 背面', self.site.trial_desk(self.proof_id, 2, 'front').page().marks.values())
        draft_steps = self.site.draft(draft_id, 2, 'front').page().cut_steps
        self.assertEqual(draft_steps[0]['origin'], (1, 1))
        self.assertEqual(draft_steps[0]['exposed'], (2, 1, 'front'))

    def test_save_failure_rolls_back_and_retries(self) -> None:
        draft_id, opened = self.site.open_draft(self.proof_id)
        self.assertEqual(opened.status, 201, opened.body)
        page = self.site.draft(draft_id, 2, 'front').page()
        self.site.trial_step(page.selection_at(0, 0))

        holes_before = self._holes()
        plans_before = self._count('cut_plans')
        with closing(sqlite3.connect(self.site.database)) as connection:
            connection.execute('''
                CREATE TRIGGER stop_cut_plan BEFORE INSERT ON cut_plans
                BEGIN SELECT RAISE(ABORT, 'cut plan write rejected'); END
            ''')
        rejected, _ = self._issue_draft(draft_id)
        self.assertEqual(rejected.status, 500, rejected.body)
        self.assertIn('签存失败', rejected.body)
        self.assertEqual(self._holes(), holes_before)
        self.assertEqual(self._count('cut_plans'), plans_before)
        self.assertEqual(self.site.trial_desk(self.proof_id, 2, 'front').page().shared_holes, 0)

        with closing(sqlite3.connect(self.site.database)) as connection:
            connection.execute('DROP TRIGGER stop_cut_plan')
        retry, plan = self._issue_draft(draft_id)
        self.assertEqual(retry.status, 201, retry.body)
        self.assertIsNotNone(plan.cut_plan_id)
        self.assertEqual(self._holes(), [(1, 0)])
        self.assertEqual(self._count('cut_plans'), 1)

    def test_progressive_chain_exposes_and_empties(self) -> None:
        draft_id, opened = self.site.open_draft(self.proof_id)
        self.assertEqual(opened.status, 201, opened.body)
        page = self.site.draft(draft_id, 2, 'front').page()
        expected = [
            ((1, 0), 'back', (2, 0, 'front')),
            ((2, 0), 'front', (3, 0, 'back')),
            ((3, 0), 'back', (0, 0, 'front')),
            ((0, 0), 'front', None),
        ]
        for index, (origin, face, exposed) in enumerate(expected):
            response = self.site.trial_step(page.selection_at(0, 0))
            self.assertEqual(response.status, 200, response.body)
            page = response.page()
            step = page.cut_steps[index]
            self.assertEqual((step['origin'], step['face'], step['exposed']),
                             (origin, face, exposed))
        self.assertIn('露空', page.cut_steps[-1]['lines'][-1])

        issued, plan = self._issue_draft(draft_id)
        self.assertEqual(issued.status, 201, issued.body)
        self.assertEqual([step['outcome'] for step in plan.cut_steps], ['new'] * 4)
        self.assertIsNone(plan.cut_steps[-1]['exposed'])
        self.assertEqual(sorted(self._holes()), [(0, 0), (1, 0), (2, 0), (3, 0)])
        self.assertEqual(self.site.trial_desk(self.proof_id, 2, 'front').page().shared_holes, 4)

    def test_stale_revision_and_bad_requests(self) -> None:
        draft_id, opened = self.site.open_draft(self.proof_id)
        self.assertEqual(opened.status, 201, opened.body)
        page = self.site.draft(draft_id, 2, 'front').page()
        old_form = page.selection_at(0, 0)
        first = self.site.trial_step(old_form)
        self.assertEqual(first.status, 200, first.body)
        stale_step = self.site.trial_step(old_form)
        self.assertEqual(stale_step.status, 409, stale_step.body)
        self.assertEqual(stale_step.page().cut_steps, [])

        issue_v1 = first.page().issue_form()
        second = self.site.trial_step(first.page().selection_at(0, 0))
        self.assertEqual(second.status, 200, second.body)
        stale_issue = self.site.post_form(issue_v1)
        self.assertEqual(stale_issue.status, 409, stale_issue.body)
        self.assertIsNone(stale_issue.page().cut_plan_id)
        self.assertEqual(self._count('cut_plans'), 0)

        cases = [
            ('GET', f'/proofs/{self.proof_id + 100}/cut-plans', None, 404),
            ('GET', '/cut-plans/999', None, 404),
            ('GET', '/cut-reports/999', None, 404),
            ('POST', '/cut-plans', {'proof_id': str(self.proof_id + 100)}, 404),
            ('GET', '/cut-plans/not-a-number', None, 400),
            ('GET', f'/cut-plans/{draft_id}?step=3&side=front', None, 400),
            ('GET', f'/cut-plans/{draft_id}?side=left', None, 400),
            ('POST', '/cut-plans', {'proof_id': 'x'}, 400),
        ]
        for method, path, fields, status in cases:
            with self.subTest(path=path):
                reply = self.site.request(method, path, fields)
                self.assertEqual(reply.status, status, reply.body)

        revision = self.site.draft(draft_id, 2, 'front').page().selection_at(0, 0).fields['revision']
        empty = self.site.request('POST', f'/cut-plans/{draft_id}/steps', {
            'revision': revision, 'step': '2', 'side': 'front', 'x': '9', 'y': '0',
        })
        self.assertEqual(empty.status, 422, empty.body)
        missing = self.site.request('POST', f'/cut-plans/{draft_id}/steps', {
            'step': '2', 'side': 'front', 'x': '0', 'y': '0',
        })
        self.assertEqual(missing.status, 400, missing.body)

    def test_cut_plan_demo(self) -> None:
        # 甲 reviews two steps on the old form; 乙 signs B away first.
        draft_id, opened = self.site.open_draft(self.proof_id)
        page = self.site.draft(draft_id, 2, 'front').page()
        page = self.site.trial_step(page.selection_at(0, 0)).page()
        second = self.site.trial_step(page.selection_at(0, 0))
        preview = [
            {'origin': list(step['origin']), 'face': step['face'],
             'exposed': None if step['exposed'] is None else list(step['exposed'])}
            for step in second.page().cut_steps
        ]
        other = self._draft_with_front_step(0)
        other_issue, _ = self._issue_draft(other)
        self.assertEqual(other_issue.status, 201)
        issued, plan = self._issue_draft(draft_id)
        self.assertEqual(issued.status, 201, issued.body)

        # Separate proof: 甲 opens a two-step draft and reviews B、C first;
        # 乙 then signs B and C away, so 甲's old form is rejected at step 1.
        fresh_proof = self.site.sample('cut_plans.json')
        slow, _ = self.site.open_draft(fresh_proof)
        slow_page = self.site.draft(slow, 2, 'front').page()
        slow_page = self.site.trial_step(slow_page.selection_at(0, 0)).page()
        self.site.trial_step(slow_page.selection_at(0, 0))
        rival, _ = self.site.open_draft(fresh_proof)
        rival_page = self.site.draft(rival, 2, 'front').page()
        rival_page = self.site.trial_step(rival_page.selection_at(0, 0)).page()
        self.site.trial_step(rival_page.selection_at(0, 0))
        rival_issue, _ = self._issue_draft(rival)
        self.assertEqual(rival_issue.status, 201)
        conflict_issue, conflict_page = self._issue_draft(slow)
        with closing(sqlite3.connect(self.site.database)) as connection:
            shared_after = connection.execute(
                'SELECT count(*) FROM cut_holes WHERE proof_id = ?', (fresh_proof,),
            ).fetchone()[0]
        plan_count = self._count('cut_plans')

        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'cut-plans-carryover',
            'input': {'proof_id': self.proof_id, 'draft_id': draft_id},
            'expected': {
                'preview': [
                    {'origin': [1, 0], 'face': 'back', 'exposed': [2, 0, 'front']},
                    {'origin': [2, 0], 'face': 'front', 'exposed': [3, 0, 'back']},
                ],
                'outcomes': ['prior', 'new'],
                'conflict_status': 409,
            },
            'actual': {
                'preview': preview,
                'outcomes': [step['outcome'] for step in plan.cut_steps],
                'conflict_status': conflict_issue.status,
                'conflict_body_has_step_one': '第 1 步' in conflict_issue.body,
                'shared_holes_after_rejection': shared_after,
                'plans_total': plan_count,
            },
            'code_paths': [
                'cut/plans.py', 'cut/store.py', 'cut/pages.py', 'cut/http_cut.py',
                'browser/http_server.py', 'fold/layers.py', 'fold/visibility.py',
            ],
            'oracle': '旧页两步先裁 B 露 C、再裁 C 露 D；他人先签 B 时第一步记先前完成且仍露 C，'
                      '本单只新增 C。他人连 B、C 都签走时第一步验口失败，返回 409 且无新裁口。',
        }, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    unittest.main()
