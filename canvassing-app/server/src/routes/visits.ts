import { Router } from "express";
import { prisma } from "../db";
import { VISIT_OUTCOMES } from "../types";

export const visitsRouter = Router();

// Logged the instant the canvasser taps an outcome on the quick-action
// prompt. Also stamps the House's current status so the map recolors live.
visitsRouter.post("/", async (req, res) => {
  const { houseId, employeeId, outcome, notes, lat, lng } = req.body as {
    houseId: string;
    employeeId: string;
    outcome: string;
    notes?: string;
    lat: number;
    lng: number;
  };

  if (!houseId || !employeeId || !VISIT_OUTCOMES.includes(outcome as any)) {
    return res.status(400).json({ error: "houseId, employeeId, and a valid outcome are required" });
  }

  const [visit] = await prisma.$transaction([
    prisma.visit.create({
      data: { houseId, employeeId, outcome: outcome as any, notes, lat, lng },
    }),
    prisma.house.update({
      where: { id: houseId },
      data: { status: outcome as any, lastVisitedAt: new Date() },
    }),
  ]);

  res.status(201).json(visit);
});

visitsRouter.get("/", async (req, res) => {
  const { areaId, date } = req.query as { areaId?: string; date?: string };
  if (!areaId) return res.status(400).json({ error: "areaId query param is required" });

  const dayStart = date ? new Date(`${date}T00:00:00`) : undefined;
  const dayEnd = date ? new Date(`${date}T23:59:59`) : undefined;

  const visits = await prisma.visit.findMany({
    where: {
      house: { areaId },
      ...(dayStart && dayEnd ? { timestamp: { gte: dayStart, lte: dayEnd } } : {}),
    },
    include: { house: true, employee: true },
    orderBy: { timestamp: "desc" },
  });

  res.json(visits);
});
