export type Role = "user" | "moderator" | "admin" | "superadmin";
export type MemberKind = "student" | "applicant" | "staff" | "guest";
export type ReadingStatus = "want_to_read" | "reading" | "finished" | "abandoned";
export type EventStatus =
  | "slot_selection"
  | "voting"
  | "scheduled"
  | "held"
  | "cancelled";
export type ApplicationStatus =
  | "submitted"
  | "chat_open"
  | "approved"
  | "rejected"
  | "withdrawn";
export type ParticipationState = "going" | "maybe" | "declined" | "waitlist";

export type User = {
  id: number;
  display_name: string;
  role: Role;
  photo_url: string | null;
  tg_username: string | null;
  onboarded: boolean;
};

export type EventType = {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  requires_reading: boolean;
};

export type Reference = { genres: string[]; event_types: EventType[] };

export type Profile = {
  member_kind: MemberKind;
  full_name: string;
  faculty: string | null;
  year: number | null;
  university_email: string | null;
  reading_pace: "rare" | "steady" | "fast" | null;
  club_experience: "none" | "visitor" | "organizer" | null;
  genres: string[];
  event_type_ids: number[];
  about: string | null;
  completed_at: string | null;
  email_required: boolean;
};

export type BookBrief = {
  id: number | null;
  title: string;
  authors: string[];
  year: number | null;
  cover_url: string | null;
  source: string | null;
  external_id: string | null;
  reading_status: ReadingStatus | null;
  my_score: number | null;
  demanded: boolean;
  demand_count: number;
};

export type DemandTypeCount = { event_type_id: number; title: string; count: number };

export type BookCard = BookBrief & {
  description: string | null;
  page_count: number | null;
  isbn13: string | null;
  genres: string[];
  language: string | null;
  avg_score: number | null;
  ratings_count: number;
  readers_count: number;
  demand_readers: number;
  demand_types: DemandTypeCount[];
  my_demand_type_ids: number[];
  my_review: string | null;
  my_started_on: string | null;
  my_finished_on: string | null;
  open_event_id: number | null;
  my_application_status: ApplicationStatus | null;
};

export type BookSearch = { items: BookBrief[]; sources_degraded: boolean };

export type Slot = {
  id: number;
  starts_at: string;
  duration_minutes: number;
  place: string | null;
  note: string | null;
  votes: number;
  my_vote: boolean;
};

export type ClubEvent = {
  id: number;
  book: BookBrief;
  event_type_id: number;
  event_type_title: string;
  organizer_id: number;
  organizer_name: string;
  title: string | null;
  description: string | null;
  place: string | null;
  capacity: number | null;
  audience: MemberKind[];
  status: EventStatus;
  vote_deadline: string | null;
  starts_at: string | null;
  duration_minutes: number | null;
  slots: Slot[];
  going: number;
  my_state: ParticipationState | null;
  my_event: boolean;
  attended: boolean;
  my_feedback_score: number | null;
  cancel_reason: string | null;
};

export type DemandCard = {
  book: BookBrief;
  waiting: number;
  readers: number;
  types: DemandTypeCount[];
  joined: boolean;
  has_application: boolean;
  last_demand_at: string | null;
};

export type Board = { events: ClubEvent[]; demands: DemandCard[] };

export type SurveyQuestion = {
  key: string;
  title: string;
  type: "bool" | "choice" | "multi" | "int" | "text";
  options?: string[];
  required?: boolean;
  placeholder?: string;
};

export type Application = {
  id: number;
  book: BookBrief;
  user_id: number;
  user_name: string;
  user_username: string | null;
  event_type_id: number | null;
  event_type_title: string | null;
  proposed_type_title: string | null;
  answers: Record<string, unknown>;
  status: ApplicationStatus;
  audience: MemberKind[];
  room_title: string | null;
  invite_link: string | null;
  decision_comment: string | null;
  created_at: string;
  event_id: number | null;
};

export type PersonBrief = {
  id: number;
  display_name: string;
  photo_url: string | null;
  tg_username: string | null;
  faculty: string | null;
  member_kind: MemberKind | null;
  friendship: "none" | "outgoing" | "incoming" | "friends" | null;
};

export type Friends = {
  friends: PersonBrief[];
  incoming: PersonBrief[];
  outgoing: PersonBrief[];
};

export type Room = {
  id: number;
  chat_id: number;
  title: string;
  status: "free" | "busy" | "disabled";
  application_id: number | null;
  checked_at: string | null;
  check_error: string | null;
};

export type Setting = { key: string; value: unknown; title: string; hint: string | null };

export type BookRequest = {
  id: number;
  title: string;
  authors: string[];
  year: number | null;
  status: "pending" | "approved" | "rejected";
  book_id: number | null;
  created_at: string;
  user_id: number;
  user_name: string | null;
  decision_comment: string | null;
};

export type MyStats = {
  finished: number;
  finished_this_year: number;
  avg_score: number | null;
  events_attended: number;
};
