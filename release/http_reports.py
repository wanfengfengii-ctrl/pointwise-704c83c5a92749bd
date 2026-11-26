from html import escape
import sqlite3

from browser.html_pages import PageResponse, page, problem
from fold.creases import MovingSide
from release.freeze import issue_report
from release.history import get_report
from release.report import ReportLine, ReportSnapshot


def _render_line(line: ReportLine) -> str:
    x, y = line.origin.x, line.origin.y
    return f'''
<tr data-x="{x}" data-y="{y}" data-face="{line.face.value}">
<th scope="row">#{line.annotation_id}</th><td>({x}, {y})</td><td>{line.face.label}</td>
<td><p class="annotation-text" data-annotation-id="{line.annotation_id}">{escape(line.text)}</p></td>
</tr>'''


def render_report(snapshot: ReportSnapshot, status: int = 200) -> PageResponse:
    folds = ''.join(
        f'<li>{crease.axis.value}={crease.line} · {"高侧" if crease.moving is MovingSide.HIGH else "低侧"}移动</li>'
        for crease in snapshot.creases
    )
    sequence = f'<ol>{folds}</ol>' if folds else '<p>原件无折线。</p>'
    lines = ''.join(_render_line(line) for line in snapshot.lines)
    if not lines:
        lines = '<tr><td colspan="4">签出时没有正式批注。</td></tr>'
    return page(f'校样单 #{snapshot.report_id}', f'''
<article data-report-id="{snapshot.report_id}" data-proof-id="{snapshot.proof_id}">
<h2>冻结来源</h2>
<p><a href="/proofs/{snapshot.proof_id}">校样 {snapshot.proof_id}</a> · 原纸 {snapshot.stock.width} × {snapshot.stock.height} 格</p>
{sequence}
<h2>原纸面批注</h2>
<div class="table-scroll"><table>
<thead><tr><th scope="col">批注</th><th scope="col">原格 (x, y)</th><th scope="col">纸面</th><th scope="col">文字</th></tr></thead>
<tbody>{lines}</tbody>
</table></div>
</article>
<p><a href="/reports/{snapshot.report_id}">领取此签出单</a></p>
''', status)


def issue_report_response(connection: sqlite3.Connection, proof_id: int) -> PageResponse:
    try:
        snapshot = issue_report(connection, proof_id)
    except sqlite3.Error:
        return problem(500, '校样单签存失败')
    if snapshot is None:
        return problem(404, '校样不存在')
    return render_report(snapshot, 201)


def read_report_response(connection: sqlite3.Connection, report_id: int) -> PageResponse:
    snapshot = get_report(connection, report_id)
    if snapshot is None:
        return problem(404, '签出单不存在')
    return render_report(snapshot)
