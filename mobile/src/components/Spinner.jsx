import { View, ActivityIndicator, StyleSheet } from 'react-native'
import { colors } from '../theme'

export default function Spinner({ size = 'large', overlay = false }) {
  return (
    <View style={[styles.container, overlay && styles.overlay]}>
      <ActivityIndicator size={size} color={colors.primary} />
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(248,250,252,0.85)',
    zIndex: 99,
  },
})
