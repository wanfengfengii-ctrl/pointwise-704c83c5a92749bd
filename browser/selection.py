from dataclasses import dataclass
from typing import Mapping

from browser.fold_controls import ViewSpec, parse_view
from sheet.stock import Cell


@dataclass(frozen=True, slots=True)
class Selection:
    view: ViewSpec
    display: Cell


def encode_selection(selection: Selection) -> dict[str, str]:
    return {
        'proof_id': str(selection.view.proof_id),
        'step': str(selection.view.step),
        'side': selection.view.observation.value,
        'x': str(selection.display.x),
        'y': str(selection.display.y),
    }


def parse_selection(fields: Mapping[str, str]) -> Selection:
    try:
        proof_id = int(fields['proof_id'])
        view_fields = {'step': fields['step'], 'side': fields['side']}
        display = Cell(int(fields['x']), int(fields['y']))
    except KeyError as error:
        raise ValueError(f'选格缺少字段 {error.args[0]}') from error
    except ValueError as error:
        raise ValueError('校样号与选格坐标须为整数') from error
    if proof_id <= 0:
        raise ValueError('校样号须为正整数')
    return Selection(parse_view(proof_id, view_fields), display)
