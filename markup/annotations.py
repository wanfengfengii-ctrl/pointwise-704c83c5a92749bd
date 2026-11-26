from dataclasses import dataclass
import sqlite3

from markup.target import PaperTarget
from sheet.stock import Cell, Face


@dataclass(frozen=True, slots=True)
class Annotation:
    annotation_id: int
    proof_id: int
    origin: Cell
    face: Face
    text: str


def initialize_annotations(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY,
            proof_id INTEGER NOT NULL REFERENCES proofs(id),
            x INTEGER NOT NULL CHECK (x >= 0),
            y INTEGER NOT NULL CHECK (y >= 0),
            face TEXT NOT NULL CHECK (face IN ('front', 'back')),
            text TEXT NOT NULL
        )
    ''')
    connection.execute('CREATE INDEX IF NOT EXISTS annotations_by_proof ON annotations (proof_id, id)')


def append_annotation(connection: sqlite3.Connection, target: PaperTarget, text: str) -> Annotation:
    if not isinstance(text, str) or not text.strip():
        raise ValueError('请输入批注文字')
    with connection:
        cursor = connection.execute(
            'INSERT INTO annotations (proof_id, x, y, face, text) VALUES (?, ?, ?, ?, ?)',
            (target.proof_id, target.origin.x, target.origin.y, target.face.value, text),
        )
        annotation_id = cursor.lastrowid
    return Annotation(annotation_id, target.proof_id, target.origin, target.face, text)


def list_annotations(connection: sqlite3.Connection, proof_id: int) -> tuple[Annotation, ...]:
    rows = connection.execute(
        'SELECT id, x, y, face, text FROM annotations WHERE proof_id = ? ORDER BY id',
        (proof_id,),
    )
    return tuple(
        Annotation(annotation_id, proof_id, Cell(x, y), Face(face), text)
        for annotation_id, x, y, face, text in rows
    )
