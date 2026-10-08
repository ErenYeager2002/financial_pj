"""Maintenance state machine. No shell commands, financial writes or force option."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Plan:
    services: tuple[str, ...]
    mode: str
    requires_idle: bool
    image_key: str | None = None

PLANS = {
    'frontend': Plan(('next',), 'full', False, 'NEXT_IMAGE'),
    'backend-schema': Plan(('api', 'worker-standard', 'worker-task-discovery'), 'full', True, 'BACKEND_IMAGE'),
    'backend': Plan(('api', 'egress-proxy', 'worker-standard', 'worker-task-discovery'), 'full', True, 'BACKEND_IMAGE'),
    'workers': Plan(('worker-standard', 'worker-task-discovery', 'worker-agent'), 'worker', True),
    'agent': Plan(('worker-agent',), 'worker', True, 'AGENT_IMAGE'),
}

class DeploymentFailure(RuntimeError):
    pass

def deploy(adapter, name, image=None):
    if name not in PLANS:
        raise DeploymentFailure('Unknown deployment plan')
    plan = PLANS[name]
    if image and not plan.image_key:
        raise DeploymentFailure('This plan does not accept an image')
    if adapter.mode() != 'normal':
        raise DeploymentFailure('Maintenance already active; inspect/recover it first')
    # Everything that can fail without disrupting access happens before preparation.
    adapter.preflight(plan, image)
    adapter.backup()
    adapter.set_mode('notice')
    committed = False
    try:
        adapter.grace()
        if plan.requires_idle:
            adapter.wait_idle()
        adapter.set_mode(plan.mode)
        adapter.verify_mode(plan.mode)
        # From this point a partial cutover must never restore access automatically.
        committed = True
        adapter.cutover(plan, image)
        adapter.wait_healthy(plan)
        adapter.set_mode('normal')
        adapter.verify_mode('normal')
        adapter.record('succeeded', name)
    except BaseException:
        if not committed:
            # A failed drain made no service changes: restore normal access.
            adapter.set_mode('normal')
        else:
            adapter.set_mode(plan.mode)
            if name in ('backend-schema', 'frontend'):
                try:
                    if name == 'frontend':
                        restored = adapter.rollback_frontend()
                    elif name == 'backend-schema':
                        restored = adapter.restore_before_schema_migration()
                        if not restored:
                            restored = adapter.rollback_after_schema_migration()
                    else:
                        restored = adapter.rollback_runtime(plan)
                    if restored:
                        adapter.wait_healthy(plan)
                        adapter.set_mode('normal')
                        adapter.verify_mode('normal')
                        adapter.record('restored-service', name)
                except BaseException:
                    adapter.set_mode(plan.mode)
                    adapter.record('recovery-required', name)
                    raise
        adapter.record('failed', name)
        raise

def recover(adapter):
    if adapter.mode() == 'normal':
        return
    adapter.wait_healthy(None)
    adapter.set_mode('normal')
    try:
        adapter.verify_mode('normal')
    except BaseException:
        adapter.set_mode('full')
        raise
    adapter.record('recovered', 'recovery')

def recover_frontend(adapter, image):
    """Repair only Next under retained full maintenance, then use normal readiness gates."""
    if adapter.mode() != 'full':
        raise DeploymentFailure('Frontend recovery requires existing full maintenance')
    plan = PLANS['frontend']
    adapter.preflight_frontend_recovery(image)
    adapter.backup()
    try:
        adapter.cutover(plan, image)
        adapter.wait_healthy(plan)
        adapter.set_mode('normal')
        adapter.verify_mode('normal')
        adapter.record('recovered', 'frontend')
    except BaseException:
        adapter.set_mode('full')
        adapter.record('failed', 'frontend-recovery')
        raise


def recover_schema(adapter, image):
    """Continue a confirmed original migration under retained full maintenance."""
    plan = PLANS['backend-schema']
    adapter.preflight_schema_recovery(image)
    adapter.backup()
    try:
        adapter.wait_idle()
        adapter.cutover(plan, image)
        adapter.wait_healthy(plan)
        adapter.set_mode('normal')
        adapter.verify_mode('normal')
        adapter.record('recovered', 'backend-schema')
    except BaseException:
        adapter.set_mode('full')
        try:
            adapter.rollback_after_schema_migration()
            adapter.wait_healthy(plan)
            adapter.set_mode('normal')
            adapter.verify_mode('normal')
            adapter.record('restored-service', 'schema-recovery')
        except BaseException:
            adapter.set_mode('full')
            adapter.record('failed', 'schema-recovery')
            raise
        raise
