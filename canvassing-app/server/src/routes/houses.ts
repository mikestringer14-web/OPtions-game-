import { Router } from "express";
import { prisma } from "../db";
import { generateFallbackFootprint } from "../services/geofence";

export const housesRouter = Router();

// List all houses for a canvass area, with their current status, for the
// mobile map screen.
housesRouter.get("/", async (req, res) => {
  const { areaId } = req.query;
  if (!areaId || typeof areaId !== "string") {
    return res.status(400).json({ error: "areaId query param is required" });
  }

  const houses = await prisma.house.findMany({ where: { areaId } });
  res.json(
    houses.map((h) => ({
      ...h,
      footprintGeoJson:
        h.footprintGeoJson ??
        JSON.stringify(generateFallbackFootprint({ lat: h.lat, lng: h.lng })),
    }))
  );
});

// Bulk-import houses for an area, e.g. from a CSV of addresses geocoded
// ahead of a canvassing run. Existing houses at the same lat/lng are left
// alone (idempotent import).
housesRouter.post("/import", async (req, res) => {
  const { areaId, houses } = req.body as {
    areaId: string;
    houses: { address: string; lat: number; lng: number; footprintGeoJson?: string }[];
  };

  if (!areaId || !Array.isArray(houses)) {
    return res.status(400).json({ error: "areaId and houses[] are required" });
  }

  const created = await prisma.$transaction(
    houses.map((h) =>
      prisma.house.create({
        data: {
          areaId,
          address: h.address,
          lat: h.lat,
          lng: h.lng,
          footprintGeoJson: h.footprintGeoJson,
        },
      })
    )
  );

  res.status(201).json({ created: created.length });
});
