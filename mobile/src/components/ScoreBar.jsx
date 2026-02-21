import { useEffect, useRef } from 'react'
import { View, Text, Animated, StyleSheet } from 'react-native'
import { colors, font, spacing, radius } from '../theme'

function getBarColor(value) {
  if (value >= 75) return colors.success
  if (value >= 50) return colors.warning
  return colors.error
}

export default function ScoreBar({ label, value = 0 }) {
  const animated = useRef(new Animated.Value(0)).current

  useEffect(() => {
    Animated.timing(animated, {
      toValue: value,
      duration: 1000,
      delay: 300,
      useNativeDriver: false,
    }).start()
  }, [value])

  const widthPercent = animated.interpolate({
    inputRange: [0, 100],
    outputRange: ['0%', '100%'],
  })

  const color = getBarColor(value)

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.label}>{label}</Text>
        <Text style={[styles.value, { color }]}>{value}</Text>
      </View>
      <View style={styles.track}>
        <Animated.View
          style={[styles.fill, { width: widthPercent, backgroundColor: color }]}
        />
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    marginBottom: spacing.md,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  label: {
    fontSize: font.sm,
    color: colors.textSecondary,
    fontWeight: '500',
  },
  value: {
    fontSize: font.sm,
    fontWeight: '700',
  },
  track: {
    height: 8,
    backgroundColor: '#f1f5f9',
    borderRadius: radius.full,
    overflow: 'hidden',
  },
  fill: {
    height: '100%',
    borderRadius: radius.full,
  },
})
