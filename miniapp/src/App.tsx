import { useEffect, useState } from "react";
import * as api from "./api";
import { Admin } from "./screens/Admin";
import { ApplicationForm } from "./screens/ApplicationForm";
import { BookDetail } from "./screens/BookDetail";
import { Books } from "./screens/Books";
import { EventDetail } from "./screens/EventDetail";
import { Events } from "./screens/Events";
import { Friends } from "./screens/Friends";
import { MyBooks } from "./screens/MyBooks";
import { Onboarding } from "./screens/Onboarding";
import { Profile } from "./screens/Profile";
import { initTelegram } from "./telegram";
import type { BookBrief, BookCard, EventType, User } from "./types";

type Tab = "books" | "events" | "profile";

// Три вкладки. Дневник живёт внутри карточки книги, спрос — вторым ярусом
// афиши: и то и другое — части одной истории, и разносить их по вкладкам
// значило бы заставлять человека складывать её самому.
const TABS: { key: Tab; icon: string; label: string }[] = [
  { key: "books", icon: "📚", label: "Книги" },
  { key: "events", icon: "📅", label: "Афиша" },
  { key: "profile", icon: "👤", label: "Профиль" },
];

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("books");
  const [genres, setGenres] = useState<string[]>([]);
  const [eventTypes, setEventTypes] = useState<EventType[]>([]);

  // Оверлеи поверх вкладок. Роутера нет: экранов немного, а ссылка из
  // уведомления приходит параметром — этого хватает.
  const [openBook, setOpenBook] = useState<{ book: BookBrief; want: boolean } | null>(null);
  const [openEvent, setOpenEvent] = useState<number | null>(null);
  const [organizeFor, setOrganizeFor] = useState<BookCard | null>(null);
  const [screen, setScreen] = useState<"none" | "books" | "friends" | "admin">("none");

  useEffect(() => {
    initTelegram();
    api
      .login()
      .then(async (loaded) => {
        setUser(loaded);
        const reference = await api.reference();
        setGenres(reference.genres);
        setEventTypes(reference.event_types);
      })
      .catch((e) => setAuthError(e instanceof Error ? e.message : "Не удалось войти"));
  }, []);

  // Бот открывает приложение адресом вида ?event=12 или ?book=3.
  useEffect(() => {
    if (!user?.onboarded) return;
    const params = new URLSearchParams(location.search);
    const event = params.get("event");
    const book = params.get("book");
    if (event && /^\d+$/.test(event)) {
      setTab("events");
      setOpenEvent(Number(event));
    } else if (book && /^\d+$/.test(book)) {
      setOpenBook({ book: emptyBook(Number(book)), want: false });
    } else if (params.get("tab") === "profile") {
      setTab("profile");
    }
  }, [user?.onboarded]);

  if (authError) {
    return (
      <div className="center">
        <p className="error">{authError}</p>
        <p className="hint">
          Приложение работает только внутри Telegram: вход подтверждается подписью, которую
          выдаёт сам мессенджер.
        </p>
      </div>
    );
  }

  if (!user) return <div className="center">Загружаем…</div>;

  // До анкеты остальное приложение закрыто — и на сервере тоже, эта проверка
  // лишь избавляет от бессмысленных 403.
  if (!user.onboarded) {
    return (
      <div className="app">
        <Onboarding
          initial={null}
          genres={genres}
          eventTypes={eventTypes}
          onSaved={() => setUser({ ...user, onboarded: true })}
        />
      </div>
    );
  }

  return (
    <div className="app">
      {tab === "books" && (
        <Books onOpenBook={(book, want = false) => setOpenBook({ book, want })} />
      )}
      {tab === "events" && (
        <Events
          onOpenEvent={setOpenEvent}
          onOpenBook={(bookId, want = false) =>
            setOpenBook({ book: emptyBook(bookId), want })
          }
        />
      )}
      {tab === "profile" && (
        <Profile
          user={user}
          genres={genres}
          eventTypes={eventTypes}
          onOpenBooks={() => setScreen("books")}
          onOpenFriends={() => setScreen("friends")}
          onOpenAdmin={() => setScreen("admin")}
          onOpenEvent={setOpenEvent}
        />
      )}

      {openBook && (
        <BookDetail
          book={openBook.book}
          eventTypes={eventTypes}
          wantOnOpen={openBook.want}
          onClose={() => setOpenBook(null)}
          onOrganize={(card) => {
            setOpenBook(null);
            setOrganizeFor(card);
          }}
          onOpenEvent={(id) => {
            setOpenBook(null);
            setOpenEvent(id);
          }}
        />
      )}

      {organizeFor && (
        <ApplicationForm
          book={organizeFor}
          eventTypes={eventTypes}
          onClose={() => setOrganizeFor(null)}
          onSent={() => {
            setOrganizeFor(null);
            setTab("profile");
          }}
        />
      )}

      {openEvent !== null && (
        <EventDetail eventId={openEvent} onClose={() => setOpenEvent(null)} />
      )}

      {screen === "books" && (
        <MyBooks
          onClose={() => setScreen("none")}
          onOpenBook={(book, want = false) => setOpenBook({ book, want })}
        />
      )}
      {screen === "friends" && <Friends onClose={() => setScreen("none")} />}
      {screen === "admin" && <Admin role={user.role} onClose={() => setScreen("none")} />}

      <nav className="tabs">
        {TABS.map((item) => (
          <button
            key={item.key}
            aria-current={tab === item.key ? "page" : undefined}
            onClick={() => setTab(item.key)}
          >
            <span className="icon" aria-hidden>
              {item.icon}
            </span>
            {item.label}
          </button>
        ))}
      </nav>
    </div>
  );
}

/** Заглушка книги по одному id: карточка всё равно догрузит себя сама. */
function emptyBook(id: number): BookBrief {
  return {
    id,
    title: "",
    authors: [],
    year: null,
    cover_url: null,
    source: null,
    external_id: null,
    reading_status: null,
    my_score: null,
    demanded: false,
    demand_count: 0,
  };
}
