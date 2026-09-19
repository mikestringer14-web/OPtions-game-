import React, { useState } from "react";
import { Modal, View, Text, Pressable, StyleSheet } from "react-native";
import * as Location from "expo-location";
import { useAppStore } from "../state/store";
import { api } from "../api/client";
import { PRIMARY_OUTCOMES, SECONDARY_OUTCOMES, OUTCOME_LABELS, OUTCOME_COLORS, VisitOutcome } from "../types";

/**
 * The "quick-2-click" prompt: pops up automatically when the geofence
 * watcher decides you've left a house (see locationTracking.ts). Tap 1 =
 * pick an outcome (or "More" to reveal the other 4). Tap 2 only needed for
 * the secondary sheet. Auto-dismisses the instant a choice is logged.
 */
export function QuickActionModal() {
  const promptTarget = useAppStore((s) => s.promptTarget);
  const employee = useAppStore((s) => s.employee);
  const closePrompt = useAppStore((s) => s.closePrompt);
  const updateHouseStatus = useAppStore((s) => s.updateHouseStatus);
  const [showMore, setShowMore] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  if (!promptTarget || !employee) return null;
  const { house } = promptTarget;

  async function logOutcome(outcome: VisitOutcome) {
    setSubmitting(true);
    try {
      const pos = await Location.getLastKnownPositionAsync();
      await api.logVisit({
        houseId: house.id,
        employeeId: employee!.id,
        outcome,
        lat: pos?.coords.latitude ?? house.lat,
        lng: pos?.coords.longitude ?? house.lng,
      });
      updateHouseStatus(house.id, outcome);
    } catch {
      // Keep it queued client-side would be a real offline-sync layer;
      // for now surface nothing and let the canvasser re-tap if it failed,
      // since the sheet stays open on error (see finally below only closes
      // on success).
      setSubmitting(false);
      return;
    }
    setSubmitting(false);
    setShowMore(false);
    closePrompt();
  }

  const options = showMore ? SECONDARY_OUTCOMES : PRIMARY_OUTCOMES;

  return (
    <Modal transparent animationType="slide" visible>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <Text style={styles.address}>{house.address}</Text>
          <Text style={styles.subtitle}>What happened at this house?</Text>

          <View style={styles.grid}>
            {options.map((outcome) => (
              <Pressable
                key={outcome}
                disabled={submitting}
                onPress={() => logOutcome(outcome)}
                style={[styles.tile, { backgroundColor: OUTCOME_COLORS[outcome] }]}
              >
                <Text style={styles.tileText}>{OUTCOME_LABELS[outcome]}</Text>
              </Pressable>
            ))}
          </View>

          <View style={styles.footerRow}>
            <Pressable onPress={() => setShowMore((v) => !v)} style={styles.linkBtn}>
              <Text style={styles.linkText}>{showMore ? "Back" : "More options"}</Text>
            </Pressable>
            <Pressable onPress={closePrompt} style={styles.linkBtn}>
              <Text style={styles.linkText}>Dismiss</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  sheet: { backgroundColor: "#fff", borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20 },
  address: { fontSize: 18, fontWeight: "700" },
  subtitle: { fontSize: 14, color: "#666", marginBottom: 16 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  tile: {
    width: "47%",
    paddingVertical: 22,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  tileText: { color: "#fff", fontWeight: "700", fontSize: 15, textAlign: "center" },
  footerRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 18 },
  linkBtn: { padding: 8 },
  linkText: { color: "#3B82F6", fontWeight: "600" },
});
