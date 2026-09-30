"""economy use-cases — the household's append-only double-entry points ledger (KONZEPT §5.9,
ADR-0035). Services run on the request's RLS-scoped session (``household_id = app.household_id``);
the dependency commits the unit of work. Balances are SUMs, never stored. No negative balances:
every sink with a member/escrow source is coverage-checked before it is booked."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.modules.economy.models import LedgerEntry, Redemption, Reward
from app.modules.economy.schemas import RewardCreate, RewardUpdate

SYSTEM = "system"


def member_account(user_id: uuid.UUID) -> str:
    return f"member:{user_id}"


def escrow_account(listing_id: uuid.UUID) -> str:
    return f"escrow:{listing_id}"


async def balance(session: AsyncSession, *, account: str) -> int:
    """Current balance of an account = sum(amount where to=account) minus sum(amount where
    from=account). RLS scopes the sum to the active household."""
    credited = (
        await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.to_account == account
            )
        )
    ) or 0
    debited = (
        await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.from_account == account
            )
        )
    ) or 0
    return int(credited) - int(debited)


async def expire_member_balance(
    session: AsyncSession, *, household_id: uuid.UUID, member_id: uuid.UUID
) -> int:
    """Restpunkte einer ausscheidenden Person verfallen lassen (KONZEPT §5.1, `ref_type` dort
    wörtlich als ``member_exit`` festgelegt). Gibt den verfallenen Betrag zurück.

    Warum nicht löschen: der Ledger ist eine **doppelte** Buchführung, und Salden sind Summen, nie
    gespeicherte Felder (ADR-0035). Jede Buchung hat zwei Konten — wer die Zeilen einer Person
    entfernte, veränderte damit die Salden **anderer** Mitglieder (ein Danke-Punkt
    ``member:A -> member:B`` gehört beiden Seiten) und könnte sie unter null drücken, was die
    Invariante „keine negativen Salden, nirgends" bricht. Stattdessen eine **neue** Zeile, die den
    Rest nach ``system`` bucht: die Historie bleibt vollständig, das Konto endet auf null.

    Muss **nach** dem Auflösen der Handelspositionen laufen — sonst kommt freigegebenes Escrow
    nach dem Verfall an und liegt auf einem Konto, das niemandem mehr gehört. Idempotent: ein
    zweiter Lauf findet Saldo 0 und bucht nichts.
    """
    account = member_account(member_id)
    remaining = await balance(session, account=account)
    if remaining <= 0:
        # Ein negativer Saldo kann nicht entstehen (Deckungsprüfung vor jeder Buchung); wäre er da,
        # wäre eine Ausgleichsbuchung eine stille Korrektur an einer Invariante — also nichts tun.
        return 0
    await transfer(
        session,
        household_id=household_id,
        frm=account,
        to=SYSTEM,
        amount=remaining,
        ref_type="member_exit",
        created_by=member_id,
        note=None,
    )
    return remaining


async def transfer(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    frm: str,
    to: str,
    amount: int,
    ref_type: str,
    ref_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    note: str | None = None,
) -> LedgerEntry:
    """Append one ledger movement ``frm -> to`` (``amount > 0``). The ``system`` account mints/sinks
    freely; any other source is coverage-checked (balance ≥ amount) so a balance never goes negative
    (KONZEPT §5.9). Returns the new (flushed) entry. Append-only — never updates an existing row."""
    if amount <= 0:
        raise ProblemException(slug="invalid_amount", title="Betrag muss positiv sein", status=422)
    if frm == to:
        raise ProblemException(slug="invalid_transfer", title="Quelle == Ziel", status=422)
    if frm != SYSTEM and await balance(session, account=frm) < amount:
        raise ProblemException(slug="insufficient_funds", title="Nicht genug Punkte", status=422)
    entry = LedgerEntry(
        household_id=household_id,
        from_account=frm,
        to_account=to,
        amount=amount,
        ref_type=ref_type,
        ref_id=ref_id,
        created_by=created_by,
        note=note,
    )
    session.add(entry)
    await session.flush()
    return entry


async def credit_task_completion(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    amount: int,
    instance_id: uuid.UUID,
) -> None:
    """Mint ``amount`` points to a member for completing a task (``system -> member``). No-op for
    a zero-point task. Called synchronously inside the tasks-completion transaction (ADR-0035)."""
    if amount <= 0:
        return
    await transfer(
        session,
        household_id=household_id,
        frm=SYSTEM,
        to=member_account(member_id),
        amount=amount,
        ref_type="task_completion",
        ref_id=instance_id,
        created_by=member_id,
    )


async def list_member_entries(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int
) -> list[LedgerEntry]:
    """The caller's most recent ledger movements (where they are source or target), newest first."""
    account = member_account(user_id)
    rows = await session.scalars(
        select(LedgerEntry)
        .where(or_(LedgerEntry.from_account == account, LedgerEntry.to_account == account))
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .limit(limit)
    )
    return list(rows)


async def admin_correction(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    admin_id: uuid.UUID,
    member_id: uuid.UUID,
    amount: int,
    note: str | None,
) -> LedgerEntry:
    """Admin grants (amount > 0: system -> member) or claws back (amount < 0: member -> system)
    with a visible counter-entry (no silent edit, KONZEPT §5.9). Claw-back is coverage-checked."""
    if amount == 0:
        raise ProblemException(slug="invalid_amount", title="Betrag != 0 erforderlich", status=422)
    member = member_account(member_id)
    if amount > 0:
        frm, to, value = SYSTEM, member, amount
    else:
        frm, to, value = member, SYSTEM, -amount
    return await transfer(
        session,
        household_id=household_id,
        frm=frm,
        to=to,
        amount=value,
        ref_type="admin_correction",
        ref_id=member_id,
        created_by=admin_id,
        note=note,
    )


# --- Rewards (admin catalog) -------------------------------------------------


async def create_reward(
    session: AsyncSession, *, household_id: uuid.UUID, data: RewardCreate
) -> Reward:
    """Create a reward (admin). Emits ``reward.changed``."""
    reward = Reward(
        household_id=household_id,
        title=data.title,
        description=data.description,
        cost=data.cost,
        stock=data.stock,
        cooldown_hours=data.cooldown_hours,
        kind=data.kind,
        active=data.active,
    )
    session.add(reward)
    await emit(session, type="reward.changed", household_id=household_id, payload={})
    await session.flush()
    return reward


async def list_rewards(session: AsyncSession, *, include_inactive: bool) -> list[Reward]:
    """The household's rewards (RLS-scoped). Members see only active ones; admins see all."""
    stmt = select(Reward).where(Reward.deleted_at.is_(None))
    if not include_inactive:
        stmt = stmt.where(Reward.active.is_(True))
    rows = await session.scalars(stmt.order_by(Reward.cost))
    return list(rows)


async def get_reward(session: AsyncSession, *, reward_id: uuid.UUID) -> Reward:
    reward = await session.get(Reward, reward_id)
    if reward is None or reward.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Belohnung nicht gefunden", status=404)
    return reward


async def update_reward(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    reward_id: uuid.UUID,
    expected_version: int,
    data: RewardUpdate,
) -> Reward:
    """Patch a reward under optimistic concurrency (admin). Emits ``reward.changed``."""
    reward = await get_reward(session, reward_id=reward_id)
    if reward.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Belohnung zwischenzeitlich geändert", status=412
        )
    for field in ("title", "description", "cost", "stock", "cooldown_hours", "kind", "active"):
        value = getattr(data, field)
        if value is not None:
            setattr(reward, field, value)
    await emit(session, type="reward.changed", household_id=household_id, payload={})
    await session.flush()
    await session.refresh(reward, attribute_names=["version", "updated_at"])
    return reward


async def delete_reward(
    session: AsyncSession, *, household_id: uuid.UUID, reward_id: uuid.UUID
) -> None:
    """Soft-delete a reward (admin). Past redemptions keep their snapshot. Emits reward.changed."""
    reward = await get_reward(session, reward_id=reward_id)
    reward.deleted_at = datetime.now(UTC)
    await emit(session, type="reward.changed", household_id=household_id, payload={})


# --- Redemptions (member redeem; admin fulfil) -------------------------------


async def redeem_reward(
    session: AsyncSession, *, household_id: uuid.UUID, reward_id: uuid.UUID, member_id: uuid.UUID
) -> Redemption:
    """Redeem a reward for a member: validate (active/stock/cooldown), debit points
    (member -> system, coverage-checked), decrement stock, record a ``requested`` redemption, and
    emit ``reward.redeemed`` (drives the admin's live confirm list). All in one transaction."""
    reward = await get_reward(session, reward_id=reward_id)
    if not reward.active:
        raise ProblemException(slug="reward_inactive", title="Belohnung inaktiv", status=409)
    if reward.stock is not None and reward.stock <= 0:
        raise ProblemException(slug="out_of_stock", title="Kontingent erschöpft", status=409)
    if reward.cooldown_hours:
        since = datetime.now(UTC) - timedelta(hours=reward.cooldown_hours)
        recent = await session.scalar(
            select(func.count())
            .select_from(Redemption)
            .where(
                Redemption.reward_id == reward_id,
                Redemption.member_id == member_id,
                Redemption.created_at >= since,
            )
        )
        if recent:
            raise ProblemException(slug="cooldown_active", title="Noch in Cooldown", status=409)

    # Debit the points first (coverage check -> 422 if not enough). Append-only ledger.
    await transfer(
        session,
        household_id=household_id,
        frm=member_account(member_id),
        to=SYSTEM,
        amount=reward.cost,
        ref_type="reward_redemption",
        ref_id=reward_id,
        created_by=member_id,
    )
    if reward.stock is not None:
        reward.stock -= 1
    redemption = Redemption(
        household_id=household_id,
        reward_id=reward_id,
        member_id=member_id,
        title=reward.title,
        cost=reward.cost,
        status="requested",
    )
    session.add(redemption)
    await emit(session, type="reward.redeemed", household_id=household_id, payload={})
    await session.flush()
    return redemption


async def list_redemptions(
    session: AsyncSession, *, user_id: uuid.UUID, all_members: bool, status: str | None
) -> list[Redemption]:
    """Redemptions (RLS-scoped). Admins see the whole household (confirm list); members see own.
    Optional status filter, newest first."""
    stmt = select(Redemption).where(Redemption.deleted_at.is_(None))
    if not all_members:
        stmt = stmt.where(Redemption.member_id == user_id)
    if status is not None:
        stmt = stmt.where(Redemption.status == status)
    rows = await session.scalars(stmt.order_by(Redemption.created_at.desc(), Redemption.id.desc()))
    return list(rows)


async def fulfil_redemption(
    session: AsyncSession, *, household_id: uuid.UUID, redemption_id: uuid.UUID
) -> Redemption:
    """Admin marks a redemption fulfilled (``requested -> fulfilled``). 409 if not requested.
    Emits ``reward.redeemed`` (refresh the lists)."""
    redemption = await session.get(Redemption, redemption_id)
    if redemption is None or redemption.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Einlösung nicht gefunden", status=404)
    if redemption.status != "requested":
        raise ProblemException(slug="invalid_state", title="Einlösung nicht offen", status=409)
    redemption.status = "fulfilled"
    await emit(session, type="reward.redeemed", household_id=household_id, payload={})
    await session.flush()
    return redemption


# --- Thanks + weekly challenge (KONZEPT §5.9) --------------------------------

THANKS_WEEKLY_CAP = 10  # default per-member cap on thank-you points given per ISO week


def _week_start(now: datetime) -> datetime:
    """Start of the current ISO week (Monday 00:00 UTC). The weekly challenge resets here and the
    thank-you cap is measured within it (KONZEPT §5.9: Reset Sonntagabend)."""
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


async def thanks_given_this_week(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Total thank-you points the member has GIVEN since the week started."""
    start = _week_start(datetime.now(UTC))
    total = await session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.from_account == member_account(user_id),
            LedgerEntry.ref_type == "thanks",
            LedgerEntry.created_at >= start,
        )
    )
    return int(total or 0)


async def send_thanks(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    from_user: uuid.UUID,
    to_user: uuid.UUID,
    amount: int,
    note: str | None,
) -> int:
    """Transfer ``amount`` thank-you points member -> member (KONZEPT §5.9): coverage-checked (the
    giver spends from their own balance) AND capped to ``THANKS_WEEKLY_CAP`` per ISO week. Emits
    ``thanks.sent``. Returns the giver's remaining weekly allowance."""
    if to_user == from_user:
        raise ProblemException(slug="invalid_transfer", title="Nicht an sich selbst", status=422)
    given = await thanks_given_this_week(session, user_id=from_user)
    if given + amount > THANKS_WEEKLY_CAP:
        raise ProblemException(
            slug="thanks_cap_reached", title="Wochen-Limit für Danke erreicht", status=422
        )
    await transfer(
        session,
        household_id=household_id,
        frm=member_account(from_user),
        to=member_account(to_user),
        amount=amount,
        ref_type="thanks",
        ref_id=to_user,
        created_by=from_user,
        note=note,
    )
    await emit(session, type="thanks.sent", household_id=household_id, payload={})
    return THANKS_WEEKLY_CAP - (given + amount)


FAIRNESS_WINDOW_DAYS = 30  # rolling window for the fairness account


async def _earnings_since(session: AsyncSession, *, since: datetime) -> dict[uuid.UUID, int]:
    """Points earned from task completions per member since ``since`` (RLS-scoped). The shared
    rollup behind the weekly challenge and the fairness account (KONZEPT §5.9)."""
    rows = await session.execute(
        select(LedgerEntry.to_account, func.sum(LedgerEntry.amount))
        .where(
            LedgerEntry.ref_type == "task_completion",
            LedgerEntry.to_account.like("member:%"),
            LedgerEntry.created_at >= since,
        )
        .group_by(LedgerEntry.to_account)
    )
    return {uuid.UUID(account.removeprefix("member:")): int(total) for account, total in rows.all()}


async def weekly_challenge(session: AsyncSession) -> list[tuple[uuid.UUID, int]]:
    """Standings of the current weekly challenge: points EARNED from task completions per member
    since the week started, highest first (KONZEPT §5.9, live from the ledger — no counter)."""
    earnings = await _earnings_since(session, since=_week_start(datetime.now(UTC)))
    return sorted(earnings.items(), key=lambda s: s[1], reverse=True)


async def fairness_load(
    session: AsyncSession, *, window_days: int = FAIRNESS_WINDOW_DAYS
) -> dict[uuid.UUID, int]:
    """Each member's fairness load = points earned from task completions over the rolling window
    (KONZEPT §5.9). Lower = carried less = next in line (the marketplace tiebreaker, S8). Members
    with no completions in the window are simply absent (load 0). Absence-exclusion = Phase 5."""
    since = datetime.now(UTC) - timedelta(days=window_days)
    return await _earnings_since(session, since=since)
