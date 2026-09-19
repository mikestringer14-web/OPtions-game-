import nodemailer from "nodemailer";
import fs from "fs";

/**
 * Sends the daily report PDF to the area's manager list. Reads SMTP
 * credentials from env - see server/.env.example. Until those are filled
 * in with real values this will throw, which callers should catch and log
 * rather than crash the request (a failed email shouldn't lose the report;
 * it's still on disk in server/reports/).
 */
export async function emailDailyReport(opts: {
  toEmails: string[];
  areaName: string;
  date: string;
  pdfPath: string;
}) {
  const { toEmails, areaName, date, pdfPath } = opts;

  const missing = ["SMTP_HOST", "SMTP_USER", "SMTP_PASS"].filter((k) => !process.env[k]);
  if (missing.length) {
    throw new Error(
      `Email not configured - missing env vars: ${missing.join(", ")}. See server/.env.example.`
    );
  }

  const transporter = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT ?? 465),
    secure: process.env.SMTP_SECURE !== "false",
    auth: {
      user: process.env.SMTP_USER,
      pass: process.env.SMTP_PASS,
    },
    // Without these, an unreachable host or a provider silently rejecting
    // placeholder creds hangs the request indefinitely instead of failing
    // fast - which would otherwise hang the /reports/.../send endpoint.
    connectionTimeout: 10000,
    greetingTimeout: 10000,
    socketTimeout: 10000,
  });

  await transporter.sendMail({
    from: `"${process.env.REPORT_FROM_NAME ?? "Canvassing Tracker"}" <${process.env.SMTP_USER}>`,
    to: toEmails.join(","),
    subject: `Canvassing Report - ${areaName} - ${date}`,
    text: `Attached: house-by-house canvassing results for ${areaName} on ${date}.`,
    attachments: [
      {
        filename: `${areaName.replace(/\s+/g, "_")}_${date}.pdf`,
        content: fs.createReadStream(pdfPath),
      },
    ],
  });
}
