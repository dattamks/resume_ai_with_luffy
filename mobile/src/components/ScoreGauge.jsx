import { useEffect, useRef } from 'react'
import { View, Text, Animated, StyleSheet } from 'react-native'
import Svg, { Circle } from 'react-native-svg'
import { colors, font } from '../theme'

const AnimatedCircle = Animated.createAnimatedComponent(Circle)

const SIZE = 160
const RADIUS = 60
const STROKE = 13
const CIRCUMFERENCE = 2 * Math.PI * RADIUS
const CENTER = SIZE / 2

function getScoreColor(score) {
  if (score >= 75) return colors.success
  if (score >= 50) return colors.warning
  return colors.error
}

function getScoreLabel(score) {
  if (score >= 75) return 'Strong match'
  if (score >= 50) return 'Moderate match'
  return 'Needs work'
}

export default function ScoreGauge({ score = 0, light = false }) {
  const animated = useRef(new Animated.Value(0)).current

  useEffect(() => {
    Animated.timing(animated, {
      toValue: score,
      duration: 1300,
      delay: 200,
      useNativeDriver: false,
    }).start()
  }, [score])

  const strokeDashoffset = animated.interpolate({
    inputRange: [0, 100],
    outputRange: [CIRCUMFERENCE, 0],
  })

  const color = getScoreColor(score)
  const label = getScoreLabel(score)
  const trackColor = light ? 'rgba(255,255,255,0.25)' : '#e2e8f0'
  const textColor = light ? colors.surface : colors.textPrimary
  const subColor = light ? 'rgba(255,255,255,0.7)' : colors.textMuted
  const labelBg = light ? 'rgba(255,255,255,0.18)' : `${color}18`

  return (
    <View style={styles.container}>
      <Svg width={SIZE} height={SIZE}>
        {/* Track */}
        <Circle
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke={trackColor}
          strokeWidth={STROKE}
        />
        {/* Progress */}
        <AnimatedCircle
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke={color}
          strokeWidth={STROKE}
          strokeDasharray={`${CIRCUMFERENCE} ${CIRCUMFERENCE}`}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          transform={`rotate(-90, ${CENTER}, ${CENTER})`}
        />
      </Svg>

      {/* Center text overlay */}
      <View style={styles.overlay}>
        <Text style={[styles.score, { color: textColor }]}>{score}</Text>
        <Text style={[styles.outOf, { color: subColor }]}>/100</Text>
      </View>

      {/* Label badge below */}
      <View style={[styles.labelBadge, { backgroundColor: labelBg }]}>
        <Text style={[styles.labelText, { color: light ? colors.surface : color }]}>
          {label}
        </Text>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
  },
  overlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: SIZE,
    height: SIZE,
    alignItems: 'center',
    justifyContent: 'center',
  },
  score: {
    fontSize: font.xxxl,
    fontWeight: '800',
    letterSpacing: -1,
    lineHeight: 34,
  },
  outOf: {
    fontSize: font.sm,
    fontWeight: '500',
  },
  labelBadge: {
    marginTop: 10,
    paddingHorizontal: 14,
    paddingVertical: 5,
    borderRadius: 99,
  },
  labelText: {
    fontSize: font.xs,
    fontWeight: '700',
    letterSpacing: 0.3,
    textTransform: 'uppercase',
  },
})
