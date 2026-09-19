import React from "react";
import { View, Text, Pressable, StyleSheet, Alert } from "react-native";
import { useAppStore } from "../state/store";
import { api } from "../api/client";
import { stopTracking } from "../services/locationTracking";

export function SettingsScreen({ navigation }: any) {
  const session = useAppStore((s) => s.session);
  const setSession = useAppStore((s) => s.setSession);

  async function handleClockOut() {
    if (!session) return;
    try {
      await stopTracking();
      await api.clockOut(session.id);
      setSession(null);
      Alert.alert("Clocked out", "Tracking stopped. Today's report will be emailed to management.");
      navigation.replace("ClockIn");
    } catch (err: any) {
      Alert.alert("Clock-out failed", err.message ?? String(err));
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Menu</Text>
      <Pressable style={styles.item} onPress={() => navigation.navigate("DaySummary")}>
        <Text style={styles.itemText}>Today's Summary</Text>
      </Pressable>
      <Pressable style={[styles.item, styles.danger]} onPress={handleClockOut}>
        <Text style={styles.itemText}>Clock Out & Stop Tracking</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, backgroundColor: "#fff" },
  title: { fontSize: 22, fontWeight: "800", marginBottom: 24 },
  item: { backgroundColor: "#F3F4F6", padding: 16, borderRadius: 10, marginBottom: 12 },
  danger: { backgroundColor: "#FEE2E2" },
  itemText: { fontSize: 16, fontWeight: "600" },
});
