"""RLS negative test for the vault tables (Testcontainers PG 18). Household A cannot see B's vault
items or key envelopes; WITH CHECK refuses a foreign household_id. Skipped without Docker."""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from conftest import PgDatabase


async def _connect(container: PgDatabase, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=user,
        password=password,
        database=container.dbname,
    )


async def test_vault_items_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO vault_items (household_id, author_id, ciphertext) "
            "VALUES ($1,$3,'AAAA'), ($2,$3,'BBBB');",
            h_a,
            h_b,
            user,
        )
    finally:
        await su.close()

    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        await app.execute(
            "SELECT set_config('app.household_id', $1, false), "
            "set_config('app.user_id', $2, false);",
            str(h_a),
            str(user),
        )
        rows = await app.fetch("SELECT ciphertext FROM vault_items;")
        assert [r["ciphertext"] for r in rows] == ["AAAA"]  # B's secret is invisible
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO vault_items (household_id, author_id, ciphertext) VALUES ($1,$2,'X');",
                h_b,
                user,
            )
    finally:
        await app.close()


async def test_vault_envelopes_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO vault_key_envelopes (household_id, member_id, kind, wrapped_key) "
            "VALUES ($1,$3,'passphrase','KA'), ($2,$3,'passphrase','KB');",
            h_a,
            h_b,
            user,
        )
    finally:
        await su.close()

    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        await app.execute(
            "SELECT set_config('app.household_id', $1, false), "
            "set_config('app.user_id', $2, false);",
            str(h_a),
            str(user),
        )
        rows = await app.fetch("SELECT wrapped_key FROM vault_key_envelopes;")
        assert [r["wrapped_key"] for r in rows] == ["KA"]  # B's envelope is invisible
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO vault_key_envelopes (household_id, member_id, kind, wrapped_key) "
                "VALUES ($1,$2,'passphrase','X');",
                h_b,
                user,
            )
    finally:
        await app.close()
