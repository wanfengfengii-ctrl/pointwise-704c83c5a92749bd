import sqlite3
from dataclasses import dataclass

from cut.store import (
    CutPlan,
    CutStep,
    Draft,
    PlanStep,
    insert_cut_holes,
    insert_draft,
    insert_plan,
    load_draft,
    replace_draft_steps,
    shared_holes,
)
from fold.layers import FoldedLayers, build_layers
from fold.visibility import Observation, visible_at
from sheet.cutouts import Cutouts
from sheet.proofs import FrozenProof, get_proof
from sheet.stock import Cell, Face


class UnknownDraft(LookupError):
    pass


class StaleRevision(LookupError):
    pass


class EmptyCell(ValueError):
    pass


class PaperConflict(LookupError):
    def __init__(self, step_number: int) -> None:
        super().__init__(f'纸况冲突：第 {step_number} 步')
        self.step_number = step_number


class NoSteps(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TrialPreview:
    visible: tuple[Cell, Face]
    exposed: tuple[Cell, Face] | None


def _layers(proof: FrozenProof, holes: frozenset[Cell], step: int) -> FoldedLayers:
    return build_layers(proof.stock, Cutouts(proof.cutouts.holes | holes), proof.folds, step)


def _sighting(
    proof: FrozenProof, holes: frozenset[Cell], step: int,
    side: Observation, display: Cell,
) -> tuple[Cell, Face] | None:
    visible = visible_at(_layers(proof, holes, step), side, display)
    return None if visible is None else (visible.origin, visible.face)


def trial_preview(
    proof: FrozenProof, holes: frozenset[Cell], step: int,
    side: Observation, display: Cell,
) -> TrialPreview:
    visible = _sighting(proof, holes, step, side, display)
    if visible is None:
        raise EmptyCell('所选位置没有可试裁的纸面')
    origin, _face = visible
    exposed = _sighting(proof, holes | {origin}, step, side, display)
    return TrialPreview(visible, exposed)


def open_draft(connection: sqlite3.Connection, proof_id: int) -> Draft | None:
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        proof = get_proof(connection, proof_id)
        if proof is None:
            return None
        holes = shared_holes(connection, proof_id)
        return insert_draft(connection, proof_id, holes)


def append_trial_step(
    connection: sqlite3.Connection, draft_id: int, revision: str,
    step: int, side: Observation, display: Cell,
) -> Draft:
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        draft = load_draft(connection, draft_id)
        if draft is None:
            raise UnknownDraft('草稿不存在')
        if draft.revision != revision:
            raise StaleRevision('草稿已有更新，请从草稿页重新查看')
        proof = get_proof(connection, draft.proof_id)
        if proof is None:
            raise UnknownDraft('草稿所属校样不存在')
        preview = trial_preview(proof, draft.holes, step, side, display)
        origin, face = preview.visible
        new_step = CutStep(step, side, display, origin, face, preview.exposed)
        return replace_draft_steps(connection, draft, draft.steps + (new_step,))


def issue_cut_plan(
    connection: sqlite3.Connection, draft_id: int, revision: str,
) -> CutPlan:
    with connection:
        # Serialize against other issuers before reading shared paper state.
        connection.execute('BEGIN IMMEDIATE')
        draft = load_draft(connection, draft_id)
        if draft is None:
            raise UnknownDraft('草稿不存在')
        if draft.revision != revision:
            raise StaleRevision('草稿已有更新，请从草稿页重新查看')
        if not draft.steps:
            raise NoSteps('草稿尚无试裁步骤')
        proof = get_proof(connection, draft.proof_id)
        if proof is None:
            raise UnknownDraft('草稿所属校样不存在')
        holes = set(shared_holes(connection, draft.proof_id))
        results: list[PlanStep] = []
        added: list[Cell] = []
        for order, step in enumerate(draft.steps, 1):
            if step.origin in holes:
                sighting = _sighting(
                    proof, frozenset(holes), step.step, step.side, step.display,
                )
                if sighting != step.exposed:
                    raise PaperConflict(order)
                outcome = 'prior'
            else:
                sighting = _sighting(
                    proof, frozenset(holes), step.step, step.side, step.display,
                )
                if sighting != (step.origin, step.face):
                    raise PaperConflict(order)
                holes.add(step.origin)
                after = _sighting(
                    proof, frozenset(holes), step.step, step.side, step.display,
                )
                if after != step.exposed:
                    raise PaperConflict(order)
                added.append(step.origin)
                outcome = 'new'
            results.append(PlanStep(
                step.step, step.side, step.display, step.origin, step.face,
                step.exposed, outcome,
            ))
        plan = CutPlan(None, draft.proof_id, tuple(results))
        if added:
            insert_cut_holes(connection, draft.proof_id, tuple(added))
        plan_id = insert_plan(connection, plan)
    return CutPlan(plan_id, plan.proof_id, plan.steps)
