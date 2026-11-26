from dataclasses import dataclass
from typing import Iterable

from fold.creases import Crease, validate_crease
from fold.projection import make_frame, project_footprint
from sheet.stock import Stock


@dataclass(frozen=True, slots=True)
class FoldSequence:
    creases: tuple[Crease, ...]

    def prefix(self, step: int) -> tuple[Crease, ...]:
        if type(step) is not int or not 0 <= step <= len(self.creases):
            raise ValueError('折步不存在')
        return self.creases[:step]


def validate_sequence(stock: Stock, creases: Iterable[Crease]) -> FoldSequence:
    ordered = tuple(creases)
    if len(ordered) > 2:
        raise ValueError('校样最多可保存两道折线')
    if not ordered:
        return FoldSequence(ordered)
    footprint = frozenset(stock.cells())
    for step, crease in enumerate(ordered, 1):
        frame = make_frame(footprint)
        try:
            validate_crease(crease, frame.minimum, frame.maximum)
        except ValueError as error:
            raise ValueError(f'第 {step} 道折线：{error}') from error
        footprint = project_footprint(footprint, crease)
    return FoldSequence(ordered)
