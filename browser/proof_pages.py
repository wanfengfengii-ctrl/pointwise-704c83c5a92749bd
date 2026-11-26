import sqlite3
from typing import Mapping

from browser.fold_controls import ViewSpec, parse_view, render_fold_controls, validate_view_step
from browser.grid_view import render_grid
from browser.html_pages import PageResponse, page, problem
from fold.layers import build_layers
from fold.visibility import VisibleSurface, visible_surface
from sheet.proofs import FrozenProof, get_proof


def render_proof_page(proof: FrozenProof, view: ViewSpec, surface: VisibleSurface) -> PageResponse:
    controls = render_fold_controls(view, len(proof.folds.creases))
    grid = render_grid(surface, view, proof.ink)
    title = f'校样 {proof.proof_id} · 第 {view.step} 步 · {view.observation.label}'
    return page(title, f'''
{controls}
{grid}
<p><a href="/proofs/{proof.proof_id}/unfolded">查看双面展开图</a>
<a href="/proofs/{proof.proof_id}/cut-plans?step={view.step}&side={view.observation.value}">进入试裁台</a></p>
''')


def view_proof(
    connection: sqlite3.Connection, proof_id: int, parameters: Mapping[str, str],
) -> PageResponse:
    proof = get_proof(connection, proof_id)
    if proof is None:
        return problem(404, '校样不存在')
    try:
        view = parse_view(proof_id, parameters)
        validate_view_step(view, len(proof.folds.creases))
    except ValueError as error:
        return problem(400, str(error))
    layers = build_layers(proof.stock, proof.cutouts, proof.folds, view.step)
    return render_proof_page(proof, view, visible_surface(layers, view.observation))
