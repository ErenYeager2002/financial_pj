"""Keep AR v2 actions outside legacy Workers' queued/running SQL predicates.

The existing database column is retained. Public lifecycle states stay unchanged;
only newly created v2 actions receive the isolated storage values.
"""
from __future__ import annotations

from sqlalchemy import case

AR_ACTION_PREFIX = "ar_v2:"
ACTION_STATES = ("queued", "running", "succeeded", "failed", "cancelled")


def isolated_action_state(value: str) -> str:
    if value not in ACTION_STATES:
        raise ValueError("新版核销动作状态无效，不能写入旧队列。")
    return AR_ACTION_PREFIX + value


def logical_action_state(value: str | None) -> str | None:
    if value in {isolated_action_state(state) for state in ACTION_STATES}:
        return value.removeprefix(AR_ACTION_PREFIX)
    return value


def action_storage_states(*states: str) -> tuple[str, ...]:
    """Use the existing state index at Worker claim boundaries."""
    return tuple(value for state in states for value in (state, isolated_action_state(state)))


def logical_state_expression(column):
    return case({isolated_action_state(state): state for state in ACTION_STATES},
                value=column, else_=column)


def state_update_expression(column, value: str):
    return case((column.in_([isolated_action_state(state) for state in ACTION_STATES]),
                 isolated_action_state(value)), else_=value)
