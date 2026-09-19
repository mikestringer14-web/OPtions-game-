import { Router } from "express";
import { prisma } from "../db";

export const areasRouter = Router();

// Returns the area's boundary polygon so the mobile app can run the
// leave-the-neighborhood auto-pause check locally (see mobile's
// services/autoPause.ts) without a network round-trip per GPS sample.
areasRouter.get("/:id", async (req, res) => {
  const area = await prisma.canvassArea.findUnique({ where: { id: req.params.id } });
  if (!area) return res.status(404).json({ error: "Area not found" });
  res.json(area);
});
