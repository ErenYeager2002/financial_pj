from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ExecutionMode = Literal["workflow", "pi_harness"]
PI_HARNESS_ACTION = "pi_harness_execute"


class ReconciliationRunner(Protocol):
    mode: ExecutionMode

    def initial_action(self) -> str: ...

    def worker_chains_next_action(self) -> bool: ...

    def worker_finalizes_batch(self) -> bool: ...


@dataclass(frozen=True)
class WorkflowRunnerAdapter:
    mode: ExecutionMode = "workflow"

    def initial_action(self) -> str:
        return "prepare_workspace"

    def worker_chains_next_action(self) -> bool:
        return True

    def worker_finalizes_batch(self) -> bool:
        return True


@dataclass(frozen=True)
class PiHarnessRunnerAdapter:
    mode: ExecutionMode = "pi_harness"

    def initial_action(self) -> str:
        return PI_HARNESS_ACTION

    def worker_chains_next_action(self) -> bool:
        return False

    def worker_finalizes_batch(self) -> bool:
        return False


_RUNNERS: dict[str, ReconciliationRunner] = {
    "workflow": WorkflowRunnerAdapter(),
    "pi_harness": PiHarnessRunnerAdapter(),
}


def reconciliation_runner(mode: str) -> ReconciliationRunner:
    try:
        return _RUNNERS[mode]
    except KeyError as exc:
        raise ValueError("不支持的应收核销执行方式。") from exc
