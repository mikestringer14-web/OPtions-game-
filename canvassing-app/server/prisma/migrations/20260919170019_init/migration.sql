-- CreateTable
CREATE TABLE "Employee" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "pinCode" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'CANVASSER',
    "active" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "CanvassArea" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "boundaryGeoJson" TEXT NOT NULL,
    "managerEmails" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "House" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "areaId" TEXT NOT NULL,
    "address" TEXT NOT NULL,
    "lat" REAL NOT NULL,
    "lng" REAL NOT NULL,
    "footprintGeoJson" TEXT,
    "status" TEXT,
    "lastVisitedAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "House_areaId_fkey" FOREIGN KEY ("areaId") REFERENCES "CanvassArea" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Visit" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "houseId" TEXT NOT NULL,
    "employeeId" TEXT NOT NULL,
    "outcome" TEXT NOT NULL,
    "notes" TEXT,
    "lat" REAL NOT NULL,
    "lng" REAL NOT NULL,
    "timestamp" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Visit_houseId_fkey" FOREIGN KEY ("houseId") REFERENCES "House" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "Visit_employeeId_fkey" FOREIGN KEY ("employeeId") REFERENCES "Employee" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "WorkSession" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "employeeId" TEXT NOT NULL,
    "areaId" TEXT NOT NULL,
    "clockInAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "clockOutAt" DATETIME,
    "autoPausedAt" DATETIME,
    CONSTRAINT "WorkSession_employeeId_fkey" FOREIGN KEY ("employeeId") REFERENCES "Employee" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "WorkSession_areaId_fkey" FOREIGN KEY ("areaId") REFERENCES "CanvassArea" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "TrackPoint" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "sessionId" TEXT NOT NULL,
    "lat" REAL NOT NULL,
    "lng" REAL NOT NULL,
    "speedMps" REAL,
    "timestamp" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "TrackPoint_sessionId_fkey" FOREIGN KEY ("sessionId") REFERENCES "WorkSession" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "DailyReport" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "areaId" TEXT NOT NULL,
    "date" TEXT NOT NULL,
    "pdfPath" TEXT NOT NULL,
    "recipients" TEXT NOT NULL,
    "emailedAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateIndex
CREATE UNIQUE INDEX "Employee_email_key" ON "Employee"("email");

-- CreateIndex
CREATE INDEX "House_areaId_idx" ON "House"("areaId");

-- CreateIndex
CREATE INDEX "Visit_houseId_idx" ON "Visit"("houseId");

-- CreateIndex
CREATE INDEX "Visit_employeeId_idx" ON "Visit"("employeeId");

-- CreateIndex
CREATE INDEX "WorkSession_employeeId_idx" ON "WorkSession"("employeeId");

-- CreateIndex
CREATE INDEX "WorkSession_areaId_idx" ON "WorkSession"("areaId");

-- CreateIndex
CREATE INDEX "TrackPoint_sessionId_idx" ON "TrackPoint"("sessionId");

-- CreateIndex
CREATE UNIQUE INDEX "DailyReport_areaId_date_key" ON "DailyReport"("areaId", "date");
