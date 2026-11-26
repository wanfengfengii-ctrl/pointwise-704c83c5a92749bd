from dataclasses import dataclass
import json
import secrets
import sqlite3

from fold.visibility import Observation
from sheet.proof_store import MAX_ROW_ID
from sheet.stock import Cell, Face


@dataclass(frozen=True, slots=True)
class CutStep:
    """A reviewed trial cut inside one draft."""

    step: int
    side: Observation
    display: Cell
    origin: Cell
    face: Face
    exposed: tuple[Cell, Face] | None


@dataclass(frozen=True, slots=True)
class Draft:
    draft_id: int
    proof_id: int
    revision: str
    snapshot: frozenset[Cell]
    steps: tuple[CutStep, ...]

    @property
    def holes(self) -> frozenset[Cell]:
        return self.snapshot | frozenset(step.origin for step in self.steps)


@dataclass(frozen=True, slots=True)
class PlanStep:
    step: int
    side: Observation
    display: Cell
    origin: Cell
    face: Face
    exposed: tuple[Cell, Face] | None
    outcome: str  # 'new' or 'prior'


@dataclass(frozen=True, slots=True)
class CutPlan:
    plan_id: int | None
    proof_id: int
    steps: tuple[PlanStep, ...]


def initialize_cut_plans(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS cut_holes (
            proof_id INTEGER NOT NULL REFERENCES proofs(id),
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            PRIMARY KEY (proof_id, x, y)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS cut_drafts (
            id INTEGER PRIMARY KEY,
            proof_id INTEGER NOT NULL REFERENCES proofs(id),
            revision TEXT NOT NULL,
            snapshot TEXT NOT NULL,
            steps TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS cut_plans (
            id INTEGER PRIMARY KEY,
            proof_id INTEGER NOT NULL REFERENCES proofs(id),
            payload TEXT NOT NULL
        )
    ''')


def new_revision() -> str:
    return secrets.token_urlsafe(18)


def _pack_cell(cell: Cell) -> list[int]:
    return [cell.x, cell.y]


def _unpack_cell(value: object) -> Cell:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('纸格记录无效')
    return Cell(value[0], value[1])


def _pack_exposed(exposed: tuple[Cell, Face] | None) -> dict | None:
    if exposed is None:
        return None
    cell, face = exposed
    return {'x': cell.x, 'y': cell.y, 'face': face.value}


def _unpack_exposed(value: object) -> tuple[Cell, Face] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('露面记录无效')
    return Cell(value['x'], value['y']), Face(value['face'])


def pack_step(step: CutStep | PlanStep) -> dict:
    payload = {
        'step': step.step,
        'side': step.side.value,
        'display': _pack_cell(step.display),
        'origin': _pack_cell(step.origin),
        'face': step.face.value,
        'exposed': _pack_exposed(step.exposed),
    }
    if isinstance(step, PlanStep):
        payload['outcome'] = step.outcome
    return payload


def unpack_step(payload: dict) -> CutStep:
    return CutStep(
        payload['step'],
        Observation(payload['side']),
        _unpack_cell(payload['display']),
        _unpack_cell(payload['origin']),
        Face(payload['face']),
        _unpack_exposed(payload['exposed']),
    )


def unpack_plan_step(payload: dict) -> PlanStep:
    step = unpack_step(payload)
    return PlanStep(
        step.step, step.side, step.display, step.origin, step.face, step.exposed,
        payload['outcome'],
    )


def shared_holes(connection: sqlite3.Connection, proof_id: int) -> frozenset[Cell]:
    rows = connection.execute(
        'SELECT x, y FROM cut_holes WHERE proof_id = ?', (proof_id,),
    )
    return frozenset(Cell(x, y) for x, y in rows)


def load_draft(connection: sqlite3.Connection, draft_id: int) -> Draft | None:
    if not 0 < draft_id <= MAX_ROW_ID:
        return None
    row = connection.execute(
        'SELECT proof_id, revision, snapshot, steps FROM cut_drafts WHERE id = ?',
        (draft_id,),
    ).fetchone()
    if row is None:
        return None
    proof_id, revision, snapshot, steps = row
    return Draft(
        draft_id,
        proof_id,
        revision,
        frozenset(_unpack_cell(cell) for cell in json.loads(snapshot)),
        tuple(unpack_step(payload) for payload in json.loads(steps)),
    )


def insert_draft(
    connection: sqlite3.Connection, proof_id: int, snapshot: frozenset[Cell],
) -> Draft:
    revision = new_revision()
    serialized = json.dumps(
        [_pack_cell(cell) for cell in sorted(snapshot, key=lambda c: (c.y, c.x))],
        separators=(',', ':'),
    )
    cursor = connection.execute(
        'INSERT INTO cut_drafts (proof_id, revision, snapshot, steps) VALUES (?, ?, ?, ?)',
        (proof_id, revision, serialized, '[]'),
    )
    return Draft(cursor.lastrowid, proof_id, revision, snapshot, ())


def replace_draft_steps(
    connection: sqlite3.Connection, draft: Draft, steps: tuple[CutStep, ...],
) -> Draft:
    revision = new_revision()
    connection.execute(
        'UPDATE cut_drafts SET revision = ?, steps = ? WHERE id = ?',
        (
            revision,
            json.dumps([pack_step(step) for step in steps], ensure_ascii=False, separators=(',', ':')),
            draft.draft_id,
        ),
    )
    return Draft(
        draft.draft_id, draft.proof_id, revision, draft.snapshot, steps,
    )


def insert_cut_holes(connection: sqlite3.Connection, proof_id: int, cells: tuple[Cell, ...]) -> None:
    connection.executemany(
        'INSERT INTO cut_holes (proof_id, x, y) VALUES (?, ?, ?)',
        [(proof_id, cell.x, cell.y) for cell in cells],
    )


def insert_plan(connection: sqlite3.Connection, plan: CutPlan) -> int:
    payload = {
        'steps': [pack_step(step) for step in plan.steps],
    }
    cursor = connection.execute(
        'INSERT INTO cut_plans (proof_id, payload) VALUES (?, ?)',
        (plan.proof_id, json.dumps(payload, ensure_ascii=False, separators=(',', ':'))),
    )
    return cursor.lastrowid


def load_plan(connection: sqlite3.Connection, plan_id: int) -> CutPlan | None:
    if not 0 < plan_id <= MAX_ROW_ID:
        return None
    row = connection.execute(
        'SELECT proof_id, payload FROM cut_plans WHERE id = ?', (plan_id,),
    ).fetchone()
    if row is None:
        return None
    proof_id, serialized = row
    payload = json.loads(serialized)
    return CutPlan(
        plan_id,
        proof_id,
        tuple(unpack_plan_step(item) for item in payload['steps']),
    )
