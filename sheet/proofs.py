import sqlite3
from dataclasses import dataclass
from typing import Mapping

from fold.creases import Crease, FoldAxis, MovingSide
from fold.sequence import FoldSequence, validate_sequence
from sheet.cutouts import Cutouts, validate_cutouts
from sheet.ink import Ink, validate_ink
from sheet.proof_store import insert_proof, load_proof
from sheet.stock import Cell, Stock


@dataclass(frozen=True, slots=True)
class ProofDraft:
    stock: Stock
    front: tuple[tuple[Cell, str], ...]
    back: tuple[tuple[Cell, str], ...]
    holes: tuple[Cell, ...]
    creases: tuple[Crease, ...]


@dataclass(frozen=True, slots=True)
class FrozenProof:
    proof_id: int
    stock: Stock
    ink: Ink
    cutouts: Cutouts
    folds: FoldSequence


def _pack_marks(marks: Mapping[Cell, str]) -> list[list]:
    ordered = sorted(marks.items(), key=lambda item: (item[0].y, item[0].x))
    return [[cell.x, cell.y, mark] for cell, mark in ordered]


def freeze_proof(connection: sqlite3.Connection, draft: ProofDraft) -> int:
    ink = validate_ink(draft.stock, draft.front, draft.back)
    cutouts = validate_cutouts(draft.stock, draft.holes)
    folds = validate_sequence(draft.stock, draft.creases)
    payload = {
        'width': draft.stock.width,
        'height': draft.stock.height,
        'front': _pack_marks(ink.front),
        'back': _pack_marks(ink.back),
        'holes': [[cell.x, cell.y] for cell in sorted(cutouts.holes, key=lambda cell: (cell.y, cell.x))],
        'folds': [[crease.axis.value, crease.line, crease.moving.value] for crease in folds.creases],
    }
    with connection:
        proof_id = insert_proof(connection, payload)
    return proof_id


def get_proof(connection: sqlite3.Connection, proof_id: int) -> FrozenProof | None:
    payload = load_proof(connection, proof_id)
    if payload is None:
        return None
    return FrozenProof(
        proof_id=proof_id,
        stock=Stock(payload['width'], payload['height']),
        ink=Ink(
            {Cell(x, y): mark for x, y, mark in payload['front']},
            {Cell(x, y): mark for x, y, mark in payload['back']},
        ),
        cutouts=Cutouts(frozenset(Cell(x, y) for x, y in payload['holes'])),
        folds=FoldSequence(tuple(
            Crease(FoldAxis(axis), line, MovingSide(moving))
            for axis, line, moving in payload['folds']
        )),
    )
