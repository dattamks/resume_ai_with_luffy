import { useState, useEffect } from 'react'
import {
  View, Text, StyleSheet, TouchableOpacity, Alert, ScrollView,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import * as Haptics from 'expo-haptics'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { colors, shadow, radius, spacing, font } from '../theme'

function MenuItem({ icon, label, value, color, onPress, danger }) {
  return (
    <TouchableOpacity
      style={styles.menuItem}
      onPress={onPress}
      activeOpacity={0.75}
      disabled={!onPress}
    >
      <View style={[styles.menuIconWrap, danger && styles.menuIconDanger]}>
        <Ionicons name={icon} size={18} color={danger ? colors.error : (color || colors.primary)} />
      </View>
      <Text style={[styles.menuLabel, danger && styles.menuLabelDanger]}>{label}</Text>
      {value ? <Text style={styles.menuValue}>{value}</Text> : null}
      {onPress && !danger ? (
        <Ionicons name="chevron-forward" size={16} color={colors.textMuted} />
      ) : null}
    </TouchableOpacity>
  )
}

export default function AccountScreen() {
  const { user, logout } = useAuth()
  const [stats, setStats] = useState({ total: 0, best: null, avg: null })

  useEffect(() => {
    api.get('/analyses/').then(({ data }) => {
      const list = Array.isArray(data) ? data : data.results ?? []
      const done = list.filter((a) => a.status === 'done' && a.ats_score != null)
      const best = done.length > 0 ? Math.max(...done.map((a) => a.ats_score)) : null
      const avg =
        done.length > 0
          ? Math.round(done.reduce((s, a) => s + a.ats_score, 0) / done.length)
          : null
      setStats({ total: list.length, best, avg })
    }).catch(() => {})
  }, [])

  const handleLogout = () => {
    Alert.alert(
      'Sign Out',
      'Are you sure you want to sign out?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Sign Out',
          style: 'destructive',
          onPress: async () => {
            await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning)
            await logout()
          },
        },
      ],
      { cancelable: true }
    )
  }

  // Generate avatar initials from username
  const initials = user?.username
    ? user.username.slice(0, 2).toUpperCase()
    : '??'

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView showsVerticalScrollIndicator={false}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Account</Text>
        </View>

        {/* Profile card */}
        <LinearGradient
          colors={['#4338ca', '#6366f1']}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.profileCard}
        >
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{initials}</Text>
          </View>
          <Text style={styles.username}>{user?.username}</Text>
          {user?.email ? (
            <Text style={styles.email}>{user.email}</Text>
          ) : null}
          <View style={styles.profileBadge}>
            <Ionicons name="checkmark-circle" size={12} color="rgba(255,255,255,0.8)" />
            <Text style={styles.profileBadgeText}>Active account</Text>
          </View>
        </LinearGradient>

        {/* Stats */}
        <View style={styles.statsRow}>
          {[
            { label: 'Analyses', value: stats.total, icon: 'layers-outline', color: colors.primary },
            { label: 'Best Score', value: stats.best, icon: 'trophy-outline', color: colors.success },
            { label: 'Avg Score', value: stats.avg, icon: 'bar-chart-outline', color: colors.warning },
          ].map(({ label, value, icon, color }) => (
            <View key={label} style={styles.statCard}>
              <View style={[styles.statIcon, { backgroundColor: `${color}18` }]}>
                <Ionicons name={icon} size={15} color={color} />
              </View>
              <Text style={styles.statValue}>{value ?? '—'}</Text>
              <Text style={styles.statLabel}>{label}</Text>
            </View>
          ))}
        </View>

        {/* Info section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Account Info</Text>
          <View style={styles.menuCard}>
            <MenuItem
              icon="person-outline"
              label="Username"
              value={user?.username}
            />
            <View style={styles.menuDivider} />
            <MenuItem
              icon="mail-outline"
              label="Email"
              value={user?.email || 'Not set'}
            />
          </View>
        </View>

        {/* Sign out */}
        <View style={styles.section}>
          <View style={styles.menuCard}>
            <MenuItem
              icon="log-out-outline"
              label="Sign Out"
              onPress={handleLogout}
              danger
            />
          </View>
        </View>

        {/* Footer */}
        <View style={styles.footer}>
          <Text style={styles.footerText}>Resume AI · v1.0.0</Text>
          <Text style={styles.footerSub}>Powered by Claude &amp; OpenAI</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },

  header: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.lg,
    paddingBottom: spacing.md,
  },
  headerTitle: {
    fontSize: font.xxl,
    fontWeight: '800',
    color: colors.textPrimary,
    letterSpacing: -0.5,
  },

  // Profile
  profileCard: {
    marginHorizontal: spacing.xl,
    borderRadius: radius.xxl,
    padding: spacing.xxl,
    alignItems: 'center',
    gap: spacing.sm,
    ...shadow.hero,
  },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: radius.full,
    backgroundColor: 'rgba(255,255,255,0.25)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.sm,
    borderWidth: 2,
    borderColor: 'rgba(255,255,255,0.4)',
  },
  avatarText: {
    fontSize: font.xxl,
    fontWeight: '800',
    color: colors.surface,
    letterSpacing: 1,
  },
  username: {
    fontSize: font.xl,
    fontWeight: '700',
    color: colors.surface,
    letterSpacing: -0.3,
  },
  email: {
    fontSize: font.sm,
    color: 'rgba(255,255,255,0.75)',
  },
  profileBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.18)',
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
    borderRadius: radius.full,
  },
  profileBadgeText: {
    fontSize: font.xs,
    color: 'rgba(255,255,255,0.9)',
    fontWeight: '600',
  },

  // Stats
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginHorizontal: spacing.xl,
    marginTop: spacing.lg,
  },
  statCard: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    padding: spacing.md,
    alignItems: 'center',
    gap: spacing.xs,
    ...shadow.sm,
  },
  statIcon: {
    width: 32,
    height: 32,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.xs,
  },
  statValue: {
    fontSize: font.xl,
    fontWeight: '800',
    color: colors.textPrimary,
    letterSpacing: -0.5,
  },
  statLabel: {
    fontSize: font.xs,
    color: colors.textMuted,
    fontWeight: '500',
    textAlign: 'center',
  },

  // Sections
  section: {
    marginHorizontal: spacing.xl,
    marginTop: spacing.xl,
  },
  sectionTitle: {
    fontSize: font.xs,
    fontWeight: '700',
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: spacing.sm,
    marginLeft: spacing.sm,
  },
  menuCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    overflow: 'hidden',
    ...shadow.sm,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md + 2,
    gap: spacing.md,
  },
  menuIconWrap: {
    width: 34,
    height: 34,
    borderRadius: radius.md,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuIconDanger: { backgroundColor: colors.errorLight },
  menuLabel: {
    flex: 1,
    fontSize: font.md,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  menuLabelDanger: { color: colors.error },
  menuValue: {
    fontSize: font.sm,
    color: colors.textSecondary,
    maxWidth: 140,
  },
  menuDivider: {
    height: 1,
    backgroundColor: colors.border,
    marginLeft: spacing.lg + 34 + spacing.md,
  },

  // Footer
  footer: {
    alignItems: 'center',
    paddingVertical: spacing.xxxl,
    gap: spacing.xs,
  },
  footerText: {
    fontSize: font.sm,
    color: colors.textMuted,
    fontWeight: '500',
  },
  footerSub: {
    fontSize: font.xs,
    color: colors.textMuted,
  },
})
