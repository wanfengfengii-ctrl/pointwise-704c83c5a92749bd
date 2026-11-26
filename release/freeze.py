from dataclasses import replace
import sqlite3

from markup.annotations import list_annotations
from release.history import insert_report
from release.report import ReportSnapshot, build_report_snapshot
from sheet.proofs import get_proof


def issue_report(connection: sqlite3.Connection, proof_id: int) -> ReportSnapshot | None:
    with connection:
        # Acquire the write transaction before reading any inputs to the snapshot.
        connection.execute('BEGIN IMMEDIATE')
        proof = get_proof(connection, proof_id)
        if proof is None:
            return None
        snapshot = build_report_snapshot(proof, list_annotations(connection, proof_id))
        report_id = insert_report(connection, snapshot)
    return replace(snapshot, report_id=report_id)
