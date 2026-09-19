import { Router } from "express";
import { prisma } from "../db";
import { generateDailyReportPdf } from "../services/pdfReport";
import { emailDailyReport } from "../services/email";

export const reportsRouter = Router();

/**
 * Generates (or reuses) today's PDF for an area and emails it to the
 * area's manager list. Called either manually from a management endpoint,
 * or automatically the moment every clocked-in employee's WorkSession for
 * that area has an clockOutAt/autoPausedAt set for the day (see the
 * end-of-day trigger note in README "Automatic end-of-day email").
 */
reportsRouter.post("/daily/:areaId/:date/send", async (req, res) => {
  const { areaId, date } = req.params;

  try {
    const area = await prisma.canvassArea.findUniqueOrThrow({ where: { id: areaId } });
    const pdfPath = await generateDailyReportPdf(areaId, date);

    await prisma.dailyReport.upsert({
      where: { areaId_date: { areaId, date } },
      create: { areaId, date, pdfPath, recipients: area.managerEmails },
      update: { pdfPath },
    });

    const toEmails = area.managerEmails.split(",").map((e) => e.trim()).filter(Boolean);
    await emailDailyReport({ toEmails, areaName: area.name, date, pdfPath });

    await prisma.dailyReport.update({
      where: { areaId_date: { areaId, date } },
      data: { emailedAt: new Date() },
    });

    res.json({ ok: true, pdfPath, emailedTo: toEmails });
  } catch (err: any) {
    // Report generation still succeeds even if email isn't configured yet -
    // return 207 so the caller knows the PDF exists but wasn't sent.
    res.status(207).json({ ok: false, error: err.message });
  }
});

reportsRouter.get("/daily/:areaId/:date", async (req, res) => {
  const { areaId, date } = req.params;
  const pdfPath = await generateDailyReportPdf(areaId, date);
  res.download(pdfPath);
});
