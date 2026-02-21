import { useState, useRef } from 'react'
import {
  View, Text, TouchableOpacity, Animated,
  LayoutAnimation, Platform, UIManager, StyleSheet,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { colors, font, spacing, radius } from '../theme'

// Enable LayoutAnimation on Android
if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true)
}

function AccordionItem({ title, content }) {
  const [open, setOpen] = useState(false)
  const rotateAnim = useRef(new Animated.Value(0)).current

  const toggle = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut)
    Animated.timing(rotateAnim, {
      toValue: open ? 0 : 1,
      duration: 220,
      useNativeDriver: true,
    }).start()
    setOpen(!open)
  }

  const rotate = rotateAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '180deg'],
  })

  return (
    <View style={styles.item}>
      <TouchableOpacity
        style={styles.trigger}
        onPress={toggle}
        activeOpacity={0.7}
      >
        <Text style={styles.triggerText}>{title}</Text>
        <Animated.View style={{ transform: [{ rotate }] }}>
          <Ionicons name="chevron-down" size={16} color={colors.textMuted} />
        </Animated.View>
      </TouchableOpacity>

      {open && (
        <View style={styles.body}>
          <Text style={styles.bodyText}>{content}</Text>
        </View>
      )}
    </View>
  )
}

export default function SectionAccordion({ sections = {} }) {
  const entries = Object.entries(sections)
  if (!entries.length) return null

  return (
    <View style={styles.container}>
      {entries.map(([key, text], i) => (
        <View key={key}>
          <AccordionItem
            title={key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
            content={text}
          />
          {i < entries.length - 1 && <View style={styles.divider} />}
        </View>
      ))}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    borderRadius: radius.lg,
    overflow: 'hidden',
  },
  item: {},
  trigger: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.md + 2,
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.surface,
  },
  triggerText: {
    flex: 1,
    fontSize: font.sm,
    fontWeight: '600',
    color: colors.primary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginRight: spacing.sm,
  },
  body: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md + 2,
    backgroundColor: colors.surface,
  },
  bodyText: {
    fontSize: font.sm,
    color: colors.textPrimary,
    lineHeight: 21,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginHorizontal: spacing.lg,
  },
})
