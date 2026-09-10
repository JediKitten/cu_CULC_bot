from enum import StrEnum

import sqlalchemy as sa


def enum_col(py_enum: type[StrEnum], name: str) -> sa.Enum:
    """VARCHAR + CHECK вместо нативного типа Postgres.

    Список форматов встреч, видов уведомлений и статусов будет расти, а
    добавить значение в нативный pg enum внутри транзакции нельзя —
    пересобрать CHECK можно.
    """
    return sa.Enum(
        py_enum,
        native_enum=False,
        create_constraint=True,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        length=32,
    )


class UserRole(StrEnum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]


_ROLE_RANK = {
    UserRole.USER: 0,
    UserRole.MODERATOR: 1,
    UserRole.ADMIN: 2,
    UserRole.SUPERADMIN: 3,
}


class MemberKind(StrEnum):
    """Кто человек клубу.

    Ступень обучения — часть роли, а не отдельное поле: «бакалавр» и
    «магистрант» это разные ответы на один вопрос, и держать их двумя
    колонками значило бы позволить состояния вроде «сотрудник-магистрант».
    """

    APPLICANT = "applicant"
    BACHELOR = "bachelor"
    MASTER = "master"
    STAFF = "staff"
    GUEST = "guest"


# Категории, у которых студенческая почта обязательна.
EMAIL_REQUIRED_KINDS = frozenset({MemberKind.BACHELOR, MemberKind.MASTER})


class ReadingPace(StrEnum):
    NONE = "none"  # вообще не читаю
    RARE = "rare"  # несколько книг в год
    STEADY = "steady"  # книга в месяц
    FAST = "fast"  # несколько книг в месяц


class ClubExperience(StrEnum):
    NONE = "none"
    VISITOR = "visitor"  # бывал гостем
    ORGANIZER = "organizer"  # вёл встречи


class BookStatus(StrEnum):
    ACTIVE = "active"
    HIDDEN = "hidden"
    PENDING_MODERATION = "pending_moderation"


class BookSourceKind(StrEnum):
    GOOGLE_BOOKS = "google_books"
    OPEN_LIBRARY = "open_library"
    MANUAL = "manual"


class RequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReadingStatus(StrEnum):
    WANT_TO_READ = "want_to_read"
    READING = "reading"
    FINISHED = "finished"
    ABANDONED = "abandoned"


class EventTypeStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"
    HIDDEN = "hidden"


class RevokeReason(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"  # встреча по книге назначена, спрос закрыт


class ApplicationStatus(StrEnum):
    SUBMITTED = "submitted"
    CHAT_OPEN = "chat_open"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class RoomStatus(StrEnum):
    FREE = "free"
    BUSY = "busy"
    DISABLED = "disabled"


class EventStatus(StrEnum):
    SLOT_SELECTION = "slot_selection"  # организатор расставляет окна
    VOTING = "voting"  # участники выбирают удобное
    SCHEDULED = "scheduled"  # время закреплено
    HELD = "held"
    CANCELLED = "cancelled"


class DecidedBy(StrEnum):
    AUTO = "auto"
    ORGANIZER = "organizer"
    ADMIN = "admin"


class ParticipationState(StrEnum):
    """Промежуточного «может быть» нет намеренно: организатору нужно знать,
    на сколько человек рассчитывать, а «может быть» не отвечает на этот вопрос
    и лишь размывает кворум."""

    GOING = "going"
    DECLINED = "declined"
    WAITLIST = "waitlist"


class AttendanceMethod(StrEnum):
    CODE = "code"
    MANUAL = "manual"


class FriendshipStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class NotificationKind(StrEnum):
    DEMAND_THRESHOLD = "demand_threshold"
    APPLICATION_SUBMITTED = "application_submitted"
    APPLICATION_CHAT_OPEN = "application_chat_open"
    APPLICATION_APPROVED = "application_approved"
    APPLICATION_REJECTED = "application_rejected"
    NO_FREE_ROOM = "no_free_room"
    SLOT_VOTING_OPEN = "slot_voting_open"
    EVENT_SCHEDULED = "event_scheduled"
    EVENT_CHANGED = "event_changed"
    EVENT_CANCELLED = "event_cancelled"
    REMINDER_24H = "reminder_24h"
    REMINDER_2H = "reminder_2h"
    LOW_ATTENDANCE = "low_attendance"
    FEEDBACK_REQUEST = "feedback_request"
    FRIEND_REQUEST = "friend_request"
    FRIEND_ACCEPTED = "friend_accepted"
    ROLE_GRANTED = "role_granted"
    BOOK_REQUEST_DECIDED = "book_request_decided"
