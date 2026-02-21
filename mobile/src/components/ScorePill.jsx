import { View, Text, StyleSheet } from 'react-native'
import { colors, font, radius } from '../theme'

export default function ScorePill({ score }) {
  if (score == null) {
    return <Text style={styles.dash}>—</Text>
  }

  const isHigh = score >= 75
  const isMid = score >= 50
  const bg = isHigh ? colors.successLight : isMid ? colors.warningLight : colors.errorLight
  const textColor = isHigh ? '#15803d' : isMid ? '#b45309' : colors.error

  return (
    <View style={[styles.pill, { backgroundColor: bg }]}>
      <Text style={[styles.text, { color: textColor }]}>{score}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  pill: {
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: radius.full,
  },
  text: {
    fontSize: font.xs,
    fontWeight: '700',
  },
  dash: {
    fontSize: font.sm,
    color: colors.textMuted,
  },
})
