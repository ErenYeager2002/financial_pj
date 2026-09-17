from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..auth import UserContext, get_current_user, require_admin
from ..contracts import (
    SkillAvailabilityRead,
    SkillAvailabilityTransitionRequest,
    SkillReleaseImportRequest,
    SkillReleaseInboxItem,
    SkillReleaseMetadataUpdate,
    SkillReleasePublishRequest,
    SkillReleaseRead,
    SkillReleaseReviewRequest,
    SkillRolloutRead,
    SkillRolloutStartRequest,
    SkillSourceBindingConfirmRequest,
    SkillSourceBindingRead,
    SkillSourceDiscoveryRead,
    SkillSourceDiscoveryRequest,
    SkillSourcePrepareReleaseRequest,
    SkillSourceUpdateCheckRead,
)
from ..database import get_db
from ..skill_availability_service import (
    get_availability,
    list_availability,
    transition_availability,
)
from ..skill_release_service import (
    import_release,
    list_inbox_packages,
    list_releases,
    publish_release,
    review_release,
    update_release_metadata,
)
from ..skill_rollout_service import get_rollout, start_rollout
from ..skill_source_service import check_update, confirm_binding, discover_bindings, list_bindings
from ..skill_update_service import prepare_bound_release, update_bound_skill

router = APIRouter(prefix="/api/admin/skill-releases", tags=["admin-skill-releases"])
source_router = APIRouter(prefix="/api/admin/skill-sources", tags=["admin-skill-sources"])
availability_router = APIRouter(prefix="/api/admin/skills", tags=["admin-skills"])
rollout_router = APIRouter(prefix="/api/admin", tags=["admin-skill-rollouts"])


@rollout_router.post(
    "/skill-releases/{release_id}/rollout",
    response_model=SkillRolloutRead,
    status_code=202,
)
def admin_start_skill_rollout(
    release_id: str,
    body: SkillRolloutStartRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillRolloutRead:
    require_admin(current)
    return start_rollout(db, current, release_id, body.confirmation)


@rollout_router.get("/skill-rollouts/{rollout_id}", response_model=SkillRolloutRead)
def admin_get_skill_rollout(
    rollout_id: str,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillRolloutRead:
    require_admin(current)
    return get_rollout(db, rollout_id)


@availability_router.get("/availability", response_model=list[SkillAvailabilityRead])
def admin_list_skill_availability(
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[SkillAvailabilityRead]:
    require_admin(current)
    return list_availability(db)


@availability_router.get("/{skill_id}/availability", response_model=SkillAvailabilityRead)
def admin_get_skill_availability(
    skill_id: str,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillAvailabilityRead:
    require_admin(current)
    return get_availability(db, skill_id)


@availability_router.post("/{skill_id}/availability", response_model=SkillAvailabilityRead)
def admin_transition_skill_availability(
    skill_id: str,
    body: SkillAvailabilityTransitionRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillAvailabilityRead:
    require_admin(current)
    return transition_availability(db, current, skill_id, body.target_state, body.reason)


@source_router.get("/bindings", response_model=list[SkillSourceBindingRead])
def admin_list_skill_source_bindings(
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[SkillSourceBindingRead]:
    require_admin(current)
    return list_bindings(db)


@source_router.post("/discover", response_model=SkillSourceDiscoveryRead)
def admin_discover_skill_sources(
    body: SkillSourceDiscoveryRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillSourceDiscoveryRead:
    require_admin(current)
    return discover_bindings(db, body.repository_url, body.tracking_ref)


@source_router.post("/bindings", response_model=SkillSourceBindingRead, status_code=201)
def admin_confirm_skill_source_binding(
    body: SkillSourceBindingConfirmRequest,
    response: Response,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillSourceBindingRead:
    require_admin(current)
    binding, created = confirm_binding(db, current, body)
    if not created:
        response.status_code = 200
    return binding


@source_router.post("/bindings/{skill_id}/check-update", response_model=SkillSourceUpdateCheckRead)
def admin_check_skill_source_update(
    skill_id: str,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillSourceUpdateCheckRead:
    require_admin(current)
    return check_update(db, current, skill_id)


@source_router.post(
    "/bindings/{skill_id}/prepare-release",
    response_model=SkillReleaseRead,
    status_code=201,
)
def admin_prepare_bound_skill_release(
    skill_id: str,
    body: SkillSourcePrepareReleaseRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return prepare_bound_release(db, current, skill_id, body.version)


@availability_router.post("/{skill_id}/update", response_model=SkillReleaseRead)
def admin_update_disabled_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return update_bound_skill(db, current, skill_id)


@router.get("/inbox", response_model=list[SkillReleaseInboxItem])
def admin_list_release_inbox(
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[SkillReleaseInboxItem]:
    require_admin(current)
    return list_inbox_packages(db, current)


@router.get("", response_model=list[SkillReleaseRead])
def admin_list_skill_releases(
    skill_id: str = Query(default="", max_length=128),
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[SkillReleaseRead]:
    require_admin(current)
    return list_releases(db, current, skill_id)


@router.post("/import", response_model=SkillReleaseRead, status_code=201)
def admin_import_skill_release(
    body: SkillReleaseImportRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return import_release(db, current, body.package_name)


@router.patch("/{release_id}", response_model=SkillReleaseRead)
def admin_update_skill_release(
    release_id: str,
    body: SkillReleaseMetadataUpdate,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return update_release_metadata(db, current, release_id, body)


@router.post("/{release_id}/review", response_model=SkillReleaseRead)
def admin_review_skill_release(
    release_id: str,
    body: SkillReleaseReviewRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return review_release(db, current, release_id, body)


@router.post("/{release_id}/publish", response_model=SkillReleaseRead)
def admin_publish_skill_release(
    release_id: str,
    body: SkillReleasePublishRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return publish_release(db, current, release_id, body.confirmation)


from ..contracts import NativeSkillRead, SkillInstallCatalog, SkillInstallRequest
from ..native_skill_service import installation_catalog, install_native_skill


@source_router.post("/install-catalog", response_model=SkillInstallCatalog)
def admin_install_catalog(current: UserContext = Depends(get_current_user)):
    require_admin(current)
    return installation_catalog()


@source_router.post("/prepare-install", response_model=NativeSkillRead)
def admin_prepare_install(body: SkillInstallRequest, db: Session = Depends(get_db), current: UserContext = Depends(get_current_user)):
    require_admin(current)
    return install_native_skill(db, current, body)
