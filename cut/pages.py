from dataclasses import dataclass
from html import escape
from urllib.parse import urlencode

from browser.fold_controls import ViewSpec
from browser.html_pages import PageResponse, page
from cut.store import CutPlan, CutStep, Draft, PlanStep
from fold.layers import FoldedLayers, build_layers
from fold.visibility import Observation, VisibleCell, visible_surface
from sheet.cutouts import Cutouts
from sheet.proofs import FrozenProof
from sheet.stock import Cell, Face


def _mark(proof: FrozenProof, cell: Cell, face: Face) -> str:
    mark = proof.ink.mark_at(cell, face)
    return escape(mark) if mark else '<span class="muted">未印图记</span>'


def _face_label(face: Face) -> str:
    return face.label


def _cut_controls(proof: FrozenProof, view: ViewSpec, base: str) -> str:
    steps = ''.join(
        _cut_link(
            '原纸' if step == 0 else f'第 {step} 折',
            ViewSpec(view.proof_id, step, view.observation), view, base,
        )
        for step in range(len(proof.folds.creases) + 1)
    )
    sides = ''.join(
        _cut_link(side.label, ViewSpec(view.proof_id, view.step, side), view, base)
        for side in Observation
    )
    return (
        f'<nav class="controls" aria-label="折步">{steps}</nav>'
        f'<nav class="controls" aria-label="观察面">{sides}</nav>'
    )


def _cut_link(label: str, target: ViewSpec, current: ViewSpec, base: str) -> str:
    query = urlencode({'step': target.step, 'side': target.observation.value})
    selected = ' aria-current="page"' if target == current else ''
    return f'<a href="{escape(f"{base}?{query}", quote=True)}"{selected}>{escape(label)}</a>'


def _layers(proof: FrozenProof, holes: frozenset[Cell], step: int) -> FoldedLayers:
    return build_layers(proof.stock, Cutouts(proof.cutouts.holes | holes), proof.folds, step)


@dataclass(frozen=True, slots=True)
class _GridCell:
    display: Cell
    visible: VisibleCell | None


def _grid_cells(proof: FrozenProof, holes: frozenset[Cell], view: ViewSpec) -> list[_GridCell]:
    surface = visible_surface(_layers(proof, holes, view.step), view.observation)
    return [
        _GridCell(Cell(x, y), surface.cells.get(Cell(x, y)))
        for y in range(surface.frame.height)
        for x in range(surface.frame.width)
    ]


def _shared_grid(
    proof: FrozenProof, holes: frozenset[Cell], view: ViewSpec,
) -> str:
    surface = visible_surface(_layers(proof, holes, view.step), view.observation)
    columns = ''.join(f'<th scope="col">{x}</th>' for x in range(surface.frame.width))
    rows = []
    for y in range(surface.frame.height):
        cells = []
        for x in range(surface.frame.width):
            display = Cell(x, y)
            visible = surface.cells.get(display)
            if visible is None:
                cells.append(
                    f'<td class="empty" data-display-x="{x}" data-display-y="{y}">'
                    '<p class="cell-mark">空处</p></td>'
                )
            else:
                cells.append(
                    f'<td data-display-x="{x}" data-display-y="{y}"'
                    f' data-origin-x="{visible.origin.x}" data-origin-y="{visible.origin.y}"'
                    f' data-face="{visible.face.value}">'
                    f'<p class="cell-mark">{_mark(proof, visible.origin, visible.face)}</p></td>'
                )
        rows.append(f'<tr><th scope="row">{y}</th>{"".join(cells)}</tr>')
    return (
        '<div class="table-scroll"><table class="paper-grid">'
        '<caption>共享纸况 · 折后显示格 · 列 x / 行 y</caption>'
        f'<thead><tr><th scope="col">y / x</th>{columns}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _draft_grid(
    proof: FrozenProof, holes: frozenset[Cell], view: ViewSpec, draft: Draft,
) -> str:
    surface = visible_surface(_layers(proof, holes, view.step), view.observation)
    columns = ''.join(f'<th scope="col">{x}</th>' for x in range(surface.frame.width))
    rows = []
    for y in range(surface.frame.height):
        cells = []
        for x in range(surface.frame.width):
            display = Cell(x, y)
            visible = surface.cells.get(display)
            if visible is None:
                cells.append(
                    f'<td class="empty" data-display-x="{x}" data-display-y="{y}">'
                    '<p class="cell-mark">空处</p></td>'
                )
                continue
            fields = ''.join(
                f'<input type="hidden" name="{name}" value="{escape(value, quote=True)}">'
                for name, value in {
                    'revision': draft.revision,
                    'step': str(view.step),
                    'side': view.observation.value,
                    'x': str(x),
                    'y': str(y),
                }.items()
            )
            cells.append(
                f'<td data-display-x="{x}" data-display-y="{y}"'
                f' data-origin-x="{visible.origin.x}" data-origin-y="{visible.origin.y}"'
                f' data-face="{visible.face.value}">'
                f'<p class="cell-mark">{_mark(proof, visible.origin, visible.face)}</p>'
                f'<form method="post" action="/cut-plans/{draft.draft_id}/steps">'
                f'{fields}<button type="submit">试裁此格</button></form></td>'
            )
        rows.append(f'<tr><th scope="row">{y}</th>{"".join(cells)}</tr>')
    return (
        '<div class="table-scroll"><table class="paper-grid">'
        '<caption>草稿纸况 · 折后显示格 · 列 x / 行 y</caption>'
        f'<thead><tr><th scope="col">y / x</th>{columns}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _exposed_attributes(exposed: tuple[Cell, Face] | None) -> str:
    if exposed is None:
        return ' data-exposed-empty="1"'
    cell, face = exposed
    return (
        f' data-exposed-x="{cell.x}" data-exposed-y="{cell.y}"'
        f' data-exposed-face="{face.value}"'
    )


def _trial_row(
    order: int, step: CutStep | PlanStep, proof: FrozenProof, outcome: str | None = None,
) -> str:
    exposed = step.exposed
    if exposed is None:
        exposed_text = '露空'
    else:
        cell, face = exposed
        exposed_text = (
            f'原格 ({cell.x}, {cell.y}) · {_face_label(face)} · '
            f'{_mark(proof, cell, face)}'
        )
    extra = f' data-outcome="{outcome}"' if outcome is not None else ''
    outcome_text = ''
    if outcome == 'new':
        outcome_text = '<p class="outcome">新增裁口</p>'
    elif outcome == 'prior':
        outcome_text = '<p class="outcome">先前完成</p>'
    return f'''<li class="cut-step" data-order="{order}"
 data-fold-step="{step.step}" data-side="{step.side.value}"
 data-display-x="{step.display.x}" data-display-y="{step.display.y}"
 data-origin-x="{step.origin.x}" data-origin-y="{step.origin.y}"
 data-face="{step.face.value}"{_exposed_attributes(exposed)}{extra}>
<p>第 {order} 步 · 折步 {step.step} · {step.side.label} · 显示格 ({step.display.x}, {step.display.y})</p>
<p>所裁原格 ({step.origin.x}, {step.origin.y}) · {_face_label(step.face)} · {_mark(proof, step.origin, step.face)}</p>
<p class="exposed">裁后{exposed_text}</p>
{outcome_text}
</li>'''


def _trial_list(proof: FrozenProof, steps: tuple[CutStep | PlanStep, ...]) -> str:
    if not steps:
        return '<p class="muted">尚无试裁步骤。</p>'
    rows = ''.join(
        _trial_row(order, step, proof, getattr(step, 'outcome', None))
        for order, step in enumerate(steps, 1)
    )
    return f'<ol class="cut-steps">{rows}</ol>'


def render_trial_desk(
    proof: FrozenProof, view: ViewSpec, holes: frozenset[Cell],
) -> PageResponse:
    proof_id = proof.proof_id
    controls = _cut_controls(proof, view, f'/proofs/{proof_id}/cut-plans')
    shared = proof.cutouts.holes | holes
    holes_text = '、'.join(
        f'({cell.x}, {cell.y})' for cell in sorted(shared, key=lambda cell: (cell.y, cell.x))
    ) or '无'
    return page(f'校样 {proof_id} · 试裁台 · 第 {view.step} 步 · {view.observation.label}', f'''
<p><a href="/proofs/{proof_id}">返回原校样</a></p>
{controls}
<h2>当前共享纸况</h2>
<p class="shared-holes" data-shared-holes="{len(shared)}">已裁原格：{escape(holes_text)}</p>
{_shared_grid(proof, holes, view)}
<h2>开启试裁草稿</h2>
<form method="post" action="/cut-plans">
<input type="hidden" name="proof_id" value="{proof_id}">
<button type="submit">开启草稿</button>
</form>
''')


def _draft_heading(draft: Draft, proof: FrozenProof, view: ViewSpec) -> str:
    return f'草稿 #{draft.draft_id} · 校样 {draft.proof_id} · 第 {view.step} 步 · {view.observation.label}'


def _issue_form(draft: Draft) -> str:
    if not draft.steps:
        return '<p class="muted">试裁一步后可签出。</p>'
    return f'''<form method="post" action="/cut-plans/{draft.draft_id}/issue">
<input type="hidden" name="revision" value="{escape(draft.revision, quote=True)}">
<button type="submit">签出试裁单</button>
</form>'''


def render_draft(
    proof: FrozenProof, draft: Draft, view: ViewSpec, status: int = 200,
) -> PageResponse:
    controls = _cut_controls(proof, view, f'/cut-plans/{draft.draft_id}')
    return page(_draft_heading(draft, proof, view), f'''
<article data-draft-id="{draft.draft_id}" data-proof-id="{draft.proof_id}">
<p><a href="/proofs/{draft.proof_id}">返回原校样</a>
<a href="/proofs/{draft.proof_id}/cut-plans">试裁台</a>
<a href="/cut-plans/{draft.draft_id}">草稿 #{draft.draft_id}</a></p>
{controls}
<h2>本页选格试裁</h2>
{_draft_grid(proof, draft.holes, view, draft)}
<h2>草稿步骤</h2>
{_trial_list(proof, draft.steps)}
<div class="actions">{_issue_form(draft)}</div>
</article>
''', status)


def render_cut_plan(proof: FrozenProof, plan: CutPlan, status: int = 200) -> PageResponse:
    rows = ''.join(
        _trial_row(order, step, proof, step.outcome)
        for order, step in enumerate(plan.steps, 1)
    )
    return page(f'试裁单 #{plan.plan_id}', f'''
<article data-cut-plan-id="{plan.plan_id}" data-proof-id="{plan.proof_id}">
<h2>冻结来源</h2>
<p><a href="/proofs/{plan.proof_id}">校样 {plan.proof_id}</a> · 原纸 {proof.stock.width} × {proof.stock.height} 格</p>
<h2>逐步裁口</h2>
<ol class="cut-steps">{rows}</ol>
</article>
<p><a href="/cut-reports/{plan.plan_id}">领取此试裁单</a>
<a href="/proofs/{plan.proof_id}/cut-plans">返回试裁台</a></p>
''', status)
