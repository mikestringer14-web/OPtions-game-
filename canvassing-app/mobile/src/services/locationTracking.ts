import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { House } from "../types";
import { useAppStore } from "../state/store";
import { api } from "../api/client";
import { DrivingAwayDetector } from "./autoPause";
import { haversineMeters } from "./geo";
import {
  HOUSE_GEOFENCE_RADIUS_M,
  LOCATION_DISTANCE_FILTER_M,
  LOCATION_UPDATE_INTERVAL_MS,
  TRACKPOINT_FLUSH_INTERVAL_MS,
} from "../config";

export const LOCATION_TASK_NAME = "canvassing-location-task";

// Module-level state for the running shift. Reset on clock-in/clock-out.
// (Expo's managed background task runs in the same JS context as the app
// while it's alive; if iOS fully suspends the process between updates,
// TaskManager relaunches this module fresh and these reset to defaults -
// acceptable here since a relaunch mid-shift just means one missed
// "currently at this house" carry-over, not lost data.)
let sessionId: string | null = null;
let employeeId: string | null = null;
let areaBoundary: number[][] = [];
let houses: House[] = [];
let currentHouseId: string | null = null;
let drivingDetector: DrivingAwayDetector | null = null;
let pointBuffer: { lat: number; lng: number; speedMps?: number; timestamp: string }[] = [];
let flushTimer: ReturnType<typeof setInterval> | null = null;
let onAutoPause: (() => void) | null = null;

function nearestHouseWithin(lat: number, lng: number, radiusM: number): House | null {
  let best: House | null = null;
  let bestDist = Infinity;
  for (const h of houses) {
    const d = haversineMeters({ lat, lng }, { lat: h.lat, lng: h.lng });
    if (d < radiusM && d < bestDist) {
      best = h;
      bestDist = d;
    }
  }
  return best;
}

async function flushBuffer() {
  if (!sessionId || pointBuffer.length === 0) return;
  const toSend = pointBuffer;
  pointBuffer = [];
  try {
    await api.pushTrackPoints(sessionId, toSend);
  } catch {
    // Network hiccup - drop rather than grow unbounded; the shift's route
    // history is a nice-to-have, not the source of truth for visit outcomes.
  }
}

function handleLocationUpdate(loc: Location.LocationObject) {
  const { latitude: lat, longitude: lng, speed } = loc.coords;

  pointBuffer.push({ lat, lng, speedMps: speed ?? undefined, timestamp: new Date(loc.timestamp).toISOString() });

  // --- Per-house geofence exit -> quick-action prompt ---
  const nearHouse = nearestHouseWithin(lat, lng, HOUSE_GEOFENCE_RADIUS_M);
  if (nearHouse && nearHouse.id !== currentHouseId) {
    currentHouseId = nearHouse.id;
  } else if (!nearHouse && currentHouseId) {
    const leftHouse = houses.find((h) => h.id === currentHouseId);
    currentHouseId = null;
    if (leftHouse && !leftHouse.status) {
      // Only prompt for houses that don't already have today's outcome
      // logged, so re-passing a house you already handled doesn't nag you.
      useAppStore.getState().openPrompt(leftHouse);
    }
  }

  // --- Privacy auto-pause ---
  if (drivingDetector) {
    const { confirmed } = drivingDetector.sample({ lat, lng }, speed);
    if (confirmed) {
      onAutoPause?.();
    }
  }
}

TaskManager.defineTask(LOCATION_TASK_NAME, ({ data, error }) => {
  if (error) return;
  const { locations } = data as { locations: Location.LocationObject[] };
  locations.forEach(handleLocationUpdate);
});

export async function requestPermissions(): Promise<boolean> {
  const fg = await Location.requestForegroundPermissionsAsync();
  if (fg.status !== "granted") return false;
  const bg = await Location.requestBackgroundPermissionsAsync();
  return bg.status === "granted";
}

export async function startTracking(opts: {
  sessionId: string;
  employeeId: string;
  areaBoundaryGeoJson: string;
  houses: House[];
  onAutoPause: () => void;
}) {
  sessionId = opts.sessionId;
  employeeId = opts.employeeId;
  areaBoundary = JSON.parse(opts.areaBoundaryGeoJson);
  houses = opts.houses;
  currentHouseId = null;
  drivingDetector = new DrivingAwayDetector(areaBoundary);
  onAutoPause = opts.onAutoPause;
  pointBuffer = [];

  await Location.startLocationUpdatesAsync(LOCATION_TASK_NAME, {
    accuracy: Location.Accuracy.Balanced,
    timeInterval: LOCATION_UPDATE_INTERVAL_MS,
    distanceInterval: LOCATION_DISTANCE_FILTER_M,
    showsBackgroundLocationIndicator: true,
    foregroundService: {
      notificationTitle: "Canvassing Tracker",
      notificationBody: "Tracking your route while you're clocked in.",
    },
  });

  flushTimer = setInterval(flushBuffer, TRACKPOINT_FLUSH_INTERVAL_MS);
}

export async function stopTracking() {
  const running = await TaskManager.isTaskRegisteredAsync(LOCATION_TASK_NAME);
  if (running) await Location.stopLocationUpdatesAsync(LOCATION_TASK_NAME);
  if (flushTimer) clearInterval(flushTimer);
  await flushBuffer();

  sessionId = null;
  employeeId = null;
  houses = [];
  currentHouseId = null;
  drivingDetector = null;
  onAutoPause = null;
}

/** Call after the visits list refreshes so a just-logged house stops
 * being eligible to re-trigger the prompt on a later pass-by. */
export function syncHouses(updated: House[]) {
  houses = updated;
}
