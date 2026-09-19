import { create } from "zustand";
import { Employee, House, WorkSession } from "../types";

type PromptTarget = { house: House } | null;

type AppState = {
  employee: Employee | null;
  areaId: string | null;
  session: WorkSession | null;
  houses: House[];
  // The house the quick-action sheet is currently open for, set the moment
  // a geofence-exit is detected (see services/locationTracking.ts).
  promptTarget: PromptTarget;

  setEmployeeAndArea: (employee: Employee, areaId: string) => void;
  setSession: (session: WorkSession | null) => void;
  setHouses: (houses: House[]) => void;
  updateHouseStatus: (houseId: string, status: House["status"]) => void;
  openPrompt: (house: House) => void;
  closePrompt: () => void;
};

export const useAppStore = create<AppState>((set) => ({
  employee: null,
  areaId: null,
  session: null,
  houses: [],
  promptTarget: null,

  setEmployeeAndArea: (employee, areaId) => set({ employee, areaId }),
  setSession: (session) => set({ session }),
  setHouses: (houses) => set({ houses }),
  updateHouseStatus: (houseId, status) =>
    set((s) => ({
      houses: s.houses.map((h) =>
        h.id === houseId ? { ...h, status, lastVisitedAt: new Date().toISOString() } : h
      ),
    })),
  openPrompt: (house) => set({ promptTarget: { house } }),
  closePrompt: () => set({ promptTarget: null }),
}));
