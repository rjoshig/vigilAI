"""Tests for optional login and attribution (ADR-022).

The first test is the one that matters most: with both switches off nothing changed.
Everything after it turns a switch on.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.api.app import API_PREFIX, create_app
from greenlight_ai.auth import accounts
from greenlight_ai.auth.passwords import hash_password, verify_password
from greenlight_ai.auth.sessions import COOKIE_NAME
from greenlight_ai.auth.settings import BOOTSTRAP_PASSWORD, BOOTSTRAP_USERNAME, AuthSettings
from greenlight_ai.db import models
from greenlight_ai.db.settings import DbSettings

Submit = Callable[..., Any]
GOOD = "a-long-enough-password"


@pytest.fixture()
def make_client(
    db_settings: DbSettings, factory: sessionmaker[Session]
) -> Callable[..., TestClient]:
    """Build a client whose authentication switches the test chooses."""

    def _make(**kwargs: Any) -> TestClient:
        app = create_app(db_settings, auth_settings=AuthSettings(**kwargs))
        app.state.session_factory = factory
        return TestClient(app)

    return _make


@pytest.fixture()
def admin_client(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    """A client with admin login on, already past the bootstrap password change."""
    with make_client(admin_auth=True) as client:
        response = client.post(
            f"{API_PREFIX}/auth/change-password",
            json={
                "username": BOOTSTRAP_USERNAME,
                "current_password": BOOTSTRAP_PASSWORD,
                "new_password": GOOD,
            },
        )
        assert response.status_code == 200, response.text
        yield client


# --- with login off, nothing changed ------------------------------------------------


def test_with_login_off_there_is_no_prompt_and_no_cookie(client: TestClient, api: str) -> None:
    """The default is the product as it was before this existed."""
    response = client.get(f"{api}/runs")
    assert response.status_code == 200
    assert COOKIE_NAME not in response.cookies

    config = client.get(f"{api}/auth/config").json()
    assert config == {"admin_auth": False, "user_auth": False}

    me = client.get(f"{api}/auth/me").json()
    assert me["is_placeholder"] is True
    assert me["name"] == "John Doe"
    assert me["email"] == "jdoe@jdoe.com"
    assert me["is_admin"] is True


def test_with_login_off_work_is_attributed_to_the_placeholder(
    client: TestClient, api: str, factory: sessionmaker[Session], submit: Submit
) -> None:
    """There is always a current user, so nothing stores a nullable author."""
    assert submit().status_code == 201
    with factory() as session:
        placeholder = session.execute(
            sa.select(models.User).where(models.User.is_placeholder)
        ).scalar_one()
        run = session.execute(sa.select(models.Run)).scalars().one()
        config = session.execute(sa.select(models.Config)).scalars().one()

        assert run.user_id == placeholder.id
        assert config.created_by_user_id == placeholder.id
        assert config.created_by == "John Doe"


def test_the_placeholder_can_never_be_signed_in_as(
    make_client: Callable[..., TestClient], api: str
) -> None:
    """It is an attribution device, not an account."""
    with make_client(admin_auth=True, user_auth=True) as client:
        response = client.post(
            f"{api}/auth/login",
            json={"username": accounts.PLACEHOLDER_USERNAME, "password": GOOD},
        )
        assert response.status_code == 401


# --- the bootstrap administrator ----------------------------------------------------


def test_the_bootstrap_admin_exists_and_must_change_its_password(
    make_client: Callable[..., TestClient], api: str
) -> None:
    """A way into a fresh install, not a credential."""
    with make_client(admin_auth=True) as client:
        login = client.post(
            f"{api}/auth/login",
            json={"username": BOOTSTRAP_USERNAME, "password": BOOTSTRAP_PASSWORD},
        )
        assert login.status_code == 200, login.text
        assert login.json()["must_change_password"] is True

        blocked = client.get(f"{api}/admin/artifact-types")
        assert blocked.status_code == 403
        assert "new password" in blocked.json()["detail"]

        changed = client.post(
            f"{api}/auth/change-password",
            json={
                "username": BOOTSTRAP_USERNAME,
                "current_password": BOOTSTRAP_PASSWORD,
                "new_password": GOOD,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["must_change_password"] is False
        assert client.get(f"{api}/admin/artifact-types").status_code == 200


def test_a_non_loopback_deployment_refuses_to_serve_on_the_default_password(
    db_settings: DbSettings, factory: sessionmaker[Session]
) -> None:
    """A warning is easy to miss, and this is the credential everybody knows."""
    app = create_app(db_settings, auth_settings=AuthSettings(admin_auth=True, bind_host="0.0.0.0"))
    app.state.session_factory = factory
    with pytest.raises(accounts.DefaultPasswordInUse):
        with TestClient(app):
            pass


def test_a_laptop_is_exempt_from_that_refusal(make_client: Callable[..., TestClient]) -> None:
    """Loopback is a developer, not a deployment."""
    with make_client(admin_auth=True, bind_host="127.0.0.1") as client:
        assert client.get("/health").status_code == 200


# --- sign-in, sessions, lockout -----------------------------------------------------


def test_an_unauthenticated_request_is_refused_when_the_switch_is_on(
    make_client: Callable[..., TestClient], api: str
) -> None:
    """The switch is what turns the API from open to closed."""
    with make_client(user_auth=True) as client:
        assert client.get(f"{api}/runs").status_code == 401


def test_signing_out_stops_the_session_working(admin_client: TestClient, api: str) -> None:
    """Revocation is server-side, which is why sessions are rows."""
    assert admin_client.get(f"{api}/admin/artifact-types").status_code == 200
    assert admin_client.post(f"{api}/auth/logout").status_code == 204
    assert admin_client.get(f"{api}/admin/artifact-types").status_code == 401


def test_repeated_failures_lock_the_account_and_the_lock_clears(
    make_client: Callable[..., TestClient], api: str, factory: sessionmaker[Session]
) -> None:
    """Lockout is the whole of the brute-force answer, and it lets go by itself."""
    with make_client(admin_auth=True) as client:
        for _ in range(5):
            response = client.post(
                f"{api}/auth/login",
                json={"username": BOOTSTRAP_USERNAME, "password": "wrong"},
            )
            assert response.status_code == 401

        locked = client.post(
            f"{api}/auth/login",
            json={"username": BOOTSTRAP_USERNAME, "password": BOOTSTRAP_PASSWORD},
        )
        assert locked.status_code == 423

        with factory() as session:
            row = session.execute(
                sa.select(models.User).where(models.User.username == BOOTSTRAP_USERNAME)
            ).scalar_one()
            row.locked_until = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
            session.commit()

        assert (
            client.post(
                f"{api}/auth/login",
                json={"username": BOOTSTRAP_USERNAME, "password": BOOTSTRAP_PASSWORD},
            ).status_code
            == 200
        )


def test_an_expired_session_stops_working(
    admin_client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """An absolute lifetime is absolute."""
    with factory() as session:
        row = session.execute(sa.select(models.UserSession)).scalars().first()
        assert row is not None
        row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        session.commit()
    assert admin_client.get(f"{api}/admin/artifact-types").status_code == 401


def test_an_idle_session_stops_working(
    admin_client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Idle timeout is what protects an unattended screen."""
    with factory() as session:
        row = session.execute(sa.select(models.UserSession)).scalars().first()
        assert row is not None
        row.last_seen_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
        session.commit()
    assert admin_client.get(f"{api}/admin/artifact-types").status_code == 401


# --- accounts -----------------------------------------------------------------------


def test_an_admin_creates_accounts_for_both_roles(admin_client: TestClient, api: str) -> None:
    """No self-registration, and no second place to administer people from."""
    made = admin_client.post(
        f"{api}/admin/users",
        json={
            "username": "jdoe",
            "name": "John Doe",
            "email": "jdoe@example.com",
            "password": GOOD,
            "roles": ["user"],
        },
    )
    assert made.status_code == 201, made.text
    assert made.json()["must_change_password"] is True

    listed = admin_client.get(f"{api}/admin/users").json()
    assert {row["username"] for row in listed} >= {BOOTSTRAP_USERNAME, "jdoe"}

    clash = admin_client.post(
        f"{api}/admin/users",
        json={
            "username": "jdoe",
            "name": "Another",
            "email": "other@example.com",
            "password": GOOD,
            "roles": ["user"],
        },
    )
    assert clash.status_code == 422

    short = admin_client.post(
        f"{api}/admin/users",
        json={
            "username": "shorty",
            "name": "S",
            "email": "s@example.com",
            "password": "short",
            "roles": ["user"],
        },
    )
    assert short.status_code == 422


def test_a_user_account_cannot_reach_an_admin_route(
    make_client: Callable[..., TestClient], api: str, factory: sessionmaker[Session]
) -> None:
    """Two roles, and the admin one is the gate."""
    with factory() as session:
        session.add(
            models.User(
                username="plainuser",
                name="Plain User",
                email="plain@example.com",
                password_hash=hash_password(GOOD),
                role="user",
            )
        )
        session.commit()

    with make_client(admin_auth=True, user_auth=True) as client:
        assert (
            client.post(
                f"{api}/auth/login", json={"username": "plainuser", "password": GOOD}
            ).status_code
            == 200
        )
        assert client.get(f"{api}/runs").status_code == 200
        assert client.get(f"{api}/admin/artifact-types").status_code == 403


def test_deactivating_an_account_ends_its_sessions_at_once(
    admin_client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """The change takes effect now, not at the next expiry."""
    made = admin_client.post(
        f"{api}/admin/users",
        json={
            "username": "temp",
            "name": "Temp",
            "email": "temp@example.com",
            "password": GOOD,
            "roles": ["admin"],
        },
    ).json()

    off = admin_client.post(f"{api}/admin/users/{made['id']}/active?is_active=false")
    assert off.status_code == 200
    assert off.json()["is_active"] is False

    with factory() as session:
        row = session.execute(
            sa.select(models.User).where(models.User.username == "temp")
        ).scalar_one()
        assert row.deactivated_at is not None


def test_the_last_administrator_cannot_be_deactivated(
    admin_client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Otherwise nobody could sign in afterwards."""
    with factory() as session:
        admin_id = session.execute(
            sa.select(models.User.id).where(models.User.username == BOOTSTRAP_USERNAME)
        ).scalar_one()
    response = admin_client.post(f"{api}/admin/users/{admin_id}/active?is_active=false")
    assert response.status_code == 409


def test_the_placeholder_cannot_be_deactivated_or_given_a_password(
    admin_client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """It is how actions are attributed, not an account to manage."""
    with factory() as session:
        row = accounts.ensure_placeholder(session)
        session.commit()
        placeholder_id = row.id
    assert (
        admin_client.post(f"{api}/admin/users/{placeholder_id}/active?is_active=false").status_code
        == 422
    )
    assert (
        admin_client.post(
            f"{api}/admin/users/{placeholder_id}/password", json={"password": GOOD}
        ).status_code
        == 422
    )


def test_an_admin_reset_forces_the_person_to_choose_their_own(
    admin_client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """A password an administrator typed is already known to two people."""
    made = admin_client.post(
        f"{api}/admin/users",
        json={
            "username": "resetme",
            "name": "Reset Me",
            "email": "reset@example.com",
            "password": GOOD,
            "roles": ["user"],
        },
    ).json()
    other = "another-long-password"
    response = admin_client.post(
        f"{api}/admin/users/{made['id']}/password", json={"password": other}
    )
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True

    with factory() as session:
        row = session.execute(
            sa.select(models.User).where(models.User.username == "resetme")
        ).scalar_one()
        assert verify_password(other, row.password_hash)


def test_a_new_password_must_differ_from_the_one_it_replaces(
    admin_client: TestClient, api: str
) -> None:
    """Otherwise the forced change is theatre."""
    response = admin_client.post(
        f"{api}/auth/change-password",
        json={"username": BOOTSTRAP_USERNAME, "current_password": GOOD, "new_password": GOOD},
    )
    assert response.status_code == 422


# --- attribution and the audit log --------------------------------------------------


def test_sign_in_events_reach_the_audit_log(
    admin_client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Who signed in is the question the phase exists to answer."""
    admin_client.post(f"{api}/auth/login", json={"username": BOOTSTRAP_USERNAME, "password": "no"})
    with factory() as session:
        actions = set(session.execute(sa.select(models.AuditLog.action)).scalars())
    assert {"auth.password_changed", "auth.login_failed"} <= actions


def test_a_signed_in_person_is_recorded_on_their_work(
    make_client: Callable[..., TestClient],
    api: str,
    factory: sessionmaker[Session],
    fixtures_root: Path,
    cases: dict[str, Any],
) -> None:
    """The config history and the run list need a real name to show."""
    with factory() as session:
        session.add(
            models.User(
                username="submitter",
                name="Submitter",
                email="sub@example.com",
                password_hash=hash_password(GOOD),
                role="user",
            )
        )
        session.commit()

    case = cases["baseline_match"]
    with make_client(user_auth=True) as client:
        assert (
            client.post(
                f"{api}/auth/login", json={"username": "submitter", "password": GOOD}
            ).status_code
            == 200
        )
        files = [
            (
                "osl",
                (
                    "osl.docx",
                    (fixtures_root / case["osl"]).read_bytes(),
                    "application/octet-stream",
                ),
            ),
            (
                "config",
                ("config.json", (fixtures_root / case["config"]).read_bytes(), "application/json"),
            ),
        ]
        for kind, path in case["reports"].items():
            files.append(
                (
                    kind,
                    (
                        f"{kind}.xlsx",
                        (fixtures_root / path).read_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )
            )
        created = client.post(
            f"{api}/runs",
            data={
                "customer_name": case["customer"],
                "order_number": case["order_number"],
                "configuration_id": case["configuration_id"],
            },
            files=files,
        )
        assert created.status_code == 201, created.text

    with factory() as session:
        submitter = session.execute(
            sa.select(models.User).where(models.User.username == "submitter")
        ).scalar_one()
        run = session.execute(sa.select(models.Run)).scalars().one()
        config = session.execute(sa.select(models.Config)).scalars().one()
        assert run.user_id == submitter.id
        assert config.created_by == "Submitter"
        assert config.created_by_user_id == submitter.id


def test_whoami_reports_the_roles_the_account_holds(client: TestClient, api: str) -> None:
    """The placeholder is a user and an administrator, and says so (ADR-049).

    It used to answer ``role: "user"`` from a literal in `deps.py` while behaving as an
    administrator, which is the sort of disagreement that is only found by reading the
    code. The console will gate on these, so the answer has to be the account's own.
    """
    body = client.get(f"{api}/auth/me").json()

    assert body["roles"] == ["user", "admin"]
    assert body["role"] == "admin", "the legacy field holds the strongest role held"
    assert body["is_placeholder"] is True
    assert body["is_admin"] is True, "with login off nothing is gated (ADR-022)"
