import React, { useEffect, useState } from "react";
import { View, StyleSheet, Pressable, Text } from "react-native";
import MapView from "react-native-maps";
import { useAppStore } from "../state/store";
import { HouseMarker } from "../components/HouseMarker";
import { QuickActionModal } from "../components/QuickActionModal";
import { api } from "../api/client";
import { syncHouses } from "../services/locationTracking";
import { House } from "../types";

export function CanvassMapScreen({ navigation }: any) {
  const houses = useAppStore((s) => s.houses);
  const setHouses = useAppStore((s) => s.setHouses);
  const areaId = useAppStore((s) => s.areaId);
  const [selected, setSelected] = useState<House | null>(null);

  useEffect(() => {
    if (!areaId) return;
    const interval = setInterval(async () => {
      const updated = await api.getHouses(areaId);
      setHouses(updated);
      syncHouses(updated);
    }, 20000);
    return () => clearInterval(interval);
  }, [areaId]);

  const region = houses.length
    ? {
        latitude: houses[0].lat,
        longitude: houses[0].lng,
        latitudeDelta: 0.01,
        longitudeDelta: 0.01,
      }
    : undefined;

  return (
    <View style={{ flex: 1 }}>
      <MapView style={StyleSheet.absoluteFill} initialRegion={region} showsUserLocation followsUserLocation>
        {houses.map((h) => (
          <HouseMarker key={h.id} house={h} onPress={setSelected} />
        ))}
      </MapView>

      {selected && (
        <View style={styles.infoCard}>
          <Text style={styles.infoTitle}>{selected.address}</Text>
          <Text style={styles.infoStatus}>{selected.status ?? "Not visited yet"}</Text>
          <Pressable onPress={() => setSelected(null)}>
            <Text style={styles.close}>Close</Text>
          </Pressable>
        </View>
      )}

      <Pressable style={styles.settingsBtn} onPress={() => navigation.navigate("Settings")}>
        <Text style={styles.settingsBtnText}>Menu</Text>
      </Pressable>

      <QuickActionModal />
    </View>
  );
}

const styles = StyleSheet.create({
  infoCard: {
    position: "absolute",
    bottom: 30,
    left: 16,
    right: 16,
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 16,
    elevation: 4,
  },
  infoTitle: { fontWeight: "700", fontSize: 16 },
  infoStatus: { color: "#666", marginTop: 4, marginBottom: 8 },
  close: { color: "#3B82F6", fontWeight: "600" },
  settingsBtn: {
    position: "absolute",
    top: 50,
    right: 16,
    backgroundColor: "#111827",
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
  },
  settingsBtnText: { color: "#fff", fontWeight: "600" },
});
