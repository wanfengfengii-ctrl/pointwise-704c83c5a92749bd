import sqlite3
from dataclasses import dataclass

from browser.fold_controls import validate_view_step
from browser.selection import Selection
from fold.layers import build_layers
from fold.visibility import visible_at
from sheet.proofs import get_proof
from sheet.stock import Cell, Face


class UnknownProof(LookupError):
    pass


class EmptySelection(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PaperTarget:
    proof_id: int
    origin: Cell
    face: Face


def resolve_target(connection: sqlite3.Connection, selection: Selection) -> PaperTarget:
    view = selection.view
    proof = get_proof(connection, view.proof_id)
    if proof is None:
        raise UnknownProof('校样不存在')
    validate_view_step(view, len(proof.folds.creases))
    layers = build_layers(proof.stock, proof.cutouts, proof.folds, view.step)
    visible = visible_at(layers, view.observation, selection.display)
    if visible is None:
        raise EmptySelection('所选位置没有可批注的纸面')
    return PaperTarget(proof.proof_id, visible.origin, visible.face)
