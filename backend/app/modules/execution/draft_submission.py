"""Draft confirmation composes the durable Run submission and draft transaction."""
import json
from ...authorization import refresh_active_user
from ...draft_service import prepare_draft_run_request, consume_prepared_draft, _get_owned_draft
from ...models import RunRecord
from ...registry import RegisteredSkill
from .idempotency import Operation, Scope, read
from .run_submission import submit_run


def submit_draft(db, draft_id, user):
    user = refresh_active_user(db, user)
    draft = _get_owned_draft(db, draft_id, user)
    key = f"draft:{draft.id}:{draft.content_revision}"
    receipt = read(db, Scope(user.user_id, user.department_id, Operation.DRAFT_CONFIRM), key)
    pinned = None if receipt is None else RegisteredSkill.model_validate(json.loads(receipt.pinned_revision_json)["skill"])
    request = prepare_draft_run_request(db, draft_id, user, pinned_skill=pinned)
    if isinstance(request, RunRecord):
        return request
    # This entrypoint owns the read phase; final locked consumption compares the
    # current revision and full request against this original confirmation.
    db.rollback()
    def consume(session, run):
        consume_prepared_draft(session, draft_id, user, run, request)
    return submit_run(db, request, user, operation=Operation.DRAFT_CONFIRM,
                      on_persist=consume)
