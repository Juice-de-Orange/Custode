"""marketplace use-cases — handelbare Aufgaben mit Escrow (KONZEPT §5.10). Services run on the
request's RLS-scoped session; the dependency commits the unit of work.

Escrow läuft ausschließlich über das append-only economy-Ledger (ADR-0035): beim Listing wird der
Preis ``member:seller -> escrow:<listing_id>`` reserviert (Deckungsprüfung → keine negativen Salden,
kein Doppel-Listing); bei Erledigung ``escrow -> member:buyer``, bei Rückzug ``escrow ->
member:seller``. Cross-Modul nur über ``tasks.api`` (Instanz prüfen/zuweisen) + ``economy.api``
(buchen) — einseitig, kein Zyklus. Auto-Accept + Verfall→Rückfall-Cron = S8b."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.modules.economy import api as economy_api
from app.modules.marketplace.models import AutoAcceptRule, MarketListing
from app.modules.tasks import api as tasks_api


async def get_listing(session: AsyncSession, *, listing_id: uuid.UUID) -> MarketListing:
    listing = await session.get(MarketListing, listing_id)
    if listing is None or listing.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Listing nicht gefunden", status=404)
    return listing


async def list_listings(
    session: AsyncSession, *, status: str | None = "open"
) -> list[MarketListing]:
    """Listings of the active household (RLS-scoped). Default only ``open``; ``None`` = all."""
    stmt = select(MarketListing).where(MarketListing.deleted_at.is_(None))
    if status is not None:
        stmt = stmt.where(MarketListing.status == status)
    rows = await session.scalars(stmt.order_by(MarketListing.created_at.desc()))
    return list(rows)


async def create_listing(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    seller_id: uuid.UUID,
    task_instance_id: uuid.UUID,
    price: int,
) -> MarketListing:
    """List an own OPEN task instance for sale: reserve ``price`` into escrow (coverage-checked, so
    a broke seller cannot list, KONZEPT §5.10). 403 if not the seller's task, 409 if not open or
    already listed. Emits ``market.listing.created``."""
    instance = await tasks_api.get_instance(session, instance_id=task_instance_id)
    if instance.assigned_to != seller_id:
        raise ProblemException(slug="not_your_task", title="Nicht deine Aufgabe", status=403)
    if instance.status != "open":
        raise ProblemException(slug="invalid_state", title="Aufgabe ist nicht offen", status=409)
    existing = await session.scalar(
        select(MarketListing).where(
            MarketListing.task_instance_id == task_instance_id,
            MarketListing.status == "open",
            MarketListing.deleted_at.is_(None),
        )
    )
    if existing is not None:
        raise ProblemException(slug="already_listed", title="Bereits gelistet", status=409)

    listing = MarketListing(
        household_id=household_id,
        task_instance_id=task_instance_id,
        title=instance.title,
        seller_id=seller_id,
        price=price,
        status="open",
    )
    session.add(listing)
    await session.flush()  # need the id for the escrow account
    # Reserve the price into escrow (coverage-checked -> 422 if the seller can't afford it).
    await economy_api.transfer(
        session,
        household_id=household_id,
        frm=economy_api.member_account(seller_id),
        to=economy_api.escrow_account(listing.id),
        amount=price,
        ref_type="market_escrow",
        ref_id=listing.id,
        created_by=seller_id,
    )
    await emit(session, type="market.listing.created", household_id=household_id, payload={})
    # Auto-accept: if a member's standing rule matches, sell it immediately (fairness tiebreaker).
    await _try_auto_accept(
        session,
        household_id=household_id,
        listing=listing,
        template_id=instance.template_id,
        seller_id=seller_id,
    )
    return listing


async def accept_listing(
    session: AsyncSession, *, household_id: uuid.UUID, buyer_id: uuid.UUID, listing_id: uuid.UUID
) -> MarketListing:
    """Accept an open listing: the task is reassigned to the buyer (KONZEPT §5.10). The escrow stays
    locked until settlement (task completion). 409 if not open; 422 if buying your own listing.
    Emits ``market.listing.sold``."""
    listing = await get_listing(session, listing_id=listing_id)
    if listing.status != "open":
        raise ProblemException(slug="invalid_state", title="Listing nicht offen", status=409)
    if buyer_id == listing.seller_id:
        raise ProblemException(
            slug="invalid_transfer", title="Nicht dein eigenes Listing", status=422
        )
    await tasks_api.reassign_instance(
        session,
        household_id=household_id,
        instance_id=listing.task_instance_id,
        assignee=buyer_id,
    )
    listing.status = "accepted"
    listing.buyer_id = buyer_id
    await emit(session, type="market.listing.sold", household_id=household_id, payload={})
    await session.flush()
    return listing


async def withdraw_listing(
    session: AsyncSession, *, household_id: uuid.UUID, seller_id: uuid.UUID, listing_id: uuid.UUID
) -> MarketListing:
    """Seller withdraws an unsold (open) listing: the escrow is released back (KONZEPT §5.10). 403
    if not the seller, 409 if not open. Emits ``market.changed``."""
    listing = await get_listing(session, listing_id=listing_id)
    if listing.seller_id != seller_id:
        raise ProblemException(slug="not_seller", title="Nicht dein Listing", status=403)
    if listing.status != "open":
        raise ProblemException(slug="invalid_state", title="Listing nicht offen", status=409)
    await economy_api.transfer(
        session,
        household_id=household_id,
        frm=economy_api.escrow_account(listing.id),
        to=economy_api.member_account(seller_id),
        amount=listing.price,
        ref_type="market_withdraw",
        ref_id=listing.id,
        created_by=seller_id,
    )
    listing.status = "withdrawn"
    await emit(session, type="market.changed", household_id=household_id, payload={})
    await session.flush()
    return listing


async def revert_listing(
    session: AsyncSession, *, household_id: uuid.UUID, listing_id: uuid.UUID
) -> MarketListing:
    """Ein angenommenes Listing rückabwickeln: Escrow zurück an den Verkäufer, Aufgabe zurück an
    ihn, Zustand ``reverted``.

    Der Zustand stand seit Migration 0028 im CHECK und im Modell-Docstring („accepted -> reverted,
    Verfall") — ein Codepfad dorthin existierte nie. Der erste echte Anlass ist der Austritt: geht
    der **Käufer**, kann das Listing nie mehr abgerechnet werden. ``settle_listing`` zahlt an
    ``buyer_id``, und das wäre das Konto einer Person, die nicht mehr dazugehört; die Aufgabe hinge
    zugleich an einem Mitglied, das sie nicht mehr erledigen kann. Ohne diesen Weg bliebe das
    Escrow auf einem Konto liegen, das keine Route mehr auflöst.

    **Der Vertrag ist „nicht geliefert".** Ist die Aufgabe bereits ``done``, war der Handel
    erfüllt und gehört abgerechnet, nicht rückabgewickelt — der Verkäufer bekäme sonst die
    erledigte Arbeit **und** seine Punkte zurück. Deshalb 409 statt einer stillen Fehlbuchung;
    ``release_positions_of`` verzweigt vorher.

    **Eine getombstonete Instanz ist dagegen kein Fehler.** Sie kann nicht zurückgegeben werden,
    aber das Escrow muss trotzdem los: es liegt sonst auf ``escrow:<listing_id>``, einem Konto,
    das keine Route mehr auflöst. Vorher warf ``get_instance`` hier 404 und riss den ganzen
    Austritt mit (BUGLOG 2026-08-03).

    Idempotent über den Zustands-Guard (409, wenn nicht ``accepted``). Emittiert
    ``market.trade.reverted`` (KONZEPT §5.10 „Events out"; bis 11-B4 lief hier dasselbe
    inhaltslose ``market.changed`` wie beim Rückzug).
    """
    listing = await get_listing(session, listing_id=listing_id)
    if listing.status != "accepted":
        raise ProblemException(slug="invalid_state", title="Listing nicht angenommen", status=409)
    task_status = await tasks_api.instance_status(session, instance_id=listing.task_instance_id)
    if task_status == "done":
        raise ProblemException(
            slug="task_already_done",
            title="Aufgabe ist erledigt",
            status=409,
            detail="Ein erfüllter Handel wird abgerechnet, nicht rückabgewickelt.",
        )
    await economy_api.transfer(
        session,
        household_id=household_id,
        frm=economy_api.escrow_account(listing.id),
        to=economy_api.member_account(listing.seller_id),
        amount=listing.price,
        ref_type="market_revert",
        ref_id=listing.id,
        created_by=listing.seller_id,
    )
    # Die Aufgabe geht an den Verkäufer zurück — sie war vor dem Handel seine. Existiert sie nicht
    # mehr, entfällt nur dieser Schritt; die Punkte sind der Teil, der nicht liegen bleiben darf.
    if task_status is not None:
        await tasks_api.reassign_instance(
            session,
            household_id=household_id,
            instance_id=listing.task_instance_id,
            assignee=listing.seller_id,
        )
    listing.status = "reverted"
    # KONZEPT §5.10 fuehrt `market.trade.reverted` unter "Events out". Bis 11-B4 emittierte diese
    # Stelle das gleiche inhaltslose `market.changed` wie der Rückzug — zwei Vorgänge unter einem
    # Namen, und der eine, den das Konzept ausdrücklich verlangt, existierte nirgends.
    await emit(session, type="market.trade.reverted", household_id=household_id, payload={})
    await session.flush()
    return listing


async def settle_listing(
    session: AsyncSession, *, household_id: uuid.UUID, listing_id: uuid.UUID
) -> MarketListing:
    """Settle an accepted listing once its task is DONE: the escrow is paid out to the buyer
    (KONZEPT §5.10 / Audit A-04 — the buyer also keeps the task's base points from completing it).
    409 if the listing is not accepted or the task is not done. Idempotent via the status guard.
    Emits ``market.trade.settled``."""
    listing = await get_listing(session, listing_id=listing_id)
    if listing.status != "accepted" or listing.buyer_id is None:
        raise ProblemException(slug="invalid_state", title="Listing nicht angenommen", status=409)
    instance = await tasks_api.get_instance(session, instance_id=listing.task_instance_id)
    if instance.status != "done":
        raise ProblemException(
            slug="task_not_done", title="Aufgabe noch nicht erledigt", status=409
        )
    await economy_api.transfer(
        session,
        household_id=household_id,
        frm=economy_api.escrow_account(listing.id),
        to=economy_api.member_account(listing.buyer_id),
        amount=listing.price,
        ref_type="market_settle",
        ref_id=listing.id,
        created_by=listing.buyer_id,
    )
    listing.status = "settled"
    await emit(session, type="market.trade.settled", household_id=household_id, payload={})
    await session.flush()
    return listing


async def release_positions_of(
    session: AsyncSession, *, household_id: uuid.UUID, member_id: uuid.UUID
) -> dict[str, int]:
    """Alle offenen Handelspositionen einer ausscheidenden Person auflösen (KONZEPT §5.1).

    Zwei Rollen, zwei Richtungen:

    * **Als Verkäufer** eines noch offenen Listings: zurückziehen — das Escrow kommt zurück auf ihr
      Konto und verfällt danach mit dem Rest. Bliebe es liegen, lägen Punkte auf
      ``escrow:<listing_id>``, einem Konto, das nach dem Austritt keine Route mehr auflöst
      (``withdraw_listing`` prüft ``seller_id``).
    * **Als Käufer** eines angenommenen Listings: rückabwickeln — Escrow zurück an den Verkäufer,
      Aufgabe zurück an ihn. ``settle_listing`` zahlte sonst an ein Konto, das nicht mehr besetzt
      ist, und die Aufgabe hinge an jemandem, der sie nicht mehr erledigen kann.
      **Es sei denn, er hat schon geliefert** (Instanz ``done``, aber noch nicht abgerechnet — es
      gibt kein Auto-Settle, der Zustand ist der Normalfall zwischen zwei Klicks). Dann wird
      abgerechnet: wer die Arbeit gemacht hat, hat verdient, und dass er gerade geht, ändert daran
      nichts — sein Saldo verfällt danach ohnehin als eigene Buchung (Schritt 3 in
      ``app/member_exit.py``, und deshalb steht der zuletzt).
      Vor dem 2026-08-03 lief hier ausnahmslos ``revert_listing``; das rief
      ``tasks.api.reassign_instance``, das eine nicht mehr offene Instanz mit 409 ablehnt. Der
      Austritts-Handler starb, fünf Zustellversuche, DLQ — und weil alle drei Schritte **eine**
      Transaktion teilen, lief danach gar nichts mehr. Bei der Haushalts-Auflösung reichte ein
      einziges solches Listing, um die Abwicklung **aller** Mitglieder scheitern zu lassen.

    **Als Verkäufer eines bereits angenommenen** Listings passiert nichts: das Escrow hat ihr Konto
    längst verlassen, der Käufer arbeitet, und die Abrechnung geht an den Käufer — der Handel
    kommt ohne den Verkäufer zu Ende. Das ist kein Versehen, sondern die richtige Antwort.

    Idempotent: ein zweiter Lauf findet keine passenden Zustände mehr.
    """
    open_sales = (
        await session.scalars(
            select(MarketListing).where(
                MarketListing.seller_id == member_id,
                MarketListing.status == "open",
                MarketListing.deleted_at.is_(None),
            )
        )
    ).all()
    for listing in open_sales:
        await withdraw_listing(
            session, household_id=household_id, seller_id=member_id, listing_id=listing.id
        )

    accepted_buys = (
        await session.scalars(
            select(MarketListing).where(
                MarketListing.buyer_id == member_id,
                MarketListing.status == "accepted",
                MarketListing.deleted_at.is_(None),
            )
        )
    ).all()
    for listing in accepted_buys:
        delivered = (
            await tasks_api.instance_status(session, instance_id=listing.task_instance_id)
        ) == "done"
        if delivered:
            await settle_listing(session, household_id=household_id, listing_id=listing.id)
        else:
            await revert_listing(session, household_id=household_id, listing_id=listing.id)

    return {"withdrawn": len(open_sales), "reverted": len(accepted_buys)}


# --- Auto-accept rules + matching (KONZEPT §5.10, Audit A-05) ----------------


async def create_rule(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    template_id: uuid.UUID | None,
    max_price: int,
) -> AutoAcceptRule:
    """Create one of the caller's own auto-accept rules."""
    rule = AutoAcceptRule(
        household_id=household_id,
        member_id=member_id,
        template_id=template_id,
        max_price=max_price,
        active=True,
    )
    session.add(rule)
    await session.flush()
    return rule


async def list_rules(session: AsyncSession, *, member_id: uuid.UUID) -> list[AutoAcceptRule]:
    """The caller's own active rules (RLS-scoped)."""
    rows = await session.scalars(
        select(AutoAcceptRule)
        .where(
            AutoAcceptRule.member_id == member_id,
            AutoAcceptRule.deleted_at.is_(None),
        )
        .order_by(AutoAcceptRule.created_at.desc())
    )
    return list(rows)


async def delete_rule(session: AsyncSession, *, member_id: uuid.UUID, rule_id: uuid.UUID) -> None:
    """Soft-delete one of the caller's own rules (404 if not theirs)."""
    rule = await session.get(AutoAcceptRule, rule_id)
    if rule is None or rule.deleted_at is not None or rule.member_id != member_id:
        raise ProblemException(slug="not_found", title="Regel nicht gefunden", status=404)
    rule.deleted_at = datetime.now(UTC)


async def _try_auto_accept(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    listing: MarketListing,
    template_id: uuid.UUID | None,
    seller_id: uuid.UUID,
) -> None:
    """If any member (other than the seller) has a matching auto-accept rule, accept the listing for
    them at once. Among several matching members, the fairness account decides — the one who has
    carried the least is chosen (Audit A-05). Deterministic tiebreak by user_id."""
    stmt = select(AutoAcceptRule).where(
        AutoAcceptRule.deleted_at.is_(None),
        AutoAcceptRule.active.is_(True),
        AutoAcceptRule.max_price >= listing.price,
        AutoAcceptRule.member_id != seller_id,
    )
    if template_id is None:
        stmt = stmt.where(AutoAcceptRule.template_id.is_(None))
    else:
        stmt = stmt.where(
            (AutoAcceptRule.template_id == template_id) | (AutoAcceptRule.template_id.is_(None))
        )
    candidates = {rule.member_id for rule in await session.scalars(stmt)}
    if not candidates:
        return
    loads = await economy_api.fairness_load(session)
    winner = min(candidates, key=lambda m: (loads.get(m, 0), m))
    await accept_listing(session, household_id=household_id, buyer_id=winner, listing_id=listing.id)
