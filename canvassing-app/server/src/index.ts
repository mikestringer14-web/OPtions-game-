import "dotenv/config";
import express from "express";
import cors from "cors";
import { housesRouter } from "./routes/houses";
import { visitsRouter } from "./routes/visits";
import { sessionsRouter } from "./routes/sessions";
import { reportsRouter } from "./routes/reports";
import { areasRouter } from "./routes/areas";

const app = express();
app.use(cors());
app.use(express.json());

// All routes require the shared API key the mobile app sends as
// `x-api-key`. This is a simple shared-secret, not per-user auth - the PIN
// check in sessions.ts is what identifies the actual employee.
app.use((req, res, next) => {
  if (req.path === "/health") return next();
  const key = req.header("x-api-key");
  if (!key || key !== process.env.API_KEY) {
    return res.status(401).json({ error: "Missing or invalid x-api-key" });
  }
  next();
});

app.get("/health", (_req, res) => res.json({ ok: true }));
app.use("/api/houses", housesRouter);
app.use("/api/visits", visitsRouter);
app.use("/api/sessions", sessionsRouter);
app.use("/api/reports", reportsRouter);
app.use("/api/areas", areasRouter);

const port = Number(process.env.PORT ?? 4000);
app.listen(port, () => {
  console.log(`Canvassing tracker API listening on :${port}`);
});
