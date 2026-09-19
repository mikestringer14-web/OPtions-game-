export const VISIT_OUTCOMES = [
  "NOT_HOME",
  "BOOKED_QUOTE",
  "NOT_QUALIFIED",
  "TENANT_NO_OWNER",
  "DO_NOT_CONTACT",
  "CALLBACK_REQUESTED",
  "VACANT",
  "UNSAFE_SKIPPED",
] as const;

export type VisitOutcome = (typeof VISIT_OUTCOMES)[number];

export const OUTCOME_LABELS: Record<VisitOutcome, string> = {
  NOT_HOME: "Not Home / Left Hanger",
  BOOKED_QUOTE: "Booked Quote",
  NOT_QUALIFIED: "Not Interested",
  TENANT_NO_OWNER: "Tenant - No Owner",
  DO_NOT_CONTACT: "Do Not Contact",
  CALLBACK_REQUESTED: "Callback Requested",
  VACANT: "Vacant / Under Construction",
  UNSAFE_SKIPPED: "Skip - Unsafe",
};

export const OUTCOME_COLORS: Record<VisitOutcome, string> = {
  NOT_HOME: "#9CA3AF",
  BOOKED_QUOTE: "#22C55E",
  NOT_QUALIFIED: "#F59E0B",
  TENANT_NO_OWNER: "#3B82F6",
  DO_NOT_CONTACT: "#EF4444",
  CALLBACK_REQUESTED: "#A855F7",
  VACANT: "#6B7280",
  UNSAFE_SKIPPED: "#DC2626",
};

// The 4 outcomes shown by default on the quick-action sheet (matches what
// was asked for). The other 4 are reachable via "More options" so the
// primary sheet stays a true 2-tap flow. Reorder/trim in Settings later if
// the crew wants a different default set.
export const PRIMARY_OUTCOMES: VisitOutcome[] = [
  "NOT_HOME",
  "BOOKED_QUOTE",
  "NOT_QUALIFIED",
  "TENANT_NO_OWNER",
];

export const SECONDARY_OUTCOMES: VisitOutcome[] = [
  "CALLBACK_REQUESTED",
  "DO_NOT_CONTACT",
  "VACANT",
  "UNSAFE_SKIPPED",
];

export type House = {
  id: string;
  areaId: string;
  address: string;
  lat: number;
  lng: number;
  footprintGeoJson: string;
  status: VisitOutcome | null;
  lastVisitedAt: string | null;
};

export type Employee = {
  id: string;
  name: string;
  email: string;
  role: "CANVASSER" | "MANAGER" | "ADMIN";
};

export type WorkSession = {
  id: string;
  employeeId: string;
  areaId: string;
  clockInAt: string;
  clockOutAt: string | null;
  autoPausedAt: string | null;
};
