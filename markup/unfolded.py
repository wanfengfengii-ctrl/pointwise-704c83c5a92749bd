from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from markup.annotations import Annotation
from sheet.proofs import FrozenProof
from sheet.stock import Cell, Face


@dataclass(frozen=True, slots=True)
class UnfoldedReview:
    proof: FrozenProof
    groups: Mapping[tuple[Face, Cell], tuple[Annotation, ...]]


def build_unfolded_review(proof: FrozenProof, annotations: Iterable[Annotation]) -> UnfoldedReview:
    groups: dict[tuple[Face, Cell], list[Annotation]] = defaultdict(list)
    for annotation in sorted(annotations, key=lambda note: note.annotation_id):
        groups[annotation.face, annotation.origin].append(annotation)
    return UnfoldedReview(proof, MappingProxyType({key: tuple(notes) for key, notes in groups.items()}))
