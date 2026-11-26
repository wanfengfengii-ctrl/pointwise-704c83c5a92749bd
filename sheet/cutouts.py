from dataclasses import dataclass
from typing import Iterable

from sheet.stock import Cell, Stock


@dataclass(frozen=True, slots=True)
class Cutouts:
    holes: frozenset[Cell]

    def is_hole(self, cell: Cell) -> bool:
        return cell in self.holes


def validate_cutouts(stock: Stock, cells: Iterable[Cell]) -> Cutouts:
    holes: set[Cell] = set()
    for cell in cells:
        if not stock.contains(cell):
            raise ValueError(f'通孔引用无效原格 ({cell.x}, {cell.y})')
        if cell in holes:
            raise ValueError(f'重复通孔 ({cell.x}, {cell.y})')
        holes.add(cell)
    return Cutouts(frozenset(holes))
