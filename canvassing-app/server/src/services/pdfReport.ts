import PDFDocument from "pdfkit";
import fs from "fs";
import path from "path";
import { prisma } from "../db";
import { OUTCOME_LABELS, VisitOutcome } from "../types";

const REPORTS_DIR = path.join(__dirname, "..", "..", "reports");

/**
 * Builds the end-of-day PDF for one canvass area/date: a summary count per
 * outcome, then a full house-by-house table (address, outcome, canvasser,
 * time). Saved to disk and the path is returned so the caller can email it
 * or serve it for download.
 */
export async function generateDailyReportPdf(areaId: string, date: string): Promise<string> {
  const area = await prisma.canvassArea.findUniqueOrThrow({ where: { id: areaId } });

  const dayStart = new Date(`${date}T00:00:00`);
  const dayEnd = new Date(`${date}T23:59:59`);

  const visits = await prisma.visit.findMany({
    where: { house: { areaId }, timestamp: { gte: dayStart, lte: dayEnd } },
    include: { house: true, employee: true },
    orderBy: { timestamp: "asc" },
  });

  const houses = await prisma.house.findMany({ where: { areaId } });

  fs.mkdirSync(REPORTS_DIR, { recursive: true });
  const filePath = path.join(REPORTS_DIR, `${areaId}_${date}.pdf`);

  const doc = new PDFDocument({ margin: 40 });
  doc.pipe(fs.createWriteStream(filePath));

  doc.fontSize(18).text(`Canvassing Report - ${area.name}`, { align: "left" });
  doc.fontSize(11).fillColor("#555").text(date);
  doc.moveDown(1);

  // --- Summary counts ---
  const counts: Record<string, number> = {};
  for (const v of visits) counts[v.outcome] = (counts[v.outcome] ?? 0) + 1;

  doc.fillColor("#000").fontSize(13).text("Summary", { underline: true });
  doc.moveDown(0.3);
  doc.fontSize(11);
  for (const outcome of Object.keys(OUTCOME_LABELS) as VisitOutcome[]) {
    if (counts[outcome]) {
      doc.text(`${OUTCOME_LABELS[outcome]}: ${counts[outcome]}`);
    }
  }
  const untouched = houses.filter((h) => !h.lastVisitedAt || h.lastVisitedAt < dayStart).length;
  doc.text(`Not yet visited: ${untouched}`);
  doc.moveDown(1);

  // --- House-by-house table ---
  doc.fontSize(13).text("House-by-House Detail", { underline: true });
  doc.moveDown(0.3);
  doc.fontSize(10);

  const colX = { address: 40, outcome: 260, employee: 400, time: 490 };
  const headerY = doc.y;
  doc
    .font("Helvetica-Bold")
    .text("Address", colX.address, headerY)
    .text("Outcome", colX.outcome, headerY)
    .text("Canvasser", colX.employee, headerY)
    .text("Time", colX.time, headerY);
  doc.font("Helvetica").moveDown(0.5);

  for (const v of visits) {
    if (doc.y > 740) doc.addPage();
    const rowY = doc.y;
    doc
      .text(v.house.address, colX.address, rowY, { width: 210 })
      .text(OUTCOME_LABELS[v.outcome as VisitOutcome], colX.outcome, rowY, { width: 130 })
      .text(v.employee.name, colX.employee, rowY, { width: 85 })
      .text(v.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), colX.time, rowY);
    doc.moveDown(0.6);
  }

  doc.end();

  return new Promise((resolve, reject) => {
    doc.on("end", () => resolve(filePath));
    doc.on("error", reject);
  });
}
