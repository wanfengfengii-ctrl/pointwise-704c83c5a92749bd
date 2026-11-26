from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from fold.layers import FoldedLayers, Layer
from fold.projection import ProjectedFrame
from sheet.stock import Cell, Face


class Observation(StrEnum):
    FRONT = 'front'
    BACK = 'back'

    @property
    def mirrored(self) -> bool:
        return self is Observation.BACK

    @property
    def label(self) -> str:
        return '反看' if self.mirrored else '正看'


@dataclass(frozen=True, slots=True)
class VisibleCell:
    display: Cell
    origin: Cell
    face: Face


@dataclass(frozen=True, slots=True)
class VisibleSurface:
    observation: Observation
    frame: ProjectedFrame
    cells: Mapping[Cell, VisibleCell]


def _exposed_cell(
    stack: tuple[Layer, ...], observation: Observation, display: Cell,
) -> VisibleCell | None:
    layers = reversed(stack) if observation.mirrored else iter(stack)
    for layer in layers:
        if not layer.is_hole:
            face = layer.top_face.opposite() if observation.mirrored else layer.top_face
            return VisibleCell(display, layer.origin, face)
    return None


def visible_surface(layers: FoldedLayers, observation: Observation) -> VisibleSurface:
    exposed = {}
    for position, stack in layers.stacks.items():
        display = layers.frame.to_display_cell(position, observation.mirrored)
        cell = _exposed_cell(stack, observation, display)
        if cell is not None:
            exposed[display] = cell
    return VisibleSurface(observation, layers.frame, MappingProxyType(exposed))


def visible_at(layers: FoldedLayers, observation: Observation, display: Cell) -> VisibleCell | None:
    position = layers.frame.to_folded_cell(display, observation.mirrored)
    if position is None:
        return None
    return _exposed_cell(layers.stacks.get(position, ()), observation, display)
