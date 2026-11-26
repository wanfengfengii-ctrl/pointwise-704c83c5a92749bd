import json
import sqlite3


MAX_ROW_ID = (1 << 63) - 1


def initialize_proofs(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS proofs (
            id INTEGER PRIMARY KEY,
            payload TEXT NOT NULL
        )
    ''')


def insert_proof(connection: sqlite3.Connection, payload: dict) -> int:
    cursor = connection.execute(
        'INSERT INTO proofs (payload) VALUES (?)',
        (json.dumps(payload, ensure_ascii=False, separators=(',', ':')),),
    )
    return cursor.lastrowid


def load_proof(connection: sqlite3.Connection, proof_id: int) -> dict | None:
    if not 0 < proof_id <= MAX_ROW_ID:
        return None
    row = connection.execute('SELECT payload FROM proofs WHERE id = ?', (proof_id,)).fetchone()
    return None if row is None else json.loads(row[0])
