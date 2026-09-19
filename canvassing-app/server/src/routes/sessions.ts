import { Router } from "express";
import { prisma } from "../db";

export const sessionsRouter = Router();

// Clock in: verifies the employee PIN and opens a WorkSession.
sessionsRouter.post("/clock-in", async (req, res) => {
  const { employeeId, pinCode, areaId } = req.body as {
    employeeId: string;
    pinCode: string;
    areaId: string;
  };

  const employee = await prisma.employee.findUnique({ where: { id: employeeId } });
  if (!employee || employee.pinCode !== pinCode || !employee.active) {
    return res.status(401).json({ error: "Invalid employee or PIN" });
  }

  const session = await prisma.workSession.create({
    data: { employeeId, areaId },
  });

  res.status(201).json(session);
});

sessionsRouter.post("/:id/clock-out", async (req, res) => {
  const session = await prisma.workSession.update({
    where: { id: req.params.id },
    data: { clockOutAt: new Date() },
  });
  res.json(session);
});

// Called by the mobile app's auto-pause logic (see mobile/src/services/autoPause.ts)
// the moment it detects the device left the canvass area boundary at driving
// speed. This is a privacy control, not a punitive one - it stops location
// collection immediately rather than waiting for an explicit clock-out.
sessionsRouter.post("/:id/auto-pause", async (req, res) => {
  const session = await prisma.workSession.update({
    where: { id: req.params.id },
    data: { autoPausedAt: new Date() },
  });
  res.json(session);
});

// Batched track-point upload. The mobile app buffers points locally and
// flushes every ~30s or N points to avoid hammering the API on cellular.
sessionsRouter.post("/:id/track-points", async (req, res) => {
  const { points } = req.body as {
    points: { lat: number; lng: number; speedMps?: number; timestamp?: string }[];
  };
  if (!Array.isArray(points) || points.length === 0) {
    return res.status(400).json({ error: "points[] is required" });
  }

  await prisma.trackPoint.createMany({
    data: points.map((p) => ({
      sessionId: req.params.id,
      lat: p.lat,
      lng: p.lng,
      speedMps: p.speedMps,
      timestamp: p.timestamp ? new Date(p.timestamp) : new Date(),
    })),
  });

  res.status(201).json({ inserted: points.length });
});
