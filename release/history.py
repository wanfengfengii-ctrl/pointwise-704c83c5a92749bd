from dataclasses import asdict
import json
import sqlite3

from fold.creases import Crease, FoldAxis, MovingSide
from release.report import ReportLine, ReportSnapshot
from sheet.proof_store import MAX_ROW_ID
from sheet.stock import Cell, Face, Stock


def initialize_reports(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY,
            proof_id INTEGER NOT NULL REFERENCES proofs(id),
            payload TEXT NOT NULL
        )
    ''')


def insert_report(connection: sqlite3.Connection, snapshot: ReportSnapshot) -> int:
    payload = {
        'stock': asdict(snapshot.stock),
        'creases': [asdict(crease) for crease in snapshot.creases],
        'lines': [asdict(line) for line in snapshot.lines],
    }
    cursor = connection.execute(
        'INSERT INTO reports (proof_id, payload) VALUES (?, ?)',
        (snapshot.proof_id, json.dumps(payload, ensure_ascii=False, separators=(',', ':'))),
    )
    return cursor.lastrowid


def get_report(connection: sqlite3.Connection, report_id: int) -> ReportSnapshot | None:
    if not 0 < report_id <= MAX_ROW_ID:
        return None
    row = connection.execute(
        'SELECT proof_id, payload FROM reports WHERE id = ?', (report_id,),
    ).fetchone()
    if row is None:
        return None
    proof_id, serialized = row
    payload = json.loads(serialized)
    creases = tuple(
        Crease(FoldAxis(item['axis']), item['line'], MovingSide(item['moving']))
        for item in payload['creases']
    )
    lines = tuple(
        ReportLine(item['annotation_id'], Cell(**item['origin']), Face(item['face']), item['text'])
        for item in payload['lines']
    )
    return ReportSnapshot(proof_id, Stock(**payload['stock']), creases, lines, report_id)
