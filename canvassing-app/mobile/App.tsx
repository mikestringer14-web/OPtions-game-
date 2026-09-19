import React from "react";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { StatusBar } from "expo-status-bar";
import { ClockInScreen } from "./src/screens/ClockInScreen";
import { CanvassMapScreen } from "./src/screens/CanvassMapScreen";
import { DaySummaryScreen } from "./src/screens/DaySummaryScreen";
import { SettingsScreen } from "./src/screens/SettingsScreen";

const Stack = createNativeStackNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <StatusBar style="light" />
      <Stack.Navigator initialRouteName="ClockIn" screenOptions={{ headerShown: false }}>
        <Stack.Screen name="ClockIn" component={ClockInScreen} />
        <Stack.Screen name="Map" component={CanvassMapScreen} />
        <Stack.Screen name="DaySummary" component={DaySummaryScreen} options={{ headerShown: true, title: "Summary" }} />
        <Stack.Screen name="Settings" component={SettingsScreen} options={{ headerShown: true, title: "Menu" }} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
