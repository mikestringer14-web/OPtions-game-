// Quick dev seed: one canvass area with a small polygon boundary, one
// manager, one canvasser, and a handful of houses. Run with `npm run seed`
// after `npm run prisma:migrate`.
import "dotenv/config";
import { prisma } from "./db";

async function main() {
  const area = await prisma.canvassArea.create({
    data: {
      name: "Maple Street Test Route",
      // Replace with the real neighborhood boundary before going live -
      // draw one at https://geojson.io and paste the polygon coordinates.
      boundaryGeoJson: JSON.stringify([
        [-79.805, 43.325],
        [-79.795, 43.325],
        [-79.795, 43.318],
        [-79.805, 43.318],
        [-79.805, 43.325],
      ]),
      managerEmails: "manager@example.com",
    },
  });

  await prisma.employee.create({
    data: { name: "Sample Canvasser", email: "canvasser@example.com", pinCode: "1234" },
  });
  await prisma.employee.create({
    data: { name: "Sample Manager", email: "manager@example.com", pinCode: "9999", role: "MANAGER" },
  });

  const addresses = [
    { address: "101 Maple St", lat: 43.3235, lng: -79.8025 },
    { address: "103 Maple St", lat: 43.3237, lng: -79.8023 },
    { address: "105 Maple St", lat: 43.3239, lng: -79.8021 },
  ];
  for (const a of addresses) {
    await prisma.house.create({ data: { areaId: area.id, ...a } });
  }

  console.log(`Seeded area ${area.id} with ${addresses.length} houses.`);
}

main().finally(() => prisma.$disconnect());
