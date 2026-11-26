from dataclasses import dataclass
from typing import Iterable

from fold.creases import Crease
from sheet.stock import Cell


@dataclass(frozen=True, slots=True)
class ProjectedFrame:
    minimum: Cell
    maximum: Cell

    @property
    def width(self) -> int:
        return self.maximum.x - self.minimum.x + 1

    @property
    def height(self) -> int:
        return self.maximum.y - self.minimum.y + 1

    def to_display_cell(self, folded: Cell, mirrored: bool = False) -> Cell:
        if not (
            self.minimum.x <= folded.x <= self.maximum.x
            and self.minimum.y <= folded.y <= self.maximum.y
        ):
            raise ValueError('折后格不在投影范围内')
        column = self.maximum.x - folded.x if mirrored else folded.x - self.minimum.x
        return Cell(column, folded.y - self.minimum.y)

    def to_folded_cell(self, display: Cell, mirrored: bool = False) -> Cell | None:
        if not 0 <= display.x < self.width or not 0 <= display.y < self.height:
            return None
        column = self.maximum.x - display.x if mirrored else self.minimum.x + display.x
        return Cell(column, self.minimum.y + display.y)


def make_frame(cells: Iterable[Cell]) -> ProjectedFrame:
    positions = iter(cells)
    try:
        first = next(positions)
    except StopIteration as error:
        raise ValueError('投影范围至少含一个纸格') from error
    min_x = max_x = first.x
    min_y = max_y = first.y
    for cell in positions:
        min_x = min(min_x, cell.x)
        max_x = max(max_x, cell.x)
        min_y = min(min_y, cell.y)
        max_y = max(max_y, cell.y)
    return ProjectedFrame(Cell(min_x, min_y), Cell(max_x, max_y))


def project_footprint(cells: Iterable[Cell], crease: Crease) -> frozenset[Cell]:
    return frozenset(crease.reflect(cell) if crease.moves(cell) else cell for cell in cells)
