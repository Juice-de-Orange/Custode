"""``make seed-demo`` — deterministic demo household + admin user (ARCHITECTURE §12).

Creates one **verified admin account** you can log straight into, plus a lived-in
household around it: three further members (two adults joined via invite, one child),
a handful of recipes, this week's meal plan, a shopping list, household tasks in
different states (with the points the completed ones earned), notes, a guide and
calendar events — enough for screenshots and a first click-through. All names are
invented; ``--lang en`` seeds the same household in English (the public demo uses it).
Idempotent: a re-run finds the existing admin by e-mail and does nothing. The fixed, known
password must never exist in a real deployment, so the script refuses to run unless
``CUSTODE_ENV=dev`` — or in demo mode, where the password is public by design (docs/demo.md).

User insert path mirrors ``accounts.service.register_user`` (same Argon2id hasher, same
self-scoped ``users`` WITH CHECK), but skips the HIBP pwned-check network call so the
seed stays offline + deterministic. Login itself enforces no password policy, so the
accounts authenticate exactly like normally-registered ones. Everything else goes
through the modules' own service functions — memberships via invite + accept, points
via task completion — so no invariant (ledger, RLS scope, outbox) is bypassed.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.null import NullCaldav
from app.kernel.auth.passwords import hash_password
from app.kernel.db.ids import new_uuid7
from app.kernel.sync.schemas import SyncOp
from app.kernel.tenancy.session import maint_session, scoped_session
from app.modules.accounts.models import User
from app.modules.accounts.service import (
    accept_invite,
    create_child,
    create_household_with_admin,
    create_invite,
)
from app.modules.calendar.schemas import EventCreate
from app.modules.calendar.service import create_event
from app.modules.guides.schemas import GuideCreate
from app.modules.guides.service import create_guide
from app.modules.mealplanner.schemas import SlotSet
from app.modules.mealplanner.service import set_slot
from app.modules.notes.schemas import NoteCreate
from app.modules.notes.service import create_note
from app.modules.recipes.schemas import IngredientLine, RecipeCreate
from app.modules.recipes.service import create_recipe
from app.modules.shopping.service import apply_shopping_batch, ensure_default_list
from app.modules.tasks.schemas import Rotation, TaskInstanceCreate, TaskTemplateCreate
from app.modules.tasks.service import (
    complete_instance,
    create_instance,
    create_room,
    create_template,
)
from app.settings import get_settings

# Demo credentials — deliberately known. Only ever created with CUSTODE_ENV=dev or in demo mode,
# where the sign-in page shows them (docs/demo.md).
DEMO_EMAIL = "admin@custode.local"
DEMO_PASSWORD = "custode-admin-demo"  # noqa: S105 - dev seed, not a real secret
DEMO_DISPLAY_NAME = "Mira"

# Further members (invented names). Adults share the admin's password so every account is
# loginable for screenshots; the child logs in with username + PIN via the child flow.
DEMO_ADULTS: tuple[tuple[str, str], ...] = (
    ("Jonas", "jonas@custode.local"),
    ("Lea", "lea@custode.local"),
)
DEMO_CHILD_NAME = "Noah"
DEMO_CHILD_USERNAME = "noah"
DEMO_CHILD_PIN = "1234"

# Deterministic ids for the shopping Sync-Batch ops (idempotent per household, like
# ``ensure_default_list``).
_SEED_NS = uuid.uuid5(uuid.NAMESPACE_URL, "custode:seed-demo")
_TZ = ZoneInfo("Europe/Berlin")

# --- Content ------------------------------------------------------------------
#
# One set per language, identical in shape and counts: German is what ``make seed-demo`` has always
# seeded; English is what the public demo shows (``demo-reset --lang en``). Tests and the demo
# reset compare counts, so a new item goes into BOTH sets.


@dataclass(frozen=True)
class _Content:
    household: str
    recipes: tuple[RecipeCreate, ...]
    # Dinners on Saturday and Sunday (free text, the first one cooked by Lea).
    free_dinners: tuple[str, str]
    # (label, qty, unit, category, checked) — a mid-week list with a few items already ticked.
    shopping: tuple[tuple[str, str | None, str | None, str, bool], ...]
    # (key, name, icon, decay days)
    rooms: tuple[tuple[str, str, str, int], ...]
    # (key, title, points, duration, room key or None, rotation)
    templates: tuple[tuple[str, str, int, int, str | None, Rotation], ...]
    adhoc_task: str
    # (title, body, pinned) — the first by the admin, the second by Jonas.
    notes: tuple[tuple[str, str, bool], tuple[str, str, bool]]
    guide: GuideCreate
    # (title, location) for next Tuesday's evening event; title of Thursday's weekly training.
    evening_event: tuple[str, str]
    weekly_event: str


_DE = _Content(
    household="Demo-Haushalt",
    recipes=(
        RecipeCreate(
            title="Linsen-Bolognese",
            servings=4,
            prep_minutes=15,
            cook_minutes=35,
            tags=["vegetarisch", "familie"],
            steps_md=(
                "1. Zwiebel und Karotte fein würfeln, in Olivenöl anschwitzen.\n"
                "2. Linsen, Tomaten und Brühe zugeben, 30 min köcheln.\n"
                "3. Mit Salz, Pfeffer und Oregano abschmecken, zu Nudeln servieren."
            ),
            ingredients=[
                IngredientLine(raw_text="250 g rote Linsen", qty="250", unit="g"),
                IngredientLine(raw_text="1 Zwiebel", qty="1"),
                IngredientLine(raw_text="2 Karotten", qty="2"),
                IngredientLine(raw_text="800 g gehackte Tomaten", qty="800", unit="g"),
                IngredientLine(raw_text="500 g Spaghetti", qty="500", unit="g"),
            ],
        ),
        RecipeCreate(
            title="Ofengemüse mit Halloumi",
            servings=3,
            prep_minutes=15,
            cook_minutes=30,
            tags=["vegetarisch", "schnell"],
            steps_md=(
                "1. Gemüse in grobe Stücke schneiden, mit Öl und Gewürzen mischen.\n"
                "2. 25 min bei 200 °C backen, Halloumi die letzten 8 min dazulegen."
            ),
            ingredients=[
                IngredientLine(raw_text="1 Zucchini", qty="1"),
                IngredientLine(raw_text="2 Paprika", qty="2"),
                IngredientLine(raw_text="500 g Kartoffeln", qty="500", unit="g"),
                IngredientLine(raw_text="250 g Halloumi", qty="250", unit="g"),
            ],
        ),
        RecipeCreate(
            title="Pfannkuchen",
            servings=4,
            prep_minutes=10,
            cook_minutes=20,
            tags=["kinder", "süß"],
            steps_md=(
                "1. Mehl, Milch, Eier und eine Prise Salz glatt rühren, 10 min ruhen lassen.\n"
                "2. Portionsweise in der Pfanne goldbraun backen."
            ),
            ingredients=[
                IngredientLine(raw_text="250 g Mehl", qty="250", unit="g"),
                IngredientLine(raw_text="500 ml Milch", qty="500", unit="ml"),
                IngredientLine(raw_text="3 Eier", qty="3"),
            ],
        ),
        RecipeCreate(
            title="Kürbissuppe",
            servings=4,
            prep_minutes=15,
            cook_minutes=25,
            tags=["herbst", "vegetarisch"],
            steps_md=(
                "1. Kürbis und Zwiebel würfeln, mit Ingwer anschwitzen.\n"
                "2. Mit Brühe aufgießen, weich kochen, pürieren.\n"
                "3. Kokosmilch einrühren, mit Salz und Chili abschmecken."
            ),
            ingredients=[
                IngredientLine(raw_text="1 Hokkaido-Kürbis", qty="1"),
                IngredientLine(raw_text="1 Zwiebel", qty="1"),
                IngredientLine(raw_text="800 ml Gemüsebrühe", qty="800", unit="ml"),
                IngredientLine(raw_text="200 ml Kokosmilch", qty="200", unit="ml"),
            ],
        ),
        RecipeCreate(
            title="Hähnchen-Curry",
            servings=4,
            prep_minutes=20,
            cook_minutes=30,
            tags=["familie"],
            steps_md=(
                "1. Hähnchen anbraten, herausnehmen.\n"
                "2. Zwiebel, Knoblauch und Currypaste anschwitzen, Kokosmilch zugeben.\n"
                "3. Hähnchen und Gemüse 15 min köcheln, mit Reis servieren."
            ),
            ingredients=[
                IngredientLine(raw_text="500 g Hähnchenbrust", qty="500", unit="g"),
                IngredientLine(raw_text="400 ml Kokosmilch", qty="400", unit="ml"),
                IngredientLine(raw_text="2 EL Currypaste", qty="2", unit="EL"),
                IngredientLine(raw_text="300 g Basmatireis", qty="300", unit="g"),
            ],
        ),
    ),
    free_dinners=("Reste", "Pizza bestellen"),
    shopping=(
        ("Milch", "2", "l", "Kühlregal", True),
        ("Butter", "1", None, "Kühlregal", True),
        ("Eier", "10", None, "Kühlregal", False),
        ("Rote Linsen", "500", "g", "Trockenwaren", False),
        ("Spaghetti", "1", "kg", "Trockenwaren", False),
        ("Hokkaido-Kürbis", "1", None, "Obst & Gemüse", False),
        ("Zucchini", "2", None, "Obst & Gemüse", False),
        ("Paprika", "3", None, "Obst & Gemüse", False),
        ("Halloumi", "1", None, "Kühlregal", False),
        ("Spülmaschinentabs", "1", None, "Haushalt", False),
    ),
    rooms=(("kitchen", "Küche", "🍳", 2), ("bath", "Bad", "🛁", 7)),
    templates=(
        ("kitchen", "Küche aufräumen", 10, 20, "kitchen", "fair"),
        ("bath", "Bad putzen", 25, 45, "bath", "fair"),
        ("trash", "Müll rausbringen", 5, 5, None, "open"),
        ("vacuum", "Staubsaugen", 15, 30, None, "fair"),
    ),
    adhoc_task="Fahrrad zur Werkstatt bringen",
    notes=(
        (
            "Urlaubsplanung Sommer",
            "- Ferienwohnung anfragen\n- Zugtickets vergleichen\n- Nachbarn wegen Blumen fragen",
            True,
        ),
        ("Geschenkideen", "Noah: Kletterkurs · Lea: Kochbuch · Oma: Fotobuch", False),
    ),
    guide=GuideCreate(
        title="Waschmaschine entkalken",
        category="Haushalt",
        tags=["waschküche", "monatlich"],
        body_md=(
            "1. Trommel leeren, Waschmittelfach ausspülen.\n"
            "2. Einen Beutel Entkalker ins Fach geben.\n"
            "3. Kochwäsche-Programm ohne Wäsche laufen lassen.\n\n"
            "Flusensieb (unten rechts) dabei gleich mit reinigen."
        ),
    ),
    evening_event=("Elternabend", "Grundschule, Raum 12"),
    weekly_event="Fußballtraining Noah",
)

_EN = _Content(
    household="Demo household",
    recipes=(
        RecipeCreate(
            title="Lentil bolognese",
            servings=4,
            prep_minutes=15,
            cook_minutes=35,
            tags=["vegetarian", "family"],
            steps_md=(
                "1. Finely dice the onion and carrots, soften them in olive oil.\n"
                "2. Add lentils, tomatoes and stock, simmer for 30 min.\n"
                "3. Season with salt, pepper and oregano, serve with pasta."
            ),
            ingredients=[
                IngredientLine(raw_text="250 g red lentils", qty="250", unit="g"),
                IngredientLine(raw_text="1 onion", qty="1"),
                IngredientLine(raw_text="2 carrots", qty="2"),
                IngredientLine(raw_text="800 g chopped tomatoes", qty="800", unit="g"),
                IngredientLine(raw_text="500 g spaghetti", qty="500", unit="g"),
            ],
        ),
        RecipeCreate(
            title="Roast vegetables with halloumi",
            servings=3,
            prep_minutes=15,
            cook_minutes=30,
            tags=["vegetarian", "quick"],
            steps_md=(
                "1. Cut the vegetables into chunks, toss with oil and spices.\n"
                "2. Roast for 25 min at 200 °C, add the halloumi for the last 8 min."
            ),
            ingredients=[
                IngredientLine(raw_text="1 courgette", qty="1"),
                IngredientLine(raw_text="2 peppers", qty="2"),
                IngredientLine(raw_text="500 g potatoes", qty="500", unit="g"),
                IngredientLine(raw_text="250 g halloumi", qty="250", unit="g"),
            ],
        ),
        RecipeCreate(
            title="Pancakes",
            servings=4,
            prep_minutes=10,
            cook_minutes=20,
            tags=["kids", "sweet"],
            steps_md=(
                "1. Whisk flour, milk, eggs and a pinch of salt until smooth, rest for 10 min.\n"
                "2. Fry in batches until golden."
            ),
            ingredients=[
                IngredientLine(raw_text="250 g flour", qty="250", unit="g"),
                IngredientLine(raw_text="500 ml milk", qty="500", unit="ml"),
                IngredientLine(raw_text="3 eggs", qty="3"),
            ],
        ),
        RecipeCreate(
            title="Pumpkin soup",
            servings=4,
            prep_minutes=15,
            cook_minutes=25,
            tags=["autumn", "vegetarian"],
            steps_md=(
                "1. Dice pumpkin and onion, soften them with ginger.\n"
                "2. Add the stock, cook until soft, blend.\n"
                "3. Stir in coconut milk, season with salt and chilli."
            ),
            ingredients=[
                IngredientLine(raw_text="1 red kuri squash", qty="1"),
                IngredientLine(raw_text="1 onion", qty="1"),
                IngredientLine(raw_text="800 ml vegetable stock", qty="800", unit="ml"),
                IngredientLine(raw_text="200 ml coconut milk", qty="200", unit="ml"),
            ],
        ),
        RecipeCreate(
            title="Chicken curry",
            servings=4,
            prep_minutes=20,
            cook_minutes=30,
            tags=["family"],
            steps_md=(
                "1. Brown the chicken, set it aside.\n"
                "2. Soften onion, garlic and curry paste, add the coconut milk.\n"
                "3. Simmer chicken and vegetables for 15 min, serve with rice."
            ),
            ingredients=[
                IngredientLine(raw_text="500 g chicken breast", qty="500", unit="g"),
                IngredientLine(raw_text="400 ml coconut milk", qty="400", unit="ml"),
                IngredientLine(raw_text="2 tbsp curry paste", qty="2", unit="tbsp"),
                IngredientLine(raw_text="300 g basmati rice", qty="300", unit="g"),
            ],
        ),
    ),
    free_dinners=("Leftovers", "Order pizza"),
    shopping=(
        ("Milk", "2", "l", "Dairy", True),
        ("Butter", "1", None, "Dairy", True),
        ("Eggs", "10", None, "Dairy", False),
        ("Red lentils", "500", "g", "Pantry", False),
        ("Spaghetti", "1", "kg", "Pantry", False),
        ("Red kuri squash", "1", None, "Fruit & veg", False),
        ("Courgettes", "2", None, "Fruit & veg", False),
        ("Peppers", "3", None, "Fruit & veg", False),
        ("Halloumi", "1", None, "Dairy", False),
        ("Dishwasher tabs", "1", None, "Household", False),
    ),
    rooms=(("kitchen", "Kitchen", "🍳", 2), ("bath", "Bathroom", "🛁", 7)),
    templates=(
        ("kitchen", "Tidy the kitchen", 10, 20, "kitchen", "fair"),
        ("bath", "Clean the bathroom", 25, 45, "bath", "fair"),
        ("trash", "Take out the bins", 5, 5, None, "open"),
        ("vacuum", "Vacuum", 15, 30, None, "fair"),
    ),
    adhoc_task="Take the bike to the repair shop",
    notes=(
        (
            "Summer holiday plans",
            "- Ask about the holiday flat\n- Compare train tickets\n- Ask the neighbours "
            "to water the plants",
            True,
        ),
        ("Gift ideas", "Noah: climbing course · Lea: cookbook · Grandma: photo book", False),
    ),
    guide=GuideCreate(
        title="Descale the washing machine",
        category="Household",
        tags=["laundry", "monthly"],
        body_md=(
            "1. Empty the drum, rinse the detergent drawer.\n"
            "2. Put one sachet of descaler into the drawer.\n"
            "3. Run the hot wash programme without laundry.\n\n"
            "Clean the lint filter (bottom right) while you are at it."
        ),
    ),
    evening_event=("Parents' evening", "Primary school, room 12"),
    weekly_event="Noah's football practice",
)

CONTENT: dict[str, _Content] = {"de": _DE, "en": _EN}


# --- Helpers ------------------------------------------------------------------


async def _insert_user(*, email: str, display_name: str, locale: str) -> uuid.UUID:
    """Self-scoped user insert (the register_user bootstrap path), e-mail pre-verified so the
    account is immediately usable without the mailpit confirmation flow."""
    user_id = new_uuid7()
    async with scoped_session(household_id=user_id, user_id=user_id) as session:
        session.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password(DEMO_PASSWORD),
                display_name=display_name,
                email_verified_at=datetime.now(UTC),
                locale=locale,
            )
        )
    return user_id


async def _join_via_invite(
    *, household_id: uuid.UUID, admin_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Membership through the real door: the admin issues a single-use invite, the user accepts."""
    async with scoped_session(household_id=household_id, user_id=admin_id) as session:
        code = await create_invite(
            session,
            household_id=household_id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    await accept_invite(user_id=user_id, code=code)


def _local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=_TZ)


async def _seed_content(
    session: AsyncSession,
    *,
    content: _Content,
    household_id: uuid.UUID,
    admin_id: uuid.UUID,
    adults: dict[str, uuid.UUID],
    child_id: uuid.UUID,
) -> None:
    """Fill the household through the modules' service functions (one transaction)."""
    today = datetime.now(_TZ).date()
    week_start = today - timedelta(days=today.weekday())
    jonas, lea = adults["Jonas"], adults["Lea"]

    # Recipes + this week's dinners (five recipes, two free-text evenings).
    recipes = [
        await create_recipe(session, household_id=household_id, data=data)
        for data in content.recipes
    ]
    cooks = [admin_id, jonas, lea, admin_id, jonas]
    for day, (recipe, cook) in enumerate(zip(recipes, cooks, strict=True)):
        await set_slot(
            session,
            household_id=household_id,
            week_start=week_start,
            data=SlotSet(day_of_week=day, slot="dinner", recipe_id=recipe.id, cook_id=cook),
        )
    await set_slot(
        session,
        household_id=household_id,
        week_start=week_start,
        data=SlotSet(day_of_week=5, slot="dinner", free_text=content.free_dinners[0], cook_id=lea),
    )
    await set_slot(
        session,
        household_id=household_id,
        week_start=week_start,
        data=SlotSet(day_of_week=6, slot="dinner", free_text=content.free_dinners[1]),
    )

    # Shopping list via the Sync-Batch (the only write path for offline entities, ADR-0032).
    list_id = await ensure_default_list(session, household_id=household_id, user_id=admin_id)
    ops = [
        SyncOp(
            client_op_id=uuid.uuid5(_SEED_NS, f"op:{household_id}:{i}"),
            entity="shopping_item",
            id=uuid.uuid5(_SEED_NS, f"item:{household_id}:{i}"),
            op="upsert",
            fields={
                "list_id": str(list_id),
                "label": label,
                "qty": qty,
                "unit": unit,
                "category": category,
                "checked": checked,
            },
        )
        for i, (label, qty, unit, category, checked) in enumerate(content.shopping)
    ]
    await apply_shopping_batch(session, household_id=household_id, user_id=admin_id, ops=ops)

    # Rooms + templates + instances in different states; completions book the points ledger.
    rooms = {
        key: await create_room(
            session, household_id=household_id, name=name, icon=icon, decay_days=decay
        )
        for key, name, icon, decay in content.rooms
    }
    templates = {}
    for key, title, points, duration, room_key, rotation in content.templates:
        templates[key] = await create_template(
            session,
            household_id=household_id,
            data=TaskTemplateCreate(
                title=title,
                points=points,
                duration_est_minutes=duration,
                room_id=rooms[room_key].id if room_key else None,
                rotation=rotation,
            ),
        )
    now = datetime.now(UTC)
    # (template key or None, ad-hoc title, assignee, due offset in days, completed by)
    plan: tuple[tuple[str | None, str | None, uuid.UUID | None, int, uuid.UUID | None], ...] = (
        ("kitchen", None, jonas, -2, jonas),  # done, on time
        ("bath", None, lea, -3, lea),  # done, overdue -> decayed points
        ("trash", None, child_id, -1, child_id),  # done by the child
        ("vacuum", None, admin_id, 0, None),  # open, due today
        ("kitchen", None, None, 1, None),  # open, unassigned
        ("trash", None, jonas, -1, None),  # open, overdue
        (None, content.adhoc_task, lea, 4, None),  # ad-hoc, open
    )
    for template_key, adhoc_title, assignee, offset, doer in plan:
        instance = await create_instance(
            session,
            household_id=household_id,
            data=TaskInstanceCreate(
                template_id=templates[template_key].id if template_key else None,
                title=adhoc_title,
                assigned_to=assignee,
                due_at=now + timedelta(days=offset),
            ),
        )
        if doer is not None:
            # ``version`` is a server default (ETag) — load it for the If-Match guard.
            await session.refresh(instance, attribute_names=["version"])
            await complete_instance(
                session,
                household_id=household_id,
                instance_id=instance.id,
                user_id=doer,
                expected_version=instance.version,
            )

    # Notes, a guide, calendar events.
    for author, (title, body, pinned) in zip((admin_id, jonas), content.notes, strict=True):
        await create_note(
            session,
            household_id=household_id,
            author_id=author,
            data=NoteCreate(title=title, body_md=body, pinned=pinned),
        )
    await create_guide(
        session,
        household_id=household_id,
        author_id=admin_id,
        data=content.guide.model_copy(update={"contact_id": jonas}),
    )
    caldav = NullCaldav()  # unused without a subscription_id; keeps the port contract
    next_tuesday = week_start + timedelta(days=8)
    next_thursday = week_start + timedelta(days=10)
    evening_title, evening_location = content.evening_event
    await create_event(
        session,
        household_id=household_id,
        owner_id=admin_id,
        caldav=caldav,
        data=EventCreate(
            title=evening_title,
            location=evening_location,
            starts_at=_local(next_tuesday, 19, 0),
            ends_at=_local(next_tuesday, 20, 30),
            tzid=_TZ.key,
        ),
    )
    await create_event(
        session,
        household_id=household_id,
        owner_id=jonas,
        caldav=caldav,
        data=EventCreate(
            title=content.weekly_event,
            starts_at=_local(next_thursday, 17, 0),
            ends_at=_local(next_thursday, 18, 30),
            rrule="FREQ=WEEKLY;BYDAY=TH",
            tzid=_TZ.key,
        ),
    )


async def seed_demo_admin(lang: str = "de") -> uuid.UUID | None:
    """Idempotently create the demo admin + lived-in household in ``lang`` (``de``/``en``).
    Returns the new household's id, or ``None`` when the admin already exists."""
    settings = get_settings()
    if settings.env != "dev" and not settings.demo_mode:
        raise SystemExit(
            "seed-demo creates an admin with a fixed, known password; it runs only with "
            "CUSTODE_ENV=dev or in demo mode (CUSTODE_DEMO_MODE=on, docs/demo.md)."
        )
    content = CONTENT[lang]

    # Cross-user existence check (by e-mail) -> maint role, like the login bootstrap.
    async with maint_session() as session:
        existing = await session.scalar(select(User.id).where(User.email == DEMO_EMAIL))
    if existing is not None:
        print(f"seed-demo: {DEMO_EMAIL} already exists ({existing}) — nothing to do.")
        return None

    admin_id = await _insert_user(email=DEMO_EMAIL, display_name=DEMO_DISPLAY_NAME, locale=lang)
    household_id = await create_household_with_admin(
        creator_user_id=admin_id, name=content.household
    )

    adults: dict[str, uuid.UUID] = {}
    for name, email in DEMO_ADULTS:
        adults[name] = await _insert_user(email=email, display_name=name, locale=lang)
        await _join_via_invite(household_id=household_id, admin_id=admin_id, user_id=adults[name])
    child_id = await create_child(
        household_id=household_id,
        granted_by=admin_id,
        display_name=DEMO_CHILD_NAME,
        username=DEMO_CHILD_USERNAME,
        pin=DEMO_CHILD_PIN,
    )

    async with scoped_session(household_id=household_id, user_id=admin_id) as session:
        await _seed_content(
            session,
            content=content,
            household_id=household_id,
            admin_id=admin_id,
            adults=adults,
            child_id=child_id,
        )

    print(f"seed-demo: created the demo household ({lang})")
    print(f"  E-mail:     {DEMO_EMAIL}")
    print(f"  Password:   {DEMO_PASSWORD}")
    print(f"  Household:  {content.household} ({household_id})")
    print(f"  User id:    {admin_id}")
    print(f"  Members:    {', '.join(adults)} (same password), child {DEMO_CHILD_NAME}")
    print(f"  Child login: {DEMO_CHILD_USERNAME} / PIN {DEMO_CHILD_PIN}")
    return household_id


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="seed-demo", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--lang",
        choices=sorted(CONTENT),
        default="de",
        help="language of the demo content (default: de)",
    )
    args = parser.parse_args(argv)
    asyncio.run(seed_demo_admin(args.lang))


if __name__ == "__main__":
    main()
