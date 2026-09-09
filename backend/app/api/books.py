from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.db import get_session
from app.models import Book, BookRequest, ReadingEntry
from app.models.enums import BookStatus, ReadingStatus, RequestStatus
from app.schemas import (
    BookCard,
    BookRequestIn,
    BookRequestOut,
    BookSearchOut,
    DiaryIn,
    ExternalRef,
)
from app.services import cards
from app.services.books import merge
from app.services.books.normalize import dedup_key

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("", response_model=BookSearchOut)
async def search_books(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = Query(default="", max_length=200),
    external: bool = True,
    limit: int = Query(default=20, ge=1, le=40),
) -> BookSearchOut:
    """Поиск. Пустой запрос отдаёт каталог клуба — с него начинается вкладка.

    Внешние источники подключаются, только когда что-то ищут: показывать
    человеку миллион чужих книг вместо своей полки бессмысленно.
    """
    if not q.strip():
        books = list(
            (
                await session.execute(
                    sa.select(Book)
                    .where(Book.status == BookStatus.ACTIVE)
                    .order_by(Book.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        briefs = [cards.brief_from_book(book) for book in books]
        return BookSearchOut(items=await cards.decorate(session, user.id, briefs))

    candidates, degraded = await merge.search(session, q, limit=limit, external=external)
    briefs = [cards.brief_from_candidate(c) for c in candidates[:limit]]
    return BookSearchOut(
        items=await cards.decorate(session, user.id, briefs), sources_degraded=degraded
    )


@router.post("/ensure", response_model=BookCard)
async def ensure_book(
    body: ExternalRef,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BookCard:
    """Заводит в каталоге книгу, выбранную во внешней выдаче.

    Вызывается в момент первого действия с ней — отметки о чтении или спроса.
    До этого держать в базе чужой каталог незачем.
    """
    candidate = await merge.fetch_external(body.source, body.external_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Источник больше не знает эту книгу")
    book = await merge.ensure_book(session, candidate, added_by=user.id)
    await session.commit()
    await session.refresh(book)
    return await cards.card(session, user.id, book)


@router.get("/{book_id}", response_model=BookCard)
async def get_book(
    book_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BookCard:
    book = await session.get(Book, book_id)
    if book is None or book.status is BookStatus.HIDDEN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Книга не найдена")
    return await cards.card(session, user.id, book)


@router.put("/{book_id}/diary", response_model=BookCard)
async def save_diary(
    book_id: int,
    body: DiaryIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BookCard:
    """Запись дневника. Одна строка на пару «человек — книга»: повторный вызов
    правит её, а не заводит вторую."""
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Книга не найдена")

    entry = (
        await session.execute(
            sa.select(ReadingEntry).where(
                ReadingEntry.user_id == user.id, ReadingEntry.book_id == book_id
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        entry = ReadingEntry(user_id=user.id, book_id=book_id, status=body.status)
        session.add(entry)

    entry.status = body.status
    entry.started_on = body.started_on
    entry.finished_on = body.finished_on
    entry.score = body.score
    entry.review = (body.review or "").strip() or None
    entry.is_private = body.is_private
    entry.updated_at = sa.func.now()

    await session.commit()
    await session.refresh(book)
    return await cards.card(session, user.id, book)


@router.delete("/{book_id}/diary", response_model=BookCard)
async def drop_diary(
    book_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BookCard:
    await session.execute(
        sa.delete(ReadingEntry).where(
            ReadingEntry.user_id == user.id, ReadingEntry.book_id == book_id
        )
    )
    await session.commit()
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Книга не найдена")
    return await cards.card(session, user.id, book)


@router.post("/{book_id}/read", response_model=BookCard)
async def mark_read(
    book_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BookCard:
    """Кнопка «Читал» из списка: один тап, без формы.

    Повторный тап снимает отметку — иначе промах пришлось бы исправлять
    через карточку, а список для того и существует, чтобы туда не ходить.
    """
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Книга не найдена")

    entry = (
        await session.execute(
            sa.select(ReadingEntry).where(
                ReadingEntry.user_id == user.id, ReadingEntry.book_id == book_id
            )
        )
    ).scalar_one_or_none()

    if entry is None:
        session.add(
            ReadingEntry(user_id=user.id, book_id=book_id, status=ReadingStatus.FINISHED)
        )
    elif entry.status is ReadingStatus.FINISHED and entry.score is None and not entry.review:
        # Отметка была пустой — снимаем её целиком. Если человек успел
        # поставить оценку или написать отзыв, молча стирать их нельзя.
        await session.delete(entry)
    else:
        entry.status = ReadingStatus.FINISHED

    await session.commit()
    await session.refresh(book)
    return await cards.card(session, user.id, book)


@router.post("/requests", response_model=BookRequestOut)
async def request_book(
    body: BookRequestIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BookRequestOut:
    """Завести книгу руками, когда источники её не знают.

    Заявка идёт на модерацию: каталог общий, и мусор в нём стоит дороже,
    чем ожидание.
    """
    duplicate = (
        await session.execute(
            sa.select(Book).where(Book.dedup_key == dedup_key(body.title, body.authors))
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Такая книга уже есть в каталоге: {duplicate.title}"
        )

    request = BookRequest(
        user_id=user.id,
        title=body.title.strip(),
        authors=[a.strip() for a in body.authors if a.strip()],
        year=body.year,
        isbn13=body.isbn13,
        cover_url=body.cover_url,
        description=body.description,
        comment=body.comment,
        status=RequestStatus.PENDING,
    )
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return BookRequestOut(
        id=request.id,
        title=request.title,
        authors=list(request.authors or []),
        year=request.year,
        status=request.status,
        book_id=request.book_id,
        created_at=request.created_at,
        user_id=request.user_id,
        user_name=user.display_name,
    )
