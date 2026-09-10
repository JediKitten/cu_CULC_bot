from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    ApplicationStatus,
    ClubExperience,
    EventStatus,
    MemberKind,
    ParticipationState,
    ReadingPace,
    ReadingStatus,
    RequestStatus,
    RoomStatus,
    UserRole,
)

# --- Вход и профиль ----------------------------------------------------------


class TelegramAuthIn(BaseModel):
    init_data: str


class UserOut(BaseModel):
    id: int
    display_name: str
    role: UserRole
    photo_url: str | None = None
    tg_username: str | None = None
    # Заполнена ли анкета: без неё приложение показывает онбординг, а не клуб.
    onboarded: bool = False


class AuthOut(BaseModel):
    token: str
    user: UserOut


class EventTypeOut(BaseModel):
    id: int
    slug: str
    title: str
    description: str | None = None
    requires_reading: bool = True


class ProfileOut(BaseModel):
    member_kind: MemberKind
    member_kind_title: str = ""
    full_name: str
    university_email: str | None = None
    reading_pace: ReadingPace | None = None
    club_experience: ClubExperience | None = None
    genres: list[str] = []
    event_type_ids: list[int] = []
    about: str | None = None
    completed_at: datetime | None = None
    # Необязательная часть анкеты пройдена (пусть и с пропусками).
    preferences_at: datetime | None = None
    # Показывать ли плашку «допройти анкету».
    needs_preferences: bool = False
    email_required: bool = False
    favourites: list["BookBrief"] = []


class IdentityIn(BaseModel):
    """Обязательная часть: её же правят из профиля."""

    member_kind: MemberKind
    full_name: str = Field(min_length=1, max_length=128)
    university_email: str | None = Field(default=None, max_length=255)


class PreferencesIn(BaseModel):
    """Необязательная часть. Любой вопрос можно пропустить — пустое значение
    здесь полноценный ответ, а не отсутствие данных."""

    reading_pace: ReadingPace | None = None
    club_experience: ClubExperience | None = None
    genres: list[str] = []
    event_type_ids: list[int] = []
    about: str | None = Field(default=None, max_length=2000)


class DismissIn(BaseModel):
    # true — больше не напоминать вовсе; false — спрятать до следующего /start.
    forever: bool = False


class KindOut(BaseModel):
    key: MemberKind
    title: str
    email_required: bool = False


class ReferenceOut(BaseModel):
    """Всё, что нужно нарисовать анкету, одним запросом."""

    genres: list[str]
    event_types: list[EventTypeOut]
    kinds: list[KindOut] = []
    # Домен, который принимает почта. Показываем подсказкой в форме, чтобы
    # человек узнавал об ограничении до отправки, а не из ошибки.
    email_domains: list[str] = []


# --- Книги -------------------------------------------------------------------


class BookBrief(BaseModel):
    """Строка списка. id пуст у книги, которой ещё нет в каталоге, — такая
    приходит из внешнего источника и заводится при первом действии с ней."""

    id: int | None = None
    title: str
    authors: list[str] = []
    year: int | None = None
    cover_url: str | None = None
    source: str | None = None
    external_id: str | None = None
    # Состояние текущего пользователя — чтобы список рисовался без второго запроса.
    world_rating: float | None = None
    world_ratings_count: int | None = None
    club_score: float | None = None
    club_ratings: int = 0
    reading_status: ReadingStatus | None = None
    my_score: int | None = None
    liked: bool = False
    favourite_position: int | None = None
    demanded: bool = False
    demand_count: int = 0


class BookCard(BookBrief):
    description: str | None = None
    page_count: int | None = None
    isbn13: str | None = None
    genres: list[str] = []
    language: str | None = None
    avg_score: float | None = None
    ratings_count: int = 0
    readers_count: int = 0
    # Спрос по этой книге: кто ждёт и каких форматов.
    demand_readers: int = 0
    demand_types: list["DemandTypeCount"] = []
    my_demand_type_ids: list[int] = []
    my_review: str | None = None
    my_started_on: date | None = None
    my_finished_on: date | None = None
    open_event_id: int | None = None
    my_application_status: ApplicationStatus | None = None


class DemandTypeCount(BaseModel):
    event_type_id: int
    title: str
    count: int


class BookSearchOut(BaseModel):
    items: list[BookBrief]
    # Хотя бы один внешний источник не ответил. Показываем сноской: выдача
    # неполна, и человеку стоит это знать, прежде чем заводить книгу руками.
    sources_degraded: bool = False


class ExternalRef(BaseModel):
    """Ссылка на книгу во внешнем источнике — то, чем клиент просит завести её
    в каталог, не пересылая карточку целиком."""

    source: str
    external_id: str


class LikeIn(BaseModel):
    liked: bool


class FavouriteIn(BaseModel):
    # 1..4 — место на витрине профиля, пусто — убрать оттуда.
    position: int | None = Field(default=None, ge=1, le=4)


class DiaryIn(BaseModel):
    status: ReadingStatus
    started_on: date | None = None
    finished_on: date | None = None
    score: int | None = Field(default=None, ge=1, le=10)
    review: str | None = Field(default=None, max_length=4000)
    is_private: bool = False


class BookRequestIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    authors: list[str] = []
    year: int | None = Field(default=None, ge=1, le=2100)
    isbn13: str | None = Field(default=None, max_length=13)
    cover_url: str | None = Field(default=None, max_length=1024)
    description: str | None = Field(default=None, max_length=4000)
    comment: str | None = Field(default=None, max_length=1000)


class BookRequestOut(BaseModel):
    id: int
    title: str
    authors: list[str] = []
    year: int | None = None
    status: RequestStatus
    book_id: int | None = None
    created_at: datetime
    user_id: int
    user_name: str | None = None
    decision_comment: str | None = None


# --- Спрос -------------------------------------------------------------------


class DemandIn(BaseModel):
    # Пустой список допустим: «хочу встречу» само по себе полноценная отметка,
    # а форматы — необязательное уточнение.
    event_type_ids: list[int] = []
    comment: str | None = Field(default=None, max_length=500)


class DemandCardOut(BaseModel):
    """Карточка спроса в нижнем ярусе афиши."""

    book: BookBrief
    waiting: int
    readers: int
    types: list[DemandTypeCount]
    joined: bool
    has_application: bool
    last_demand_at: datetime | None = None


# --- Заявки организаторов ----------------------------------------------------


class ApplicationIn(BaseModel):
    book_id: int
    event_type_id: int | None = None
    proposed_type_title: str | None = Field(default=None, max_length=128)
    answers: dict = {}


class ApplicationOut(BaseModel):
    id: int
    book: BookBrief
    user_id: int
    user_name: str
    user_username: str | None = None
    event_type_id: int | None = None
    event_type_title: str | None = None
    proposed_type_title: str | None = None
    answers: dict = {}
    status: ApplicationStatus
    audience: list[MemberKind] = []
    room_title: str | None = None
    invite_link: str | None = None
    decision_comment: str | None = None
    created_at: datetime
    event_id: int | None = None


class ApproveIn(BaseModel):
    # Пустой список — «всем». Заполняется администратором в момент одобрения.
    audience: list[MemberKind] = []
    event_type_id: int | None = None
    comment: str | None = Field(default=None, max_length=1000)


class RejectIn(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)


# --- Мероприятия -------------------------------------------------------------


class SlotIn(BaseModel):
    starts_at: datetime
    duration_minutes: int = Field(default=120, ge=30, le=600)
    place: str | None = Field(default=None, max_length=256)
    note: str | None = Field(default=None, max_length=500)


class SlotsIn(BaseModel):
    slots: list[SlotIn] = Field(min_length=1, max_length=12)
    title: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    capacity: int | None = Field(default=None, ge=1, le=1000)
    min_attendance: int | None = Field(default=None, ge=1, le=1000)
    vote_days: int | None = Field(default=None, ge=1, le=30)


class SlotOut(BaseModel):
    id: int
    starts_at: datetime
    duration_minutes: int
    place: str | None = None
    note: str | None = None
    votes: int = 0
    my_vote: bool = False


class EventOut(BaseModel):
    id: int
    book: BookBrief
    event_type_id: int
    event_type_title: str
    organizer_id: int
    organizer_name: str
    title: str | None = None
    description: str | None = None
    place: str | None = None
    capacity: int | None = None
    audience: list[MemberKind] = []
    status: EventStatus
    vote_deadline: datetime | None = None
    starts_at: datetime | None = None
    duration_minutes: int | None = None
    slots: list[SlotOut] = []
    going: int = 0
    # Друзья, которые уже записались или ждут эту встречу: идти куда-то
    # приятнее, когда знаешь, что там будет свой.
    friends_going: list[str] = []
    friends_waiting: list[str] = []
    my_state: ParticipationState | None = None
    my_event: bool = False
    attended: bool = False
    my_feedback_score: int | None = None
    # Код присутствия показываем только вокруг самой встречи.
    code_available: bool = False
    cancel_reason: str | None = None


class BoardOut(BaseModel):
    """Афиша целиком: сверху встречи, под ними спрос."""

    events: list[EventOut]
    demands: list[DemandCardOut]


class VoteIn(BaseModel):
    slot_ids: list[int] = []


class DecideIn(BaseModel):
    slot_id: int
    note: str | None = Field(default=None, max_length=500)


class ParticipationIn(BaseModel):
    state: ParticipationState


class AttendanceIn(BaseModel):
    code: str = Field(min_length=1, max_length=8)


class FeedbackIn(BaseModel):
    score: int | None = Field(default=None, ge=1, le=10)
    text: str | None = Field(default=None, max_length=4000)


# --- Люди и друзья -----------------------------------------------------------


class PersonBrief(BaseModel):
    id: int
    display_name: str
    photo_url: str | None = None
    tg_username: str | None = None
    member_kind: MemberKind | None = None
    member_kind_title: str | None = None
    friendship: str | None = None  # none | outgoing | incoming | friends


class PersonProfileOut(BaseModel):
    """Чужой профиль: то, что человек показывает клубу."""

    person: PersonBrief
    about: str | None = None
    favourites: list[BookBrief] = []
    finished: int = 0
    events_attended: int = 0
    genres: list[str] = []


class FriendsOut(BaseModel):
    friends: list[PersonBrief]
    incoming: list[PersonBrief]
    outgoing: list[PersonBrief]


# --- Админка -----------------------------------------------------------------


class RoomIn(BaseModel):
    chat_id: int
    title: str | None = Field(default=None, max_length=128)


class RoomOut(BaseModel):
    id: int
    chat_id: int
    title: str
    status: RoomStatus
    application_id: int | None = None
    checked_at: datetime | None = None
    check_error: str | None = None


class SettingOut(BaseModel):
    key: str
    value: object
    title: str
    hint: str | None = None


class SettingIn(BaseModel):
    value: object


class RoleIn(BaseModel):
    user_id: int
    role: UserRole


class EventTypeIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    requires_reading: bool = True
    status: str | None = None
    sort_order: int | None = None


BookCard.model_rebuild()


ProfileOut.model_rebuild()
