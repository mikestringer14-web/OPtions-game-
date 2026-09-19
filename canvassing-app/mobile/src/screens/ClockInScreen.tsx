import React, { useState } from "react";
import { View, Text, TextInput, Pressable, StyleSheet, Alert } from "react-native";
import { useAppStore } from "../state/store";
import { api } from "../api/client";
import { requestPermissions, startTracking } from "../services/locationTracking";

/**
 * Minimal clock-in: employee ID + PIN + which area they're canvassing
 * today. Kept deliberately low-friction since this runs on a shared or
 * personal phone at the start of a shift, standing on a driveway.
 */
export function ClockInScreen({ navigation }: any) {
  const [employeeId, setEmployeeId] = useState("");
  const [pinCode, setPinCode] = useState("");
  const [areaId, setAreaId] = useState("");
  const [loading, setLoading] = useState(false);

  const setEmployeeAndArea = useAppStore((s) => s.setEmployeeAndArea);
  const setSession = useAppStore((s) => s.setSession);
  const setHouses = useAppStore((s) => s.setHouses);

  async function handleClockIn() {
    setLoading(true);
    try {
      const granted = await requestPermissions();
      if (!granted) {
        Alert.alert(
          "Location permission required",
          "Tracking needs \"Always\" location access to work while your phone is locked or the app is backgrounded. Enable it in Settings > Canvassing Tracker > Location."
        );
        setLoading(false);
        return;
      }

      const session = await api.clockIn(employeeId, pinCode, areaId);
      const [houses, area] = await Promise.all([api.getHouses(areaId), api.getArea(areaId)]);

      setEmployeeAndArea({ id: employeeId, name: "", email: "", role: "CANVASSER" }, areaId);
      setSession(session);
      setHouses(houses);

      await startTracking({
        sessionId: session.id,
        employeeId,
        areaBoundaryGeoJson: area.boundaryGeoJson,
        houses,
        onAutoPause: () => {
          api.autoPause(session.id).catch(() => {});
          Alert.alert(
            "Tracking paused",
            "Looks like you left the neighborhood at driving speed, so location tracking was automatically turned off for your privacy. Clock out from Settings if your shift is actually done."
          );
        },
      });

      navigation.replace("Map");
    } catch (err: any) {
      Alert.alert("Clock-in failed", err.message ?? String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Clock In</Text>
      <TextInput
        style={styles.input}
        placeholder="Employee ID"
        value={employeeId}
        onChangeText={setEmployeeId}
        autoCapitalize="none"
      />
      <TextInput
        style={styles.input}
        placeholder="PIN"
        value={pinCode}
        onChangeText={setPinCode}
        secureTextEntry
        keyboardType="number-pad"
      />
      <TextInput
        style={styles.input}
        placeholder="Area ID (today's route)"
        value={areaId}
        onChangeText={setAreaId}
        autoCapitalize="none"
      />
      <Pressable style={styles.button} onPress={handleClockIn} disabled={loading}>
        <Text style={styles.buttonText}>{loading ? "Clocking in..." : "Clock In & Start Tracking"}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: "center", padding: 24, backgroundColor: "#111827" },
  title: { fontSize: 28, fontWeight: "800", color: "#fff", marginBottom: 24 },
  input: {
    backgroundColor: "#1F2937",
    color: "#fff",
    padding: 14,
    borderRadius: 10,
    marginBottom: 12,
    fontSize: 16,
  },
  button: { backgroundColor: "#22C55E", padding: 16, borderRadius: 10, marginTop: 12 },
  buttonText: { color: "#fff", fontWeight: "700", textAlign: "center", fontSize: 16 },
});
