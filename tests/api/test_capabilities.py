"""The API enforces capabilities, not roles (Phase 6.20c, ADR-049).

**These are the tests that matter in this phase.** Hiding a nav item is not access
control; a door that only looks shut is worse than one that is plainly open, because
nobody checks it again. Everything here therefore talks to the API directly with the
login switches **on**, which is the only configuration in which any of it applies:
with them off there is one placeholder holding every capability and nothing is gated,
exactly as ADR-022 promises.

Two shapes, and both are needed:

- For a capability a **reviewer holds**, a plain ``user`` is refused and the reviewer
  is not — that is the reviewer role earning its existence.
- For a capability only an **administrator holds**, the reviewer is refused and the
  administrator is not — that is the line between judging the work and defining the
  deployment.

The refusal is asserted as **403**, never 404. The screen exists and is not theirs.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.api.app import API_PREFIX, create_app
from greenlight_ai.auth.passwords import hash_password
from greenlight_ai.auth.roles import Capability, capabilities_of
from greenlight_ai.auth.settings import BOOTSTRAP_USERNAME, AuthSettings
from greenlight_ai.db import models
from greenlight_ai.db.settings import DbSettings

PASSWORD = "a-long-enough-password"

#: One route per capability, chosen so the request reaches the guard and nothing else:
#: a read where reading is the gated act, and otherwise the smallest possible write.
#: A write that would be refused *after* the guard still tells us what we are asking —
#: the assertions below only ever say "403" or "not 403".
ROUTES: dict[Capability, tuple[str, str, Any]] = {
    Capability.VIEW_ADMIN: ("GET", "/admin/usage", None),
    Capability.APPROVE_TRAINING: ("GET", "/admin/candidates", None),
    Capability.MANAGE_RULES: ("GET", "/admin/rules", None),
    Capability.TEACH_MODEL: (
        "POST",
        "/admin/examples",
        {"stage": "s2_extract", "given": {}, "answer": {}},
    ),
    Capability.MANAGE_REFERENCE: (
        "POST",
        "/admin/aliases",
        {"canonical_name": "state", "alias": "st"},
    ),
    Capability.MANAGE_PRIVACY: ("GET", "/admin/masked-columns", None),
    Capability.MANAGE_ARTIFACTS: ("GET", "/admin/artifact-types", None),
    Capability.MANAGE_PROGRAMMES: ("GET", "/admin/programme-rules", None),
    Capability.MANAGE_MEANING: ("GET", "/admin/meaning", None),
    Capability.MANAGE_USERS: ("GET", "/admin/users", None),
    Capability.MANAGE_SETTINGS: ("GET", "/admin/settings", None),
}


@pytest.fixture()
def locked_client(db_settings: DbSettings, factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """A client with **both** login switches on.

    Yields:
        The client. Nothing is signed in yet, so every admin route answers 401 until a
        test signs somebody in.
    """
    app = create_app(db_settings, auth_settings=AuthSettings(admin_auth=True, user_auth=True))
    app.state.session_factory = factory
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def sign_in(locked_client: TestClient, factory: sessionmaker[Session]) -> Callable[..., TestClient]:
    """Sign in as a fresh account holding exactly the roles asked for.

    Returns:
        A callable taking the roles and returning the same client, now carrying that
        account's session cookie.

    The row is written directly rather than through ``POST /admin/users``, because the
    account-creation route is itself one of the things under test here and a test that
    needs an administrator to make a reviewer cannot check what a reviewer may do.
    """
    made: list[str] = []

    def _sign_in(*roles: str) -> TestClient:
        username = f"{'-'.join(roles)}-{len(made)}"
        made.append(username)
        with factory() as session:
            session.add(
                models.User(
                    username=username,
                    name=username,
                    email=f"{username}@localhost",
                    password_hash=hash_password(PASSWORD),
                    roles=list(roles),
                    is_active=True,
                    must_change_password=False,
                )
            )
            session.commit()
        response = locked_client.post(
            f"{API_PREFIX}/auth/login",
            json={"username": username, "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
        return locked_client

    return _sign_in


def _call(client: TestClient, capability: Capability) -> int:
    """Make the request that stands for one capability.

    Args:
        client: The signed-in client.
        capability: Which route to reach for.

    Returns:
        The status code.
    """
    method, path, body = ROUTES[capability]
    url = f"{API_PREFIX}{path}"
    if method == "GET":
        return client.get(url).status_code
    return client.post(url, json=body).status_code


# --- every capability, from both sides ----------------------------------------------


@pytest.mark.parametrize("capability", sorted(Capability, key=lambda c: c.value))
def test_an_administrator_is_never_refused(
    sign_in: Callable[..., TestClient], capability: Capability
) -> None:
    """An administrator holds all eleven, so none of these routes may answer 403."""
    client = sign_in("user", "admin")

    assert _call(client, capability) != 403, capability.value


@pytest.mark.parametrize("capability", sorted(capabilities_of(["reviewer"]), key=lambda c: c.value))
def test_a_reviewer_reaches_what_judging_the_work_needs(
    sign_in: Callable[..., TestClient], capability: Capability
) -> None:
    """The five a reviewer holds. Refusing any of them makes the role a half-job."""
    client = sign_in("user", "reviewer")

    assert _call(client, capability) != 403, capability.value


@pytest.mark.parametrize(
    "capability",
    sorted(capabilities_of(["admin"]) - capabilities_of(["reviewer"]), key=lambda c: c.value),
)
def test_a_reviewer_is_refused_what_defines_the_deployment(
    sign_in: Callable[..., TestClient], capability: Capability
) -> None:
    """The six only an administrator holds: programmes, artifacts, meaning, accounts,
    settings and masked columns."""
    client = sign_in("user", "reviewer")

    assert _call(client, capability) == 403, capability.value


@pytest.mark.parametrize("capability", sorted(Capability, key=lambda c: c.value))
def test_a_plain_user_reaches_none_of_the_console(
    sign_in: Callable[..., TestClient], capability: Capability
) -> None:
    """Including the dashboard. Somebody who can change nothing is not invited in."""
    client = sign_in("user")

    assert _call(client, capability) == 403, capability.value


def test_holding_user_and_reviewer_is_exactly_a_reviewer(
    sign_in: Callable[..., TestClient],
) -> None:
    """Roles add up and never subtract, which is the whole point of the union."""
    client = sign_in("user", "reviewer")

    assert client.get(f"{API_PREFIX}/auth/me").json()["roles"] == ["user", "reviewer"]
    assert _call(client, Capability.APPROVE_TRAINING) != 403
    assert _call(client, Capability.MANAGE_SETTINGS) == 403


# --- what the consoles read, so they do not reimplement the matrix -------------------


def test_whoami_reports_the_capabilities_not_just_the_roles(
    sign_in: Callable[..., TestClient],
) -> None:
    """Neither app has to know the matrix; it reads the answer (6.20d).

    A console that derived capabilities from role names would disagree with the API the
    first time a grant moved — and would disagree in the worst direction, by offering a
    screen that then refuses.
    """
    client = sign_in("user", "reviewer")

    me = client.get(f"{API_PREFIX}/auth/me").json()

    assert me["capabilities"] == sorted(
        capability.value for capability in capabilities_of(["user", "reviewer"])
    )
    assert "manage_settings" not in me["capabilities"]
    assert me["is_admin"] is False


def test_the_placeholder_reports_everything_while_login_is_off(client: TestClient) -> None:
    """Which is what keeps both sidebars exactly as they were (ADR-022)."""
    me = client.get(f"{API_PREFIX}/auth/me").json()

    assert me["is_placeholder"] is True
    assert me["capabilities"] == sorted(capability.value for capability in Capability)


# --- the refusal says the right thing ------------------------------------------------


def test_the_refusal_is_403_and_names_what_was_missing(
    sign_in: Callable[..., TestClient],
) -> None:
    """404 would make a support conversation impossible; a bare 403 nearly as much."""
    client = sign_in("user", "reviewer")

    response = client.get(f"{API_PREFIX}/admin/settings")

    assert response.status_code == 403
    assert "settings" in response.json()["detail"]


def test_nobody_signed_in_is_401_rather_than_403(locked_client: TestClient) -> None:
    """The distinction a console needs to know whether to show a sign-in screen."""
    assert locked_client.get(f"{API_PREFIX}/admin/usage").status_code == 401


# --- the routes whose capability depends on a parameter ------------------------------


def test_a_reviewer_may_bulk_delete_aliases_but_not_masked_columns(
    sign_in: Callable[..., TestClient],
) -> None:
    """One route, five tables, and the capability is not known until it is read."""
    client = sign_in("user", "reviewer")
    body = {"ids": [1], "confirm": "delete"}

    assert client.post(f"{API_PREFIX}/admin/aliases/bulk-delete", json=body).status_code != 403
    assert (
        client.post(f"{API_PREFIX}/admin/masked-columns/bulk-delete", json=body).status_code == 403
    )


def test_a_reviewer_may_not_revert_an_artifact_type(
    sign_in: Callable[..., TestClient],
) -> None:
    """Putting a definition back is as strong an act as the edit it undoes."""
    client = sign_in("user", "reviewer")

    response = client.post(
        f"{API_PREFIX}/admin/versions/artifact-type/dirt/1/revert",
        json={"confirm": "revert"},
    )

    assert response.status_code == 403


def test_a_reviewer_reads_the_programme_list_but_cannot_write_one(
    sign_in: Callable[..., TestClient],
) -> None:
    """The one deliberate exception, recorded so it can be argued with.

    Four screens a reviewer works on — checks, compliance rules, examples and
    reference data — scope what they are editing to a delivery programme, so all four
    fetch the programme list. Reading that list is not *managing programmes*; writing
    one is, and that is refused.
    """
    client = sign_in("user", "reviewer")

    assert client.get(f"{API_PREFIX}/admin/scopes").status_code == 200
    assert (
        client.post(
            f"{API_PREFIX}/admin/scopes",
            json={"code": "NEW", "label": "invented by a reviewer"},
        ).status_code
        == 403
    )


# --- and with the switches off, none of it applies ----------------------------------


@pytest.mark.parametrize("capability", sorted(Capability, key=lambda c: c.value))
def test_with_login_off_nothing_is_gated(client: TestClient, capability: Capability) -> None:
    """ADR-022: with both switches off the behaviour is exactly what it was before
    login existed, and the placeholder holding `user` and `admin` is what keeps it so."""
    assert _call(client, capability) != 403, capability.value


# --- assigning roles (6.20e) ---------------------------------------------------------


def test_the_roles_catalogue_carries_the_wording_from_the_matrix(
    sign_in: Callable[..., TestClient],
) -> None:
    """One sentence per role, from beside the grants, so the screen cannot invent one."""
    client = sign_in("user", "admin")

    body = client.get(f"{API_PREFIX}/admin/users/roles").json()

    assert [entry["role"] for entry in body] == ["user", "reviewer", "admin"]
    assert all(entry["description"] for entry in body)


def test_roles_are_a_set_and_the_union_takes_effect_at_once(
    sign_in: Callable[..., TestClient], locked_client: TestClient
) -> None:
    """Saving two roles grants both; the account's next request has the capabilities."""
    admin = sign_in("user", "admin")
    created = admin.post(
        f"{API_PREFIX}/admin/users",
        json={
            "username": "senior",
            "name": "A senior associate",
            "email": "senior@localhost",
            "password": PASSWORD,
            "roles": ["user"],
        },
    ).json()

    promoted = admin.post(
        f"{API_PREFIX}/admin/users/{created['id']}/roles",
        json={"roles": ["user", "reviewer"]},
    )

    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["roles"] == ["user", "reviewer"]


def test_nothing_ticked_still_leaves_a_plain_user(
    sign_in: Callable[..., TestClient],
) -> None:
    """Saving an empty form is a mistake, not a way to lock somebody out of everything."""
    admin = sign_in("user", "admin")
    created = admin.post(
        f"{API_PREFIX}/admin/users",
        json={
            "username": "nobody",
            "name": "Nobody",
            "email": "nobody@localhost",
            "password": PASSWORD,
            "roles": ["reviewer"],
        },
    ).json()

    response = admin.post(f"{API_PREFIX}/admin/users/{created['id']}/roles", json={"roles": []})

    assert response.status_code == 200
    assert response.json()["roles"] == ["user"]


def test_the_last_administrator_cannot_demote_themselves(
    sign_in: Callable[..., TestClient],
) -> None:
    """Unrecoverable without a database edit, so it is refused rather than warned about.

    A deployment with admin login on has a bootstrap administrator from the start, so
    being the last one takes deactivating it first — which is the realistic way somebody
    arrives here: they made their own account, retired the shipped one, and then tried
    to hand their console access back.
    """
    admin = sign_in("user", "admin")
    me = admin.get(f"{API_PREFIX}/auth/me").json()
    bootstrap = next(
        row
        for row in admin.get(f"{API_PREFIX}/admin/users").json()
        if row["username"] == BOOTSTRAP_USERNAME
    )
    retired = admin.post(f"{API_PREFIX}/admin/users/{bootstrap['id']}/active?is_active=false")
    assert retired.status_code == 200, retired.text

    response = admin.post(
        f"{API_PREFIX}/admin/users/{me['id']}/roles", json={"roles": ["user", "reviewer"]}
    )

    assert response.status_code == 409
    assert "last administrator" in response.json()["detail"]
    assert admin.get(f"{API_PREFIX}/auth/me").json()["roles"] == ["user", "admin"]


def test_the_last_administrator_cannot_be_deactivated_either(
    sign_in: Callable[..., TestClient],
) -> None:
    """The other half of the same rule, and the one that was already there."""
    admin = sign_in("user", "admin")
    me = admin.get(f"{API_PREFIX}/auth/me").json()
    bootstrap = next(
        row
        for row in admin.get(f"{API_PREFIX}/admin/users").json()
        if row["username"] == BOOTSTRAP_USERNAME
    )
    admin.post(f"{API_PREFIX}/admin/users/{bootstrap['id']}/active?is_active=false")

    response = admin.post(f"{API_PREFIX}/admin/users/{me['id']}/active?is_active=false")

    assert response.status_code == 409


def test_an_administrator_may_be_demoted_once_there_is_another(
    sign_in: Callable[..., TestClient],
) -> None:
    """The rule protects the deployment, not any particular person."""
    admin = sign_in("user", "admin")
    me = admin.get(f"{API_PREFIX}/auth/me").json()
    created = admin.post(
        f"{API_PREFIX}/admin/users",
        json={
            "username": "second",
            "name": "A second administrator",
            "email": "second@localhost",
            "password": PASSWORD,
            "roles": ["user", "admin"],
        },
    )
    assert created.status_code == 201, created.text

    response = admin.post(
        f"{API_PREFIX}/admin/users/{me['id']}/roles", json={"roles": ["user", "reviewer"]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["user", "reviewer"]


def test_the_placeholders_roles_are_not_editable(
    sign_in: Callable[..., TestClient],
) -> None:
    """They are what makes the product work with login off (ADR-022)."""
    admin = sign_in("user", "admin")
    placeholder = next(
        row for row in admin.get(f"{API_PREFIX}/admin/users").json() if row["is_placeholder"]
    )

    response = admin.post(
        f"{API_PREFIX}/admin/users/{placeholder['id']}/roles", json={"roles": ["user"]}
    )

    assert response.status_code == 422


def test_an_unknown_role_is_refused_rather_than_stored(
    sign_in: Callable[..., TestClient],
) -> None:
    """A typo must not become a role nobody can see in the matrix."""
    admin = sign_in("user", "admin")
    created = admin.post(
        f"{API_PREFIX}/admin/users",
        json={
            "username": "typo",
            "name": "Typo",
            "email": "typo@localhost",
            "password": PASSWORD,
            "roles": ["user"],
        },
    ).json()

    response = admin.post(
        f"{API_PREFIX}/admin/users/{created['id']}/roles", json={"roles": ["superuser"]}
    )

    assert response.status_code == 422


def test_a_role_change_is_attributed_like_everything_else(
    sign_in: Callable[..., TestClient], factory: sessionmaker[Session]
) -> None:
    """Who widened somebody's access, and from what to what (ADR-022)."""
    admin = sign_in("user", "admin")
    created = admin.post(
        f"{API_PREFIX}/admin/users",
        json={
            "username": "audited",
            "name": "Audited",
            "email": "audited@localhost",
            "password": PASSWORD,
            "roles": ["user"],
        },
    ).json()
    admin.post(
        f"{API_PREFIX}/admin/users/{created['id']}/roles",
        json={"roles": ["user", "reviewer"]},
    )

    with factory() as session:
        entry = (
            session.execute(
                sa.select(models.AuditLog)
                .where(models.AuditLog.action == "admin.user_roles_changed")
                .order_by(models.AuditLog.id.desc())
            )
            .scalars()
            .first()
        )

    assert entry is not None
    assert "user -> user, reviewer" in entry.detail


def test_a_reviewer_cannot_assign_roles_at_all(
    sign_in: Callable[..., TestClient],
) -> None:
    """The obvious escalation: granting yourself what you were not given."""
    reviewer = sign_in("user", "reviewer")

    assert (
        reviewer.post(f"{API_PREFIX}/admin/users/1/roles", json={"roles": ["admin"]}).status_code
        == 403
    )
