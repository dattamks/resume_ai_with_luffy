import { useEffect, useState, useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity, StyleSheet,
  RefreshControl,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Ionicons } from '@expo/vector-icons'
import api from '../api/client'
import Spinner from '../components/Spinner'
import ScorePill from '../components/ScorePill'
import StatusDot from '../components/StatusDot'
import { colors, shadow, radius, spacing, font } from '../theme'

function StatCard({ label, value, icon, color }) {
  return (
    <View style={styles.statCard}>
      <View style={[styles.statIcon, { backgroundColor: `${color}18` }]}>
        <Ionicons name={icon} size={16} color={color} />
      </View>
      <Text style={styles.statValue}>{value ?? '—'}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  )
}

function HistoryItem({ item, onPress }) {
  const date = new Date(item.created_at).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  })

  return (
    <TouchableOpacity style={styles.item} onPress={onPress} activeOpacity={0.75}>
      <View style={styles.itemLeft}>
        <Text style={styles.itemRole} numberOfLines={1}>
          {item.jd_role || 'Untitled role'}
        </Text>
        <View style={styles.itemMeta}>
          <Text style={styles.itemCompany} numberOfLines={1}>
            {item.jd_company || 'Unknown company'}
          </Text>
          <View style={styles.metaDot} />
          <Text style={styles.itemDate}>{date}</Text>
        </View>
        <View style={styles.itemStatusRow}>
          <StatusDot status={item.status} />
        </View>
      </View>
      <View style={styles.itemRight}>
        <ScorePill score={item.ats_score} />
        <Ionicons name="chevron-forward" size={16} color={colors.textMuted} />
      </View>
    </TouchableOpacity>
  )
}

export default function HistoryScreen({ navigation }) {
  const [analyses, setAnalyses] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const { data } = await api.get('/analyses/')
      setAnalyses(Array.isArray(data) ? data : data.results ?? [])
    } catch {
      // keep existing data on refresh failure
    }
  }, [])

  useEffect(() => {
    fetchData().finally(() => setLoading(false))
  }, [fetchData])

  const handleRefresh = async () => {
    setRefreshing(true)
    await fetchData()
    setRefreshing(false)
  }

  if (loading) return <Spinner />

  const done = analyses.filter((a) => a.status === 'done')
  const avgScore =
    done.length > 0
      ? Math.round(done.reduce((s, a) => s + (a.ats_score || 0), 0) / done.length)
      : null
  const best = done.length > 0 ? Math.max(...done.map((a) => a.ats_score || 0)) : null

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>History</Text>
        <TouchableOpacity
          style={styles.newBtn}
          onPress={() => navigation.navigate('Analyze')}
          activeOpacity={0.85}
        >
          <Ionicons name="add" size={16} color={colors.surface} />
          <Text style={styles.newBtnText}>New</Text>
        </TouchableOpacity>
      </View>

      <FlatList
        data={analyses}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={colors.primary}
            colors={[colors.primary]}
          />
        }
        ListHeaderComponent={
          done.length > 0 ? (
            <View style={styles.statsRow}>
              <StatCard
                label="Total"
                value={analyses.length}
                icon="layers-outline"
                color={colors.primary}
              />
              <StatCard
                label="Avg Score"
                value={avgScore}
                icon="bar-chart-outline"
                color={colors.warning}
              />
              <StatCard
                label="Best Score"
                value={best}
                icon="trophy-outline"
                color={colors.success}
              />
            </View>
          ) : null
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <View style={styles.emptyIcon}>
              <Ionicons name="document-text-outline" size={32} color={colors.textMuted} />
            </View>
            <Text style={styles.emptyTitle}>No analyses yet</Text>
            <Text style={styles.emptySub}>Analyze your first resume to see results here</Text>
            <TouchableOpacity
              style={styles.emptyBtn}
              onPress={() => navigation.navigate('Analyze')}
              activeOpacity={0.85}
            >
              <Text style={styles.emptyBtnText}>Analyze Resume</Text>
            </TouchableOpacity>
          </View>
        }
        renderItem={({ item }) => (
          <HistoryItem
            item={item}
            onPress={() => navigation.navigate('Results', { id: item.id })}
          />
        )}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        ListFooterComponent={analyses.length > 0 ? <View style={{ height: spacing.xxxl }} /> : null}
      />
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
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
  newBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.full,
    ...shadow.md,
  },
  newBtnText: {
    fontSize: font.sm,
    fontWeight: '700',
    color: colors.surface,
  },

  // Stats
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.lg,
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
  },

  // List
  list: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.lg,
    ...shadow.xs,
  },
  itemLeft: { flex: 1, marginRight: spacing.md },
  itemRole: {
    fontSize: font.md,
    fontWeight: '700',
    color: colors.textPrimary,
    marginBottom: spacing.xs,
  },
  itemMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  itemCompany: {
    fontSize: font.sm,
    color: colors.textSecondary,
    maxWidth: 120,
  },
  metaDot: {
    width: 3,
    height: 3,
    borderRadius: 99,
    backgroundColor: colors.textMuted,
  },
  itemDate: { fontSize: font.xs, color: colors.textMuted },
  itemStatusRow: { flexDirection: 'row' },
  itemRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },

  separator: { height: spacing.sm },

  // Empty
  empty: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.xxxl * 2,
    gap: spacing.md,
  },
  emptyIcon: {
    width: 72,
    height: 72,
    borderRadius: radius.xxl,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.sm,
    ...shadow.sm,
  },
  emptyTitle: {
    fontSize: font.lg,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  emptySub: {
    fontSize: font.sm,
    color: colors.textSecondary,
    textAlign: 'center',
    lineHeight: 20,
    maxWidth: 240,
  },
  emptyBtn: {
    marginTop: spacing.sm,
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.xxl,
    paddingVertical: spacing.md,
    borderRadius: radius.lg,
    ...shadow.lg,
  },
  emptyBtnText: {
    fontSize: font.sm,
    fontWeight: '700',
    color: colors.surface,
  },
})
