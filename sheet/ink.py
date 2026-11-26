from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from sheet.stock import Cell, Face, Stock


@dataclass(frozen=True, slots=True)
class Ink:
    front: Mapping[Cell, str]
    back: Mapping[Cell, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'front', MappingProxyType(dict(self.front)))
        object.__setattr__(self, 'back', MappingProxyType(dict(self.back)))

    def mark_at(self, cell: Cell, face: Face) -> str | None:
        marks = self.front if face is Face.FRONT else self.back
        return marks.get(cell)


def _validate_face(
    stock: Stock, face: Face, rows: Iterable[tuple[Cell, str]],
) -> dict[Cell, str]:
    marks: dict[Cell, str] = {}
    for cell, mark in rows:
        if not stock.contains(cell):
            raise ValueError(f'{face.label}图记引用无效原格 ({cell.x}, {cell.y})')
        if cell in marks:
            raise ValueError(f'{face.label}图记重复引用 ({cell.x}, {cell.y})')
        if not isinstance(mark, str):
            raise ValueError(f'{face.label}图记须为文字')
        marks[cell] = mark
    return marks


def validate_ink(
    stock: Stock, front: Iterable[tuple[Cell, str]], back: Iterable[tuple[Cell, str]],
) -> Ink:
    return Ink(_validate_face(stock, Face.FRONT, front), _validate_face(stock, Face.BACK, back))
