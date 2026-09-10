import { getInitData } from "./telegram";
import type {
  Application,
  Board,
  BookCard,
  BookBrief,
  BookRequest,
  BookSearch,
  ClubEvent,
  Friends,
  MyStats,
  PersonBrief,
  Profile,
  Reference,
  Room,
  Setting,
  SurveyQuestion,
  User,
} from "./types";

// Пусто по умолчанию: запросы идут на тот же origin, а dev-сервер Vite
// проксирует их на бэкенд. Переопределяется через VITE_API_URL, если API
// вынесен отдельно.
const BASE = import.meta.env.VITE_API_URL ?? "";

let token: string | null = null;

export class ApiError extends Error {
  // Поле объявлено отдельно от конструктора: параметры-свойства TypeScript
  // запрещены при erasableSyntaxOnly, включённом в шаблоне Vite.
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });

  if (!response.ok) {
    let message = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      // FastAPI кладёт текст в detail; у ошибок валидации это массив.
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = body.detail[0].msg;
    } catch {
      /* тело не JSON — оставим общий текст */
    }
    throw new ApiError(response.status, message);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export async function login(): Promise<User> {
  const result = await post<{ token: string; user: User }>("/api/auth/telegram", {
    init_data: getInitData(),
  });
  token = result.token;
  return result.user;
}

export const me = () => request<User>("/api/auth/me");

// --- Анкета и профиль --------------------------------------------------------

export const reference = () => request<Reference>("/api/profile/reference");
export const getProfile = () => request<Profile | null>("/api/profile");
export const saveProfile = (body: Partial<Profile>) => put<Profile>("/api/profile", body);

// --- Книги -------------------------------------------------------------------

export const searchBooks = (q: string, external = true) =>
  request<BookSearch>(
    `/api/books?q=${encodeURIComponent(q)}&external=${external ? "true" : "false"}`,
  );
export const getBook = (id: number) => request<BookCard>(`/api/books/${id}`);
export const ensureBook = (source: string, externalId: string) =>
  post<BookCard>("/api/books/ensure", { source, external_id: externalId });
export const markRead = (id: number) => post<BookCard>(`/api/books/${id}/read`);
export const saveDiary = (id: number, body: unknown) =>
  put<BookCard>(`/api/books/${id}/diary`, body);
export const dropDiary = (id: number) => del<BookCard>(`/api/books/${id}/diary`);
export const requestBook = (body: unknown) => post<BookRequest>("/api/books/requests", body);

// --- Спрос и афиша -----------------------------------------------------------

export const board = () => request<Board>("/api/board");
export const pastBoard = () => request<Board>("/api/board/past");
export const addDemand = (bookId: number, eventTypeIds: number[], comment?: string) =>
  post<void>(`/api/books/${bookId}/demand`, {
    event_type_ids: eventTypeIds,
    comment: comment ?? null,
  });
export const dropDemand = (bookId: number) => del<void>(`/api/books/${bookId}/demand`);

// --- Заявки ------------------------------------------------------------------

export const survey = () => request<SurveyQuestion[]>("/api/applications/survey");
export const applyToOrganize = (body: unknown) => post<Application>("/api/applications", body);
export const myApplications = () => request<Application[]>("/api/applications/mine");
export const withdrawApplication = (id: number) =>
  post<void>(`/api/applications/${id}/withdraw`);
export const applications = () => request<Application[]>("/api/applications");
export const openRoom = (id: number) => post<Application>(`/api/applications/${id}/open-room`);
export const approveApplication = (id: number, body: unknown) =>
  post<Application>(`/api/applications/${id}/approve`, body);
export const rejectApplication = (id: number, comment: string) =>
  post<Application>(`/api/applications/${id}/reject`, { comment });

// --- Мероприятия -------------------------------------------------------------

export const getEvent = (id: number) => request<ClubEvent>(`/api/events/${id}`);
export const publishSlots = (id: number, body: unknown) =>
  post<ClubEvent>(`/api/events/${id}/slots`, body);
export const voteSlots = (id: number, slotIds: number[]) =>
  post<ClubEvent>(`/api/events/${id}/vote`, { slot_ids: slotIds });
export const decideSlot = (id: number, slotId: number, note?: string) =>
  post<ClubEvent>(`/api/events/${id}/decide`, { slot_id: slotId, note: note ?? null });
export const setParticipation = (id: number, state: string) =>
  post<ClubEvent>(`/api/events/${id}/participation`, { state });
export const attendanceCode = (id: number) =>
  request<{ code: string }>(`/api/events/${id}/code`);
export const attend = (id: number, code: string) =>
  post<ClubEvent>(`/api/events/${id}/attend`, { code });
export const attendManual = (id: number, userId: number) =>
  post<ClubEvent>(`/api/events/${id}/attend/${userId}`);
export const eventPeople = (id: number) =>
  request<{ id: number; name: string; state: string }[]>(`/api/events/${id}/people`);
export const sendFeedback = (id: number, body: unknown) =>
  post<ClubEvent>(`/api/events/${id}/feedback`, body);

// --- Личное ------------------------------------------------------------------

export const myBooks = (status?: string) =>
  request<BookBrief[]>(`/api/me/books${status ? `?status=${status}` : ""}`);
export const myStats = () => request<MyStats>("/api/me/stats");
export const myEvents = () => request<ClubEvent[]>("/api/me/events");

// --- Друзья ------------------------------------------------------------------

export const friends = () => request<Friends>("/api/friends");
export const searchPeople = (q: string) =>
  request<PersonBrief[]>(`/api/friends/search?q=${encodeURIComponent(q)}`);
export const addFriend = (id: number) => post<PersonBrief>(`/api/friends/${id}`);
export const dropFriend = (id: number) => del<void>(`/api/friends/${id}`);

// --- Админка -----------------------------------------------------------------

export const bookRequests = () => request<BookRequest[]>("/api/admin/book-requests");
export const approveBookRequest = (id: number) =>
  post<void>(`/api/admin/book-requests/${id}/approve`);
export const rejectBookRequest = (id: number, comment: string) =>
  post<void>(`/api/admin/book-requests/${id}/reject`, { value: comment });
export const rooms = () => request<Room[]>("/api/admin/rooms");
export const addRoom = (chatId: number, title?: string) =>
  post<Room>("/api/admin/rooms", { chat_id: chatId, title: title ?? null });
export const checkRoom = (id: number) => post<void>(`/api/admin/rooms/${id}/check`);
export const deleteRoom = (id: number) => del<void>(`/api/admin/rooms/${id}`);
export const releaseRoom = (id: number) => post<void>(`/api/admin/rooms/${id}/release`);
export const settings = () => request<Setting[]>("/api/admin/settings");
export const saveSettings = (values: Record<string, unknown>) =>
  put<Record<string, unknown>>("/api/admin/settings", values);
export const people = () =>
  request<{ id: number; name: string; username: string | null; role: string }[]>(
    "/api/admin/people",
  );
export const setRole = (userId: number, role: string) =>
  post<void>("/api/admin/roles", { user_id: userId, role });
export const funnel = () => request<Record<string, number>>("/api/analytics/funnel");
export const unmetDemand = () =>
  request<{ book_id: number; title: string; waiting: number; since: string }[]>(
    "/api/analytics/unmet-demand",
  );
export const byType = () =>
  request<
    {
      type: string;
      events: number;
      attendances: number;
      confirmed: number;
      avg_score: number | null;
    }[]
  >("/api/analytics/by-type");
export const byProgram = () =>
  request<
    {
      program: string | null;
      program_title: string;
      member_kind: string | null;
      study_level: string | null;
      people: number;
      attendances: number;
    }[]
  >("/api/analytics/by-program");
