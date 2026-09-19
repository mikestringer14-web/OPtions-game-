import { LatLng, haversineMeters, isPointInPolygon } from "./geo";
import { DRIVING_SPEED_THRESHOLD_KMH, DRIVING_CONFIRM_SAMPLES } from "../config";

/**
 * Privacy auto-shutoff: tracks consecutive location samples that are BOTH
 * (a) moving faster than walking/porch-to-porch pace and (b) outside the
 * canvass area boundary. Only when both hold for DRIVING_CONFIRM_SAMPLES
 * in a row does it report "confirmed" - a single fast GPS glitch, or
 * driving fast while still technically inside a large polygon (e.g. a rural
 * route), won't trip it.
 *
 * This intentionally does NOT use distance-from-center or a timer alone:
 * the point is "left the neighborhood in a car", not "stopped moving" or
 * "far from the first house", so both speed and boundary-exit are required.
 */
export class DrivingAwayDetector {
  private consecutiveHits = 0;

  constructor(private boundary: number[][]) {}

  /** @param speedMps from CLLocation/Android FusedLocation speed, meters/sec */
  sample(point: LatLng, speedMps: number | null | undefined): { confirmed: boolean } {
    const speedKmh = (speedMps ?? 0) * 3.6;
    const outsideArea = !isPointInPolygon(point, this.boundary);
    const isDriving = speedKmh >= DRIVING_SPEED_THRESHOLD_KMH;

    if (isDriving && outsideArea) {
      this.consecutiveHits += 1;
    } else {
      this.consecutiveHits = 0;
    }

    return { confirmed: this.consecutiveHits >= DRIVING_CONFIRM_SAMPLES };
  }

  reset() {
    this.consecutiveHits = 0;
  }
}

/** Straight-line distance check, used as a cheap first-pass filter before
 * the more expensive polygon test when the area boundary is large. */
export function isFarFromPoint(point: LatLng, center: LatLng, radiusM: number): boolean {
  return haversineMeters(point, center) > radiusM;
}
