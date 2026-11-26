from dataclasses import dataclass
from html import escape
from typing import Mapping
from urllib.parse import urlencode

from fold.visibility import Observation


@dataclass(frozen=True, slots=True)
class ViewSpec:
    proof_id: int
    step: int
    observation: Observation


def parse_view(proof_id: int, parameters: Mapping[str, str]) -> ViewSpec:
    try:
        step = int(parameters.get('step', '0'))
    except ValueError as error:
        raise ValueError('折步须为整数') from error
    try:
        observation = Observation(parameters.get('side', 'front'))
    except ValueError as error:
        raise ValueError('观察面须为正看或反看') from error
    return ViewSpec(proof_id, step, observation)


def validate_view_step(view: ViewSpec, final_step: int) -> None:
    if type(view.step) is not int or not 0 <= view.step <= final_step:
        raise ValueError('折步不存在')


def view_url(view: ViewSpec) -> str:
    query = urlencode({'step': view.step, 'side': view.observation.value})
    return f'/proofs/{view.proof_id}?{query}'


def _view_link(label: str, target: ViewSpec, current: ViewSpec) -> str:
    selected = ' aria-current="page"' if target == current else ''
    return f'<a href="{escape(view_url(target), quote=True)}"{selected}>{escape(label)}</a>'


def render_fold_controls(view: ViewSpec, final_step: int) -> str:
    steps = ''.join(
        _view_link('原纸' if step == 0 else f'第 {step} 折',
                   ViewSpec(view.proof_id, step, view.observation), view)
        for step in range(final_step + 1)
    )
    sides = ''.join(
        _view_link(side.label, ViewSpec(view.proof_id, view.step, side), view)
        for side in Observation
    )
    return (
        f'<nav class="controls" aria-label="折步">{steps}</nav>'
        f'<nav class="controls" aria-label="观察面">{sides}</nav>'
    )
