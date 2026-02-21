import { useEffect, useState } from 'react'
import {
  View, Text, StyleSheet, ScrollView,
  TouchableOpacity, Platform,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import * as Haptics from 'expo-haptics'
import api from '../api/client'
import Spinner from '../components/Spinner'
import ScoreGauge from '../components/ScoreGauge'
import ScoreBar from '../components/ScoreBar'
import SectionAccordion from '../components/SectionAccordion'
import { colors, shadow, radius, spacing, font } from '../theme'

function KeywordTag({ word }) {
  return (
    <View style={styles.tag}>
      <Text style={styles.tagText}>{word}</Text>
    </View>
  )
}

function BulletCard({ item }) {
  return (
    <View style={styles.bulletCard}>
      <View style={styles.bulletBlock}>
        <Text style={styles.bulletLabel}>Original</Text>
        <Text style={styles.bulletOriginal}>{item.original}</Text>
      </View>
      <View style={styles.bulletDivider} />
      <View style={styles.bulletBlock}>
        <Text style={[styles.bulletLabel, styles.bulletLabelGreen]}>Improved</Text>
        <Text style={styles.bulletImproved}>{item.rewritten}</Text>
      </View>
      {item.reason ? (
        <Text style={styles.bulletReason}>{item.reason}</Text>
      ) : null}
    </View>
  )
}

export default function ResultsScreen({ route, navigation }) {
  const { id } = route.params
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get(`/analyses/${id}/`)
      .then(({ data }) => setAnalysis(data))
      .catch(() => setError('Could not load this analysis.'))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <Spinner />
  if (error) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.errorFull}>
          <Ionicons name="cloud-offline-outline" size={48} color={colors.textMuted} />
          <Text style={styles.errorFullText}>{error}</Text>
          <TouchableOpacity style={styles.backBtnSmall} onPress={() => navigation.goBack()}>
            <Text style={styles.backBtnSmallText}>Go back</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    )
  }
  if (!analysis) return null

  const bd = analysis.ats_score_breakdown || {}
  const sections = analysis.section_suggestions || {}
  const bullets = analysis.rewritten_bullets || []
  const gaps = analysis.keyword_gaps || []
  const score = analysis.ats_score ?? 0
  const subtitle = [analysis.jd_role, analysis.jd_company].filter(Boolean).join(' at ')
  const dateStr = new Date(analysis.created_at).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  })

  return (
    <View style={styles.safe}>
      <ScrollView
        style={styles.scroll}
        showsVerticalScrollIndicator={false}
        stickyHeaderIndices={[0]}
      >
        {/* Hero (sticky) */}
        <LinearGradient
          colors={['#4338ca', '#6366f1', '#818cf8']}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.hero}
        >
          <SafeAreaView edges={['top']}>
            {/* Nav row */}
            <View style={styles.heroNav}>
              <TouchableOpacity
                style={styles.heroBack}
                onPress={() => navigation.goBack()}
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              >
                <Ionicons name="arrow-back" size={20} color={colors.surface} />
              </TouchableOpacity>
              <View style={styles.heroTitleWrap}>
                <Text style={styles.heroTitle}>Analysis Results</Text>
                {subtitle ? (
                  <Text style={styles.heroSubtitle} numberOfLines={1}>{subtitle}</Text>
                ) : null}
              </View>
              <View style={styles.heroBadge}>
                <Text style={styles.heroBadgeText}>{analysis.ai_provider_used}</Text>
              </View>
            </View>

            {/* Score gauge */}
            <View style={styles.gaugeWrap}>
              <ScoreGauge score={score} light />
              <Text style={styles.heroDate}>{dateStr}</Text>
            </View>
          </SafeAreaView>
        </LinearGradient>

        {/* Content */}
        <View style={styles.content}>
          {/* Score Breakdown */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Score Breakdown</Text>
            <ScoreBar label="Keyword Match" value={bd.keyword_match ?? 0} />
            <ScoreBar label="Format & Structure" value={bd.format_score ?? 0} />
            <ScoreBar label="Relevance" value={bd.relevance_score ?? 0} />
          </View>

          {/* Overall Assessment */}
          {analysis.overall_assessment ? (
            <View style={styles.assessCard}>
              <View style={styles.assessHeader}>
                <Ionicons name="bulb-outline" size={16} color={colors.primary} />
                <Text style={styles.assessTitle}>Overall Assessment</Text>
              </View>
              <Text style={styles.assessText}>{analysis.overall_assessment}</Text>
            </View>
          ) : null}

          {/* Missing Keywords */}
          {gaps.length > 0 && (
            <View style={styles.card}>
              <View style={styles.cardTitleRow}>
                <Text style={styles.cardTitle}>Missing Keywords</Text>
                <View style={styles.countBadge}>
                  <Text style={styles.countBadgeText}>{gaps.length}</Text>
                </View>
              </View>
              <View style={styles.tagCloud}>
                {gaps.map((kw) => <KeywordTag key={kw} word={kw} />)}
              </View>
            </View>
          )}

          {/* Section Suggestions */}
          {Object.keys(sections).length > 0 && (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Section Suggestions</Text>
              <View style={styles.accordionWrap}>
                <SectionAccordion sections={sections} />
              </View>
            </View>
          )}

          {/* Rewritten Bullets */}
          {bullets.length > 0 && (
            <View style={styles.card}>
              <View style={styles.cardTitleRow}>
                <Text style={styles.cardTitle}>Rewritten Bullets</Text>
                <View style={[styles.countBadge, styles.countBadgeGreen]}>
                  <Text style={[styles.countBadgeText, styles.countBadgeTextGreen]}>
                    {bullets.length}
                  </Text>
                </View>
              </View>
              {bullets.map((item, i) => <BulletCard key={i} item={item} />)}
            </View>
          )}

          {/* Actions */}
          <View style={styles.actions}>
            <TouchableOpacity
              style={styles.actionBtnPrimary}
              onPress={async () => {
                await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
                navigation.navigate('AnalyzeMain')
              }}
              activeOpacity={0.85}
            >
              <Ionicons name="add-circle-outline" size={18} color={colors.surface} />
              <Text style={styles.actionBtnPrimaryText}>Analyze Another</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.actionBtnSecondary}
              onPress={() => navigation.navigate('History')}
              activeOpacity={0.85}
            >
              <Ionicons name="time-outline" size={18} color={colors.primary} />
              <Text style={styles.actionBtnSecondaryText}>View History</Text>
            </TouchableOpacity>
          </View>
        </View>
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { flex: 1 },

  // Hero
  hero: {
    paddingBottom: spacing.xxl,
  },
  heroNav: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
    paddingBottom: spacing.md,
    gap: spacing.md,
  },
  heroBack: {
    width: 36,
    height: 36,
    borderRadius: radius.full,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroTitleWrap: { flex: 1 },
  heroTitle: {
    fontSize: font.lg,
    fontWeight: '700',
    color: colors.surface,
    letterSpacing: -0.3,
  },
  heroSubtitle: {
    fontSize: font.xs,
    color: 'rgba(255,255,255,0.75)',
    marginTop: 2,
  },
  heroBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.full,
    backgroundColor: 'rgba(255,255,255,0.2)',
  },
  heroBadgeText: {
    fontSize: font.xs,
    fontWeight: '600',
    color: colors.surface,
    textTransform: 'capitalize',
  },
  gaugeWrap: {
    alignItems: 'center',
    paddingTop: spacing.md,
    gap: spacing.sm,
  },
  heroDate: {
    fontSize: font.xs,
    color: 'rgba(255,255,255,0.6)',
    marginTop: spacing.xs,
  },

  // Content
  content: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.xl,
    paddingBottom: spacing.xxxl,
    gap: spacing.lg,
  },

  // Card
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    padding: spacing.lg,
    ...shadow.sm,
  },
  cardTitle: {
    fontSize: font.md,
    fontWeight: '700',
    color: colors.textPrimary,
    marginBottom: spacing.lg,
  },
  cardTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  countBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.full,
    backgroundColor: '#fee2e2',
  },
  countBadgeText: {
    fontSize: font.xs,
    fontWeight: '700',
    color: colors.error,
  },
  countBadgeGreen: { backgroundColor: colors.successLight },
  countBadgeTextGreen: { color: '#15803d' },

  // Assessment card
  assessCard: {
    backgroundColor: colors.primaryLight,
    borderRadius: radius.xl,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: '#c7d2fe',
  },
  assessHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  assessTitle: {
    fontSize: font.sm,
    fontWeight: '700',
    color: colors.primary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  assessText: {
    fontSize: font.sm,
    color: colors.textPrimary,
    lineHeight: 21,
  },

  // Tags
  tagCloud: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  tag: {
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: radius.full,
    backgroundColor: '#fef2f2',
    borderWidth: 1,
    borderColor: '#fecaca',
  },
  tagText: {
    fontSize: font.sm,
    fontWeight: '600',
    color: colors.error,
  },

  // Accordion
  accordionWrap: {
    borderRadius: radius.md,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.border,
    marginTop: -spacing.sm,
  },

  // Bullet cards
  bulletCard: {
    backgroundColor: '#f8fafc',
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.md,
  },
  bulletBlock: {},
  bulletLabel: {
    fontSize: font.xs,
    fontWeight: '700',
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.xs,
  },
  bulletLabelGreen: { color: '#15803d' },
  bulletOriginal: {
    fontSize: font.sm,
    color: colors.textSecondary,
    textDecorationLine: 'line-through',
    lineHeight: 20,
  },
  bulletImproved: {
    fontSize: font.sm,
    color: colors.textPrimary,
    fontWeight: '600',
    lineHeight: 20,
  },
  bulletDivider: {
    height: 1,
    backgroundColor: colors.border,
  },
  bulletReason: {
    fontSize: font.xs,
    color: colors.textMuted,
    fontStyle: 'italic',
    lineHeight: 17,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },

  // Actions
  actions: { gap: spacing.md },
  actionBtnPrimary: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: colors.primary,
    borderRadius: radius.lg,
    height: 52,
    ...shadow.lg,
  },
  actionBtnPrimaryText: {
    fontSize: font.md,
    fontWeight: '700',
    color: colors.surface,
  },
  actionBtnSecondary: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    height: 52,
    borderWidth: 1.5,
    borderColor: colors.border,
  },
  actionBtnSecondaryText: {
    fontSize: font.md,
    fontWeight: '700',
    color: colors.primary,
  },

  // Error full
  errorFull: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.lg,
    padding: spacing.xxxl,
  },
  errorFullText: {
    fontSize: font.md,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  backBtnSmall: {
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.primaryLight,
  },
  backBtnSmallText: {
    fontSize: font.sm,
    fontWeight: '600',
    color: colors.primary,
  },
})
