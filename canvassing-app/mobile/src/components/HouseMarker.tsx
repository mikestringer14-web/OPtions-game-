import React from "react";
import { Marker, Polygon } from "react-native-maps";
import { House, OUTCOME_COLORS } from "../types";

/**
 * Renders one house as a 2D outline on the map: the building footprint
 * polygon (real, from OSM/Google Building Insights, or the server's
 * generated fallback square - see server/src/services/geofence.ts) filled
 * with the color of its current status, plus a small pin for tapping.
 */
export function HouseMarker({ house, onPress }: { house: House; onPress: (house: House) => void }) {
  const color = house.status ? OUTCOME_COLORS[house.status] : "#D1D5DB";
  let coords: { latitude: number; longitude: number }[] = [];
  try {
    const raw: number[][] = JSON.parse(house.footprintGeoJson);
    coords = raw.map(([lng, lat]) => ({ latitude: lat, longitude: lng }));
  } catch {
    coords = [];
  }

  return (
    <>
      {coords.length > 0 && (
        <Polygon
          coordinates={coords}
          fillColor={`${color}AA`}
          strokeColor={color}
          strokeWidth={2}
          tappable
          onPress={() => onPress(house)}
        />
      )}
      <Marker
        coordinate={{ latitude: house.lat, longitude: house.lng }}
        pinColor={color}
        onPress={() => onPress(house)}
      />
    </>
  );
}
