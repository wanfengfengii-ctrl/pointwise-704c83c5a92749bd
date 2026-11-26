from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from fold.creases import Crease
from fold.projection import ProjectedFrame, make_frame
from fold.sequence import FoldSequence
from sheet.cutouts import Cutouts
from sheet.stock import Cell, Face, Stock


@dataclass(frozen=True, slots=True)
class Layer:
    origin: Cell
    top_face: Face
    is_hole: bool

    def flipped(self) -> 'Layer':
        return Layer(self.origin, self.top_face.opposite(), self.is_hole)


@dataclass(frozen=True, slots=True)
class FoldedLayers:
    frame: ProjectedFrame
    stacks: Mapping[Cell, tuple[Layer, ...]]


def _apply_crease(
    stacks: Mapping[Cell, tuple[Layer, ...]], crease: Crease,
) -> dict[Cell, tuple[Layer, ...]]:
    stationary = {}
    moving = {}
    for position, stack in stacks.items():
        if crease.moves(position):
            landing = crease.reflect(position)
            moving[landing] = tuple(layer.flipped() for layer in reversed(stack))
        else:
            stationary[position] = stack
    for landing, stack in moving.items():
        stationary[landing] = stack + stationary.get(landing, ())
    return stationary


def build_layers(stock: Stock, cutouts: Cutouts, folds: FoldSequence, step: int) -> FoldedLayers:
    creases = folds.prefix(step)
    stacks = {
        cell: (Layer(cell, Face.FRONT, cutouts.is_hole(cell)),)
        for cell in stock.cells()
    }
    for crease in creases:
        stacks = _apply_crease(stacks, crease)
    return FoldedLayers(make_frame(stacks), MappingProxyType(stacks))
