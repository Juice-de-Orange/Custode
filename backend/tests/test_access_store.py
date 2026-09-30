"""Access-store round-trips against a real Redis (Testcontainers). Skipped without
Docker. Covers mint/load, the no-household principal, single + family revoke, the
active-household carry-forward — und den Unterschied zwischen den **zwei** Widerrufen
(11-S1g): einer beendet die Sitzung, der andere nur ihre Rechte."""

from __future__ import annotations

import uuid

from app.kernel.auth.access import (
    get_active_household,
    load_access,
    mint_access,
    revoke_access,
    revoke_access_family,
    revoke_access_tokens,
    set_active_household,
)
from app.kernel.auth.context import Role


async def test_mint_and_load_roundtrip(redis_db: None) -> None:
    uid, hid, fam = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = await mint_access(user_id=uid, household_id=hid, role=Role.admin, family_id=fam)
    claims = await load_access(token)
    assert claims is not None
    assert claims.user_id == uid
    assert claims.household_id == hid
    assert claims.role == Role.admin
    assert claims.family_id == fam


async def test_load_unknown_returns_none(redis_db: None) -> None:
    assert await load_access("kein-gueltiges-token") is None


async def test_mint_without_household(redis_db: None) -> None:
    uid, fam = uuid.uuid4(), uuid.uuid4()
    token = await mint_access(user_id=uid, household_id=None, role=None, family_id=fam)
    claims = await load_access(token)
    assert claims is not None
    assert claims.household_id is None
    assert claims.role is None


async def test_revoke_access_single(redis_db: None) -> None:
    token = await mint_access(
        user_id=uuid.uuid4(), household_id=None, role=None, family_id=uuid.uuid4()
    )
    await revoke_access(token)
    assert await load_access(token) is None


async def test_revoke_family_burns_all(redis_db: None) -> None:
    fam, uid = uuid.uuid4(), uuid.uuid4()
    t1 = await mint_access(user_id=uid, household_id=None, role=None, family_id=fam)
    t2 = await mint_access(user_id=uid, household_id=None, role=None, family_id=fam)
    await revoke_access_family(fam)
    assert await load_access(t1) is None
    assert await load_access(t2) is None


async def test_active_household_roundtrip(redis_db: None) -> None:
    fam, hid = uuid.uuid4(), uuid.uuid4()
    await set_active_household(fam, hid, Role.member)
    assert await get_active_household(fam) == (hid, Role.member)
    await set_active_household(fam, None, None)
    assert await get_active_household(fam) is None


async def test_family_revoke_also_clears_the_active_household(redis_db: None) -> None:
    """Die Sitzung ist beendet — es gibt nichts mehr fortzuschreiben."""
    fam, hid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = await mint_access(user_id=uid, household_id=hid, role=Role.admin, family_id=fam)
    await set_active_household(fam, hid, Role.admin)
    await revoke_access_family(fam)
    assert await load_access(token) is None
    assert await get_active_household(fam) is None


async def test_token_revoke_keeps_the_active_household(redis_db: None) -> None:
    """Der Unterschied, der 11-S1g trägt — und der leise brechen würde.

    Nach einem Rollenwechsel bleibt die Person Mitglied desselben Haushalts. Nimmt man ihr mit den
    Tokens auch den Merkzettel, steht sie nach der nächsten Rotation ohne Haushalts-Kontext da,
    obwohl sich an ihrer Mitgliedschaft nichts geändert hat. Wer die beiden Funktionen verwechselt,
    baut aus einer Herabstufung eine halbe Abmeldung.
    """
    fam, hid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    t1 = await mint_access(user_id=uid, household_id=hid, role=Role.admin, family_id=fam)
    t2 = await mint_access(user_id=uid, household_id=hid, role=Role.admin, family_id=fam)
    await set_active_household(fam, hid, Role.admin)

    await revoke_access_tokens(fam)

    assert await load_access(t1) is None
    assert await load_access(t2) is None
    assert await get_active_household(fam) == (hid, Role.admin)
    # Idempotent: ein zweiter Lauf über eine bereits leere Familie tut nichts und wirft nicht.
    await revoke_access_tokens(fam)
    assert await get_active_household(fam) == (hid, Role.admin)
