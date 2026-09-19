// Small geometry helpers used for the two privacy/UX features that need
// "is this point inside/near that shape" math: the per-house exit prompt
// and the leave-the-neighborhood auto-pause.

export type LatLng = { lat: number; lng: number };

const EARTH_RADIUS_M = 6371000;

export function haversineMeters(a: LatLng, b: LatLng): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);

  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

// Ray-casting point-in-polygon. `polygon` is [[lng,lat], ...] (GeoJSON order).
export function isPointInPolygon(point: LatLng, polygon: number[][]): boolean {
  const x = point.lng;
  const y = point.lat;
  let inside = false;

  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0];
    const yi = polygon[i][1];
    const xj = polygon[j][0];
    const yj = polygon[j][1];

    const intersects =
      yi > y !== yj > y &&
      x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

// Builds a rough square footprint (~9m per side) around a house's lat/lng
// when no real building outline is on file. Real outlines should come from
// OpenStreetMap building polygons (Overpass API, free) or Google Maps
// Building Insights (paid) - see README "House outlines" section for how
// to populate `footprintGeoJson` on the House model instead of using this.
export function generateFallbackFootprint(center: LatLng, sizeMeters = 9): number[][] {
  const half = sizeMeters / 2;
  const dLat = half / 111320; // meters per degree latitude, ~constant
  const dLng = half / (111320 * Math.cos((center.lat * Math.PI) / 180));

  return [
    [center.lng - dLng, center.lat - dLat],
    [center.lng + dLng, center.lat - dLat],
    [center.lng + dLng, center.lat + dLat],
    [center.lng - dLng, center.lat + dLat],
    [center.lng - dLng, center.lat - dLat],
  ];
}
