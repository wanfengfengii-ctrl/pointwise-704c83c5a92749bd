import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

from fold.creases import Crease, FoldAxis, MovingSide
from sheet.proofs import ProofDraft, freeze_proof
from sheet.proof_store import initialize_proofs
from sheet.stock import Cell, Stock


def _fields(data: object, fields: set[str], label: str) -> dict:
    if not isinstance(data, dict) or data.keys() != fields:
        raise ValueError(f'{label}字段应为 {", ".join(sorted(fields))}')
    return data


def _array(data: object, label: str) -> list:
    if not isinstance(data, list):
        raise ValueError(f'{label}须为数组')
    return data


def _marks(data: object, label: str) -> tuple[tuple[Cell, str], ...]:
    marks = []
    for item in _array(data, label):
        row = _fields(item, {'x', 'y', 'mark'}, label)
        marks.append((Cell(row['x'], row['y']), row['mark']))
    return tuple(marks)


def _holes(data: object) -> tuple[Cell, ...]:
    holes = []
    for pair in _array(data, '通孔'):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError('每个通孔须给出 [x, y]')
        holes.append(Cell(pair[0], pair[1]))
    return tuple(holes)


def _creases(data: object) -> tuple[Crease, ...]:
    creases = []
    for item in _array(data, '折序'):
        row = _fields(item, {'axis', 'line', 'moving'}, '折线')
        try:
            axis = FoldAxis(row['axis'])
            moving = MovingSide(row['moving'])
        except ValueError as error:
            raise ValueError('折轴须为 x 或 y，移动侧须为 low 或 high') from error
        creases.append(Crease(axis, row['line'], moving))
    return tuple(creases)


def parse_proof_input(data: object) -> ProofDraft:
    rows = _fields(data, {'width', 'height', 'front', 'back', 'holes', 'folds'}, '格稿')
    return ProofDraft(
        Stock(rows['width'], rows['height']),
        _marks(rows['front'], '正面图记'),
        _marks(rows['back'], '背面图记'),
        _holes(rows['holes']),
        _creases(rows['folds']),
    )


def import_proof_file(connection: sqlite3.Connection, path: str | Path) -> int:
    with Path(path).open(encoding='utf-8') as source:
        draft = parse_proof_input(json.load(source))
    return freeze_proof(connection, draft)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='导入并冻结双面纸样格稿')
    parser.add_argument('--db', required=True, type=Path, help='工坊 SQLite 文件')
    parser.add_argument('source', type=Path, help='JSON 格稿')
    arguments = parser.parse_args(argv)
    try:
        with closing(sqlite3.connect(arguments.db)) as connection:
            initialize_proofs(connection)
            proof_id = import_proof_file(connection, arguments.source)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f'导入失败：{error}', file=sys.stderr)
        return 1
    print(proof_id)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
