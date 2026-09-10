from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.db import get_session
from app.models.enums import EventStatus
from app.schemas import BoardOut, DemandIn
from app.services import demands as demands_service
from app.services import eventcards

router = APIRouter(prefix="/api", tags=["board"])


@router.get("/board", response_model=BoardOut)
async def board(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> BoardOut:
    """Афиша целиком: сверху встречи, под ними спрос.

    Один запрос на всю вкладку — два яруса одного списка, а не две страницы.
    """
    events = await eventcards.visible_events(
        session, user, (EventStatus.VOTING, EventStatus.SCHEDULED)
    )
    return BoardOut(
        events=[await eventcards.event_out(session, event, user) for event in events],
        demands=await eventcards.demand_cards(session, user),
    )


@router.get("/board/past", response_model=BoardOut)
async def past(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    attended: bool | None = None,
) -> BoardOut:
    """Прошедшие встречи. attended=true — только те, где человек отметился,
    false — только те, что прошли мимо него."""
    events = await eventcards.visible_events(
        session, user, (EventStatus.HELD, EventStatus.CANCELLED)
    )
    cards = [
        await eventcards.event_out(session, event, user, with_slots=False) for event in events
    ]
    if attended is not None:
        cards = [card for card in cards if card.attended is attended]
    return BoardOut(events=cards, demands=[])


@router.post("/books/{book_id}/demand", status_code=204)
async def add_demand(
    book_id: int,
    body: DemandIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Отметка «хочу встречу» с уточнением форматов."""
    await demands_service.set_demand(session, user, book_id, body.event_type_ids, body.comment)


@router.delete("/books/{book_id}/demand", status_code=204)
async def drop_demand(
    book_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await demands_service.revoke(session, user.id, book_id)
