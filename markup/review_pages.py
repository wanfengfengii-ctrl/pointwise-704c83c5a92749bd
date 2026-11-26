from html import escape
import sqlite3
from typing import Mapping

from browser.fold_controls import view_url
from browser.html_pages import PageResponse, page, problem
from browser.selection import parse_selection
from markup.annotations import Annotation, append_annotation, list_annotations
from markup.target import EmptySelection, UnknownProof, resolve_target
from markup.unfolded import UnfoldedReview, build_unfolded_review
from sheet.proofs import get_proof
from sheet.stock import Cell, Face


def _render_note(note: Annotation) -> str:
    return f'<p class="annotation-text" data-annotation-id="{note.annotation_id}">{escape(note.text)}</p>'


def submit_annotation(connection: sqlite3.Connection, fields: Mapping[str, str]) -> PageResponse:
    try:
        selection = parse_selection(fields)
        target = resolve_target(connection, selection)
        annotation = append_annotation(connection, target, fields.get('text', ''))
    except UnknownProof as error:
        return problem(404, str(error))
    except EmptySelection as error:
        return problem(422, str(error))
    except ValueError as error:
        return problem(400, str(error))
    except sqlite3.Error:
        return problem(500, '批注保存失败')
    x, y = annotation.origin.x, annotation.origin.y
    return page('批注已保存', f'''
<article class="receipt" data-x="{x}" data-y="{y}" data-face="{annotation.face.value}">
<h2>批注 #{annotation.annotation_id}</h2>
<p>原格 ({x}, {y}) · {annotation.face.label}</p>
{_render_note(annotation)}
</article>
<p><a href="{escape(view_url(selection.view), quote=True)}">返回原折页</a>
<a href="/proofs/{annotation.proof_id}/unfolded">查看展开图</a></p>
''', 201)


def _render_origin(review: UnfoldedReview, face: Face, cell: Cell) -> str:
    proof = review.proof
    if proof.cutouts.is_hole(cell):
        label = '贯穿孔'
    else:
        mark = proof.ink.mark_at(cell, face)
        label = escape(mark) if mark else '<span class="muted">未印图记</span>'
    notes = ''.join(
        f'<li><span>批注 #{note.annotation_id}</span>{_render_note(note)}</li>'
        for note in review.groups.get((face, cell), ())
    )
    annotations = f'<ol class="notes">{notes}</ol>' if notes else ''
    return (
        f'<td data-x="{cell.x}" data-y="{cell.y}" data-face="{face.value}">'
        f'<p class="cell-mark">{label}</p>{annotations}</td>'
    )


def _render_face(review: UnfoldedReview, face: Face) -> str:
    stock = review.proof.stock
    columns = ''.join(f'<th scope="col">{x}</th>' for x in range(stock.width))
    rows = []
    for y in range(stock.height):
        cells = ''.join(_render_origin(review, face, Cell(x, y)) for x in range(stock.width))
        rows.append(f'<tr><th scope="row">{y}</th>{cells}</tr>')
    return f'''
<section>
<h2>{face.label}</h2>
<div class="table-scroll"><table class="paper-grid">
<caption>{face.label}原纸格 · 列 x / 行 y</caption>
<thead><tr><th scope="col">y / x</th>{columns}</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>
</section>'''


def render_unfolded(review: UnfoldedReview) -> PageResponse:
    proof_id = review.proof.proof_id
    faces = ''.join(_render_face(review, face) for face in Face)
    return page(f'校样 {proof_id} · 展开图', f'''
{faces}
<div class="actions">
<a href="/proofs/{proof_id}">返回折页</a>
<form method="post" action="/reports">
<input type="hidden" name="proof_id" value="{proof_id}">
<button type="submit">签出校样单</button>
</form>
</div>
''')


def view_unfolded(connection: sqlite3.Connection, proof_id: int) -> PageResponse:
    proof = get_proof(connection, proof_id)
    if proof is None:
        return problem(404, '校样不存在')
    return render_unfolded(build_unfolded_review(proof, list_annotations(connection, proof_id)))
