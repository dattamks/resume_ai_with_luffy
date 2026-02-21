import { useEffect, useRef } from 'react'
import { View, Text, Animated, StyleSheet } from 'react-native'
import { colors, font, spacing } from '../theme'

const STATUS_CONFIG = {
  done: { color: colors.success, label: 'Done' },
  processing: { color: '#3b82f6', label: 'Processing' },
  pending: { color: colors.textMuted, label: 'Pending' },
  failed: { color: colors.error, label: 'Failed' },
}

export default function StatusDot({ status = 'pending' }) {
  const pulse = useRef(new Animated.Value(1)).current
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.pending

  useEffect(() => {
    if (status !== 'processing') return
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 0.3, duration: 700, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: true }),
      ])
    )
    loop.start()
    return () => loop.stop()
  }, [status])

  return (
    <View style={styles.container}>
      <Animated.View
        style={[styles.dot, { backgroundColor: config.color, opacity: pulse }]}
      />
      <Text style={[styles.label, { color: config.color }]}>{config.label}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 99,
  },
  label: {
    fontSize: font.xs,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
})
