from html import escape

from browser.fold_controls import ViewSpec
from browser.selection import Selection, encode_selection
from fold.visibility import VisibleCell, VisibleSurface
from sheet.ink import Ink
from sheet.stock import Cell


def render_visible_cell(cell: VisibleCell, view: ViewSpec, ink: Ink) -> str:
    mark = ink.mark_at(cell.origin, cell.face)
    label = escape(mark) if mark else '<span class="muted">未印图记</span>'
    x, y = cell.display.x, cell.display.y
    fields = ''.join(
        f'<input type="hidden" name="{name}" value="{escape(value, quote=True)}">'
        for name, value in encode_selection(Selection(view, cell.display)).items()
    )
    return f'''<td data-display-x="{x}" data-display-y="{y}">
<p class="cell-mark">{label}</p>
<form method="post" action="/annotations">
{fields}
<label>批注<textarea name="text" rows="2" required></textarea></label>
<button type="submit">保存批注</button>
</form>
</td>'''


def render_empty_cell(display: Cell) -> str:
    return (
        f'<td class="empty" data-display-x="{display.x}" data-display-y="{display.y}">'
        '<p class="cell-mark">空处</p></td>'
    )


def render_grid(surface: VisibleSurface, view: ViewSpec, ink: Ink) -> str:
    columns = ''.join(f'<th scope="col">{x}</th>' for x in range(surface.frame.width))
    rows = []
    for y in range(surface.frame.height):
        cells = []
        for x in range(surface.frame.width):
            display = Cell(x, y)
            visible = surface.cells.get(display)
            if visible is None:
                cells.append(render_empty_cell(display))
            else:
                cells.append(render_visible_cell(visible, view, ink))
        rows.append(f'<tr><th scope="row">{y}</th>{"".join(cells)}</tr>')
    return (
        '<div class="table-scroll"><table class="paper-grid">'
        '<caption>折后显示格 · 列 x / 行 y</caption>'
        f'<thead><tr><th scope="col">y / x</th>{columns}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )
