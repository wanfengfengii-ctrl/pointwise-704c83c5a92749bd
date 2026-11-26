from dataclasses import dataclass
from typing import Iterable

from fold.creases import Crease
from markup.annotations import Annotation
from sheet.proofs import FrozenProof
from sheet.stock import Cell, Face, Stock


@dataclass(frozen=True, slots=True)
class ReportLine:
    annotation_id: int
    origin: Cell
    face: Face
    text: str


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    proof_id: int
    stock: Stock
    creases: tuple[Crease, ...]
    lines: tuple[ReportLine, ...]
    report_id: int | None = None


def build_report_snapshot(proof: FrozenProof, annotations: Iterable[Annotation]) -> ReportSnapshot:
    lines = tuple(
        ReportLine(note.annotation_id, note.origin, note.face, note.text)
        for note in sorted(annotations, key=lambda note: note.annotation_id)
    )
    return ReportSnapshot(proof.proof_id, proof.stock, proof.folds.creases, lines)
