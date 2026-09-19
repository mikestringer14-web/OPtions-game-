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

// Labels shown on the mobile quick-action prompt and in the PDF report.
// Keep these short - they render as large tap targets on a 2-tap sheet.
export const OUTCOME_LABELS: Record<VisitOutcome, string> = {
  NOT_HOME: "Not Home / Left Hanger",
  BOOKED_QUOTE: "Home - Booked Quote",
  NOT_QUALIFIED: "Home - Not Interested",
  TENANT_NO_OWNER: "Tenant - No Owner",
  DO_NOT_CONTACT: "Do Not Contact",
  CALLBACK_REQUESTED: "Callback Requested",
  VACANT: "Vacant / Under Construction",
  UNSAFE_SKIPPED: "Skipped - Unsafe",
};

// Marker color per outcome, used by both the mobile map and the PDF's
// legend. UNSAFE_SKIPPED is flagged separately so management sees it fast.
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
