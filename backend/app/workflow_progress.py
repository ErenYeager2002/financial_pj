"""Shared batch progress for detail pages and task summaries."""
from __future__ import annotations

from .models import WorkflowBatch


def batch_progress(batch: WorkflowBatch) -> int:
    workflows = batch.workflows
    progress = (
        int(sum(item.progress for item in workflows) / len(workflows))
        if workflows and batch.state != "finalizing"
        else batch.progress
    )
    return min(max(progress, 0), 100)
