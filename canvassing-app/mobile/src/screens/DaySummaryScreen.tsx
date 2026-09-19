import React, { useMemo } from "react";
import { View, Text, FlatList, StyleSheet } from "react-native";
import { useAppStore } from "../state/store";
import { OUTCOME_LABELS, OUTCOME_COLORS, VisitOutcome } from "../types";

/**
 * On-device end-of-day view: how many houses landed in each outcome
 * bucket today. The authoritative, shareable version of this is the PDF
 * the backend emails to management (server/src/services/pdfReport.ts) -
 * this screen is just a quick "did I cover the street" check for the
 * canvasser themselves before they clock out.
 */
export function DaySummaryScreen() {
  const houses = useAppStore((s) => s.houses);

  const counts = useMemo(() => {
    const c: Partial<Record<VisitOutcome, number>> = {};
    let untouched = 0;
    for (const h of houses) {
      if (h.status) c[h.status] = (c[h.status] ?? 0) + 1;
      else untouched += 1;
    }
    return { c, untouched };
  }, [houses]);

  const rows = (Object.keys(counts.c) as VisitOutcome[]).map((outcome) => ({
    outcome,
    count: counts.c[outcome] ?? 0,
  }));

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Today's Summary</Text>
      <FlatList
        data={rows}
        keyExtractor={(r) => r.outcome}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <View style={[styles.dot, { backgroundColor: OUTCOME_COLORS[item.outcome] }]} />
            <Text style={styles.rowLabel}>{OUTCOME_LABELS[item.outcome]}</Text>
            <Text style={styles.rowCount}>{item.count}</Text>
          </View>
        )}
        ListFooterComponent={
          <View style={styles.row}>
            <View style={[styles.dot, { backgroundColor: "#D1D5DB" }]} />
            <Text style={styles.rowLabel}>Not visited yet</Text>
            <Text style={styles.rowCount}>{counts.untouched}</Text>
          </View>
        }
      />
      <Text style={styles.footnote}>
        The full report with addresses, times, and canvassers gets emailed to management automatically at
        clock-out.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, backgroundColor: "#fff" },
  title: { fontSize: 22, fontWeight: "800", marginBottom: 16 },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 10 },
  dot: { width: 12, height: 12, borderRadius: 6, marginRight: 10 },
  rowLabel: { flex: 1, fontSize: 15 },
  rowCount: { fontSize: 15, fontWeight: "700" },
  footnote: { marginTop: 20, color: "#888", fontSize: 12 },
});
