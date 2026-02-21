import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { createNativeStackNavigator } from '@react-navigation/native-stack'
import { Ionicons } from '@expo/vector-icons'
import { Platform } from 'react-native'
import { colors, shadow } from '../theme'

import AnalyzeScreen from '../screens/AnalyzeScreen'
import ResultsScreen from '../screens/ResultsScreen'
import HistoryScreen from '../screens/HistoryScreen'
import AccountScreen from '../screens/AccountScreen'

const Tab = createBottomTabNavigator()
const AnalyzeStack = createNativeStackNavigator()
const HistoryStack = createNativeStackNavigator()

function AnalyzeNavigator() {
  return (
    <AnalyzeStack.Navigator screenOptions={{ headerShown: false }}>
      <AnalyzeStack.Screen name="AnalyzeMain" component={AnalyzeScreen} />
      <AnalyzeStack.Screen
        name="Results"
        component={ResultsScreen}
        options={{ animation: 'slide_from_right' }}
      />
    </AnalyzeStack.Navigator>
  )
}

function HistoryNavigator() {
  return (
    <HistoryStack.Navigator screenOptions={{ headerShown: false }}>
      <HistoryStack.Screen name="HistoryMain" component={HistoryScreen} />
      <HistoryStack.Screen
        name="Results"
        component={ResultsScreen}
        options={{ animation: 'slide_from_right' }}
      />
    </HistoryStack.Navigator>
  )
}

export default function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarIcon: ({ focused, color, size }) => {
          const icons = {
            Analyze: focused ? 'document-text' : 'document-text-outline',
            History: focused ? 'time' : 'time-outline',
            Account: focused ? 'person-circle' : 'person-circle-outline',
          }
          return <Ionicons name={icons[route.name]} size={size} color={color} />
        },
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          borderTopWidth: 1,
          height: Platform.OS === 'ios' ? 84 : 64,
          paddingBottom: Platform.OS === 'ios' ? 24 : 10,
          paddingTop: 8,
          ...shadow.sm,
        },
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: '600',
        },
      })}
    >
      <Tab.Screen name="Analyze" component={AnalyzeNavigator} />
      <Tab.Screen name="History" component={HistoryNavigator} />
      <Tab.Screen name="Account" component={AccountScreen} />
    </Tab.Navigator>
  )
}
