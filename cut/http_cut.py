import sqlite3
from typing import Mapping

from browser.fold_controls import ViewSpec, parse_view, validate_view_step
from browser.html_pages import PageResponse, problem
from cut.pages import render_cut_plan, render_draft, render_trial_desk
from cut.plans import (
    EmptyCell,
    NoSteps,
    PaperConflict,
    StaleRevision,
    UnknownDraft,
    append_trial_step,
    issue_cut_plan,
    open_draft,
)
from cut.store import load_draft, load_plan, shared_holes
from fold.visibility import Observation
from sheet.proofs import get_proof
from sheet.stock import Cell


def _int_field(fields: Mapping[str, str], name: str, label: str) -> int:
    raw = fields.get(name)
    if raw is None:
        raise ValueError(f'缺少字段 {name}')
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f'{label}须为整数') from error


def _view(proof, fields: Mapping[str, str]) -> ViewSpec:
    view = parse_view(proof.proof_id, fields)
    validate_view_step(view, len(proof.folds.creases))
    return view


def view_trial_desk(
    connection: sqlite3.Connection, proof_id: int, fields: Mapping[str, str],
) -> PageResponse:
    proof = get_proof(connection, proof_id)
    if proof is None:
        return problem(404, '校样不存在')
    try:
        view = _view(proof, fields)
    except ValueError as error:
        return problem(400, str(error))
    holes = shared_holes(connection, proof_id)
    return render_trial_desk(proof, view, holes)


def open_draft_response(connection: sqlite3.Connection, fields: Mapping[str, str]) -> PageResponse:
    proof_id = _int_field(fields, 'proof_id', '校样号')
    if proof_id <= 0:
        raise ValueError('校样号须为正整数')
    draft = open_draft(connection, proof_id)
    if draft is None:
        return problem(404, '校样不存在')
    proof = get_proof(connection, proof_id)
    view = ViewSpec(proof_id, 0, Observation.FRONT)
    return render_draft(proof, draft, view, 201)


def view_draft(
    connection: sqlite3.Connection, draft_id: int, fields: Mapping[str, str],
) -> PageResponse:
    draft = load_draft(connection, draft_id)
    if draft is None:
        return problem(404, '草稿不存在')
    proof = get_proof(connection, draft.proof_id)
    if proof is None:
        return problem(404, '草稿所属校样不存在')
    try:
        view = _view(proof, fields)
    except ValueError as error:
        return problem(400, str(error))
    return render_draft(proof, draft, view)


def append_step_response(
    connection: sqlite3.Connection, draft_id: int, fields: Mapping[str, str],
) -> PageResponse:
    revision = fields.get('revision')
    if revision is None:
        raise ValueError('缺少字段 revision')
    try:
        step = int(fields['step'])
        side = Observation(fields['side'])
        display = Cell(int(fields['x']), int(fields['y']))
    except KeyError as error:
        raise ValueError(f'选格缺少字段 {error.args[0]}') from error
    except ValueError as error:
        raise ValueError('折步、视向与显示格须有效') from error
    draft = load_draft(connection, draft_id)
    if draft is None:
        return problem(404, '草稿不存在')
    proof = get_proof(connection, draft.proof_id)
    if proof is None:
        return problem(404, '草稿所属校样不存在')
    view = ViewSpec(proof.proof_id, step, side)
    try:
        validate_view_step(view, len(proof.folds.creases))
        draft = append_trial_step(connection, draft_id, revision, step, side, display)
    except UnknownDraft as error:
        return problem(404, str(error))
    except StaleRevision as error:
        return problem(409, str(error))
    except EmptyCell as error:
        return problem(422, str(error))
    except sqlite3.Error:
        return problem(500, '试裁草稿保存失败')
    return render_draft(proof, draft, view)


def issue_response(
    connection: sqlite3.Connection, draft_id: int, fields: Mapping[str, str],
) -> PageResponse:
    revision = fields.get('revision')
    if revision is None:
        raise ValueError('缺少字段 revision')
    try:
        plan = issue_cut_plan(connection, draft_id, revision)
    except UnknownDraft as error:
        return problem(404, str(error))
    except StaleRevision as error:
        return problem(409, str(error))
    except NoSteps as error:
        return problem(409, str(error))
    except PaperConflict as error:
        return problem(409, str(error))
    except sqlite3.Error:
        return problem(500, '试裁单签存失败')
    proof = get_proof(connection, plan.proof_id)
    if proof is None:
        return problem(500, '试裁单所属校样读取失败')
    return render_cut_plan(proof, plan, 201)


def read_cut_plan_response(connection: sqlite3.Connection, plan_id: int) -> PageResponse:
    plan = load_plan(connection, plan_id)
    if plan is None:
        return problem(404, '试裁单不存在')
    proof = get_proof(connection, plan.proof_id)
    if proof is None:
        return problem(404, '试裁单所属校样不存在')
    return render_cut_plan(proof, plan)
