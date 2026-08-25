from __future__ import annotations

from helpers import auth_client

PNG = b"\x89PNG\r\n\x1a\n" + b"avatar-image"


def test_user_can_upload_and_read_own_avatar() -> None:
    with auth_client(username="avatar-owner") as client:
        uploaded = client.post(
            "/api/profile/avatar",
            files={"upload": ("avatar.png", PNG, "image/png")},
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["avatar_updated_at"] is not None

        session = client.get("/api/session")
        assert session.status_code == 200
        assert session.json()["avatar_updated_at"] is not None

        avatar = client.get("/api/profile/avatar")
        assert avatar.status_code == 200
        assert avatar.content == PNG
        assert avatar.headers["content-type"].startswith("image/png")
        assert avatar.headers["x-content-type-options"] == "nosniff"


def test_avatar_rejects_unsupported_or_oversized_files() -> None:
    with auth_client(username="avatar-validation") as client:
        unsupported = client.post(
            "/api/profile/avatar",
            files={"upload": ("avatar.svg", b"<svg></svg>", "image/svg+xml")},
        )
        assert unsupported.status_code == 415

        oversized = client.post(
            "/api/profile/avatar",
            files={
                "upload": (
                    "avatar.png",
                    b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024),
                    "image/png",
                )
            },
        )
        assert oversized.status_code == 413


def test_avatar_is_private_to_the_authenticated_user() -> None:
    with auth_client(username="avatar-first-user") as first:
        assert (
            first.post(
                "/api/profile/avatar",
                files={"upload": ("avatar.png", PNG, "image/png")},
            ).status_code
            == 200
        )

    with auth_client(username="avatar-second-user") as second:
        assert second.get("/api/profile/avatar").status_code == 404
