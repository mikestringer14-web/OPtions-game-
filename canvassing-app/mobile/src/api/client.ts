import { API_URL, API_KEY } from "../config";
import { House, VisitOutcome, WorkSession } from "../types";

export type CanvassArea = {
  id: string;
  name: string;
  boundaryGeoJson: string;
  managerEmails: string;
};

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "x-api-key": API_KEY,
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  clockIn: (employeeId: string, pinCode: string, areaId: string) =>
    request<WorkSession>("/api/sessions/clock-in", {
      method: "POST",
      body: JSON.stringify({ employeeId, pinCode, areaId }),
    }),

  clockOut: (sessionId: string) =>
    request<WorkSession>(`/api/sessions/${sessionId}/clock-out`, { method: "POST" }),

  autoPause: (sessionId: string) =>
    request<WorkSession>(`/api/sessions/${sessionId}/auto-pause`, { method: "POST" }),

  pushTrackPoints: (
    sessionId: string,
    points: { lat: number; lng: number; speedMps?: number; timestamp?: string }[]
  ) =>
    request(`/api/sessions/${sessionId}/track-points`, {
      method: "POST",
      body: JSON.stringify({ points }),
    }),

  getHouses: (areaId: string) => request<House[]>(`/api/houses?areaId=${areaId}`),

  getArea: (areaId: string) => request<CanvassArea>(`/api/areas/${areaId}`),

  logVisit: (data: {
    houseId: string;
    employeeId: string;
    outcome: VisitOutcome;
    notes?: string;
    lat: number;
    lng: number;
  }) =>
    request("/api/visits", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};
