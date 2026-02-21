import { View } from 'react-native'
import { NavigationContainer } from '@react-navigation/native'
import { useAuth } from '../context/AuthContext'
import AuthStack from './AuthStack'
import MainTabs from './MainTabs'
import Spinner from '../components/Spinner'
import { colors } from '../theme'

export default function AppNavigator() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <Spinner />
      </View>
    )
  }

  return (
    <NavigationContainer>
      {user ? <MainTabs /> : <AuthStack />}
    </NavigationContainer>
  )
}
