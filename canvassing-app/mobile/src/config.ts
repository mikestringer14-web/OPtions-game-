export const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:4000";
export const API_KEY = process.env.EXPO_PUBLIC_API_KEY ?? "";

// --- Tunable thresholds ---

// A canvasser is considered "at" a house while within this radius (meters).
// Used to trigger the quick-action prompt on exit.
export const HOUSE_GEOFENCE_RADIUS_M = 20;

// Speed above this (km/h, sustained) is treated as vehicle travel rather
// than walking a route, for the privacy auto-pause feature.
export const DRIVING_SPEED_THRESHOLD_KMH = 25;

// How many consecutive samples above the speed threshold, while also
// outside the canvass area boundary, before auto-pause fires. Avoids a
// single noisy GPS fix (a bad fix reporting 40km/h for one reading)
// stopping tracking mid-shift.
export const DRIVING_CONFIRM_SAMPLES = 3;

// Foreground/background location sampling interval while clocked in.
export const LOCATION_UPDATE_INTERVAL_MS = 8000;
export const LOCATION_DISTANCE_FILTER_M = 10;

// Batch size / interval for flushing buffered track points to the server.
export const TRACKPOINT_FLUSH_INTERVAL_MS = 30000;
