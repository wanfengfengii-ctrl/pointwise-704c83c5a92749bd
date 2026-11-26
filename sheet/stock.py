from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator


@dataclass(frozen=True, slots=True)
class Cell:
    x: int
    y: int


class Face(StrEnum):
    FRONT = 'front'
    BACK = 'back'

    def opposite(self) -> 'Face':
        return Face.BACK if self is Face.FRONT else Face.FRONT

    @property
    def label(self) -> str:
        return '正面' if self is Face.FRONT else '背面'


@dataclass(frozen=True, slots=True)
class Stock:
    width: int
    height: int

    def __post_init__(self) -> None:
        if type(self.width) is not int or type(self.height) is not int:
            raise ValueError('纸样行列尺寸须为整数')
        if self.width <= 0 or self.height <= 0:
            raise ValueError('纸样行列尺寸须为正数')

    def contains(self, cell: Cell) -> bool:
        return (
            type(cell.x) is int and type(cell.y) is int
            and 0 <= cell.x < self.width and 0 <= cell.y < self.height
        )

    def cells(self) -> Iterator[Cell]:
        for y in range(self.height):
            for x in range(self.width):
                yield Cell(x, y)
