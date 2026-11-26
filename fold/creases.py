from dataclasses import dataclass
from enum import StrEnum

from sheet.stock import Cell


class FoldAxis(StrEnum):
    X = 'x'
    Y = 'y'

    def index(self, cell: Cell) -> int:
        return cell.x if self is FoldAxis.X else cell.y


class MovingSide(StrEnum):
    LOW = 'low'
    HIGH = 'high'


@dataclass(frozen=True, slots=True)
class Crease:
    axis: FoldAxis
    line: int
    moving: MovingSide

    def moves(self, cell: Cell) -> bool:
        low = self.axis.index(cell) < self.line
        return low if self.moving is MovingSide.LOW else not low

    def reflect(self, cell: Cell) -> Cell:
        reflected = 2 * self.line - 1 - self.axis.index(cell)
        if self.axis is FoldAxis.X:
            return Cell(reflected, cell.y)
        return Cell(cell.x, reflected)


def validate_crease(crease: Crease, minimum: Cell, maximum: Cell) -> None:
    if not isinstance(crease.axis, FoldAxis) or not isinstance(crease.moving, MovingSide):
        raise ValueError('折线须明确指定折轴和移动侧')
    if type(crease.line) is not int:
        raise ValueError('折线须沿整数格边')
    if not crease.axis.index(minimum) < crease.line <= crease.axis.index(maximum):
        raise ValueError('折线须在当前投影范围内部')
