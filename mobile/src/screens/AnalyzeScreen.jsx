import { useState } from 'react'
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ScrollView, ActivityIndicator, Platform,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Ionicons } from '@expo/vector-icons'
import * as DocumentPicker from 'expo-document-picker'
import * as Haptics from 'expo-haptics'
import api from '../api/client'
import { colors, shadow, radius, spacing, font } from '../theme'

const JD_TABS = [
  { value: 'text', label: 'Paste Text', icon: 'create-outline' },
  { value: 'url', label: 'Job URL', icon: 'link-outline' },
  { value: 'form', label: 'Fill Form', icon: 'list-outline' },
]

const INITIAL_FORM = {
  jd_text: '', jd_url: '', jd_role: '', jd_company: '',
  jd_skills: '', jd_experience_years: '', jd_industry: '', jd_extra_details: '',
}

export default function AnalyzeScreen({ navigation }) {
  const [file, setFile] = useState(null)
  const [jdType, setJdType] = useState('text')
  const [form, setForm] = useState(INITIAL_FORM)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const set = (field) => (value) => setForm((f) => ({ ...f, [field]: value }))

  const handlePickPDF = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: 'application/pdf',
        copyToCacheDirectory: true,
      })
      if (!result.canceled && result.assets?.[0]) {
        const picked = result.assets[0]
        if (picked.size > 5 * 1024 * 1024) {
          setError('File exceeds 5 MB limit.')
          return
        }
        setFile(picked)
        setError('')
        await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
      }
    } catch {
      setError('Could not open file picker.')
    }
  }

  const handleSubmit = async () => {
    if (!file) {
      setError('Please upload a PDF resume.')
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning)
      return
    }
    setError('')
    setLoading(true)

    const fd = new FormData()
    fd.append('resume_file', {
      uri: Platform.OS === 'ios' ? file.uri.replace('file://', '') : file.uri,
      name: file.name,
      type: 'application/pdf',
    })
    fd.append('jd_input_type', jdType)
    if (jdType === 'text') fd.append('jd_text', form.jd_text)
    if (jdType === 'url') fd.append('jd_url', form.jd_url)
    if (jdType === 'form') {
      ;['jd_role', 'jd_company', 'jd_skills', 'jd_industry', 'jd_extra_details'].forEach((k) => {
        if (form[k]) fd.append(k, form[k])
      })
      if (form.jd_experience_years) fd.append('jd_experience_years', form.jd_experience_years)
    }

    try {
      const { data } = await api.post('/analyze/', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)
      navigation.navigate('Results', { id: data.id })
    } catch (err) {
      const errs = err.response?.data
      if (errs && typeof errs === 'object') {
        setError(Object.values(errs).flat().join(' '))
      } else {
        setError('Analysis failed. Ensure the API key is configured.')
      }
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error)
    } finally {
      setLoading(false)
    }
  }

  const sizeKb = file ? (file.size / 1024).toFixed(0) : null

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Analyze Resume</Text>
        <Text style={styles.headerSub}>
          Upload your PDF and describe the job to get your ATS score
        </Text>
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {/* Error */}
        {error ? (
          <View style={styles.errorBox}>
            <Ionicons name="alert-circle-outline" size={15} color={colors.error} />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        {/* PDF Upload */}
        <View style={styles.card}>
          <View style={styles.sectionHeader}>
            <View style={styles.sectionIconWrap}>
              <Ionicons name="document-attach-outline" size={16} color={colors.primary} />
            </View>
            <Text style={styles.sectionTitle}>Resume</Text>
            <Text style={styles.sectionHint}>PDF only · max 5 MB</Text>
          </View>

          <TouchableOpacity
            style={[styles.uploadArea, file && styles.uploadAreaDone]}
            onPress={handlePickPDF}
            activeOpacity={0.75}
          >
            {file ? (
              <View style={styles.fileInfo}>
                <View style={styles.fileIconWrap}>
                  <Ionicons name="document-text" size={24} color={colors.primary} />
                </View>
                <View style={styles.fileMeta}>
                  <Text style={styles.fileName} numberOfLines={1}>{file.name}</Text>
                  <Text style={styles.fileSize}>{sizeKb} KB · tap to replace</Text>
                </View>
                <View style={styles.checkCircle}>
                  <Ionicons name="checkmark" size={14} color={colors.surface} />
                </View>
              </View>
            ) : (
              <View style={styles.uploadEmpty}>
                <View style={styles.uploadIconWrap}>
                  <Ionicons name="cloud-upload-outline" size={28} color={colors.primary} />
                </View>
                <Text style={styles.uploadTitle}>Tap to upload PDF</Text>
                <Text style={styles.uploadSub}>Browse files on your device</Text>
              </View>
            )}
          </TouchableOpacity>
        </View>

        {/* Job Description */}
        <View style={styles.card}>
          <View style={styles.sectionHeader}>
            <View style={styles.sectionIconWrap}>
              <Ionicons name="briefcase-outline" size={16} color={colors.primary} />
            </View>
            <Text style={styles.sectionTitle}>Job Description</Text>
          </View>

          {/* Tabs */}
          <View style={styles.tabs}>
            {JD_TABS.map((tab) => {
              const active = jdType === tab.value
              return (
                <TouchableOpacity
                  key={tab.value}
                  style={[styles.tab, active && styles.tabActive]}
                  onPress={() => setJdType(tab.value)}
                  activeOpacity={0.75}
                >
                  <Ionicons
                    name={tab.icon}
                    size={13}
                    color={active ? colors.primary : colors.textMuted}
                  />
                  <Text style={[styles.tabText, active && styles.tabTextActive]}>
                    {tab.label}
                  </Text>
                </TouchableOpacity>
              )
            })}
          </View>

          {/* Text */}
          {jdType === 'text' && (
            <TextInput
              style={styles.textarea}
              value={form.jd_text}
              onChangeText={set('jd_text')}
              placeholder="Paste the full job description here…"
              placeholderTextColor={colors.textMuted}
              multiline
              numberOfLines={7}
              textAlignVertical="top"
            />
          )}

          {/* URL */}
          {jdType === 'url' && (
            <View>
              <View style={styles.inputRow}>
                <Ionicons name="link-outline" size={17} color={colors.textMuted} />
                <TextInput
                  style={styles.input}
                  value={form.jd_url}
                  onChangeText={set('jd_url')}
                  placeholder="https://company.com/careers/role"
                  placeholderTextColor={colors.textMuted}
                  keyboardType="url"
                  autoCapitalize="none"
                  autoCorrect={false}
                />
              </View>
              <Text style={styles.urlHint}>
                We'll scrape the page and extract the job description automatically.
              </Text>
            </View>
          )}

          {/* Form */}
          {jdType === 'form' && (
            <View style={styles.formFields}>
              <TextInput
                style={styles.formInput}
                value={form.jd_role}
                onChangeText={set('jd_role')}
                placeholder="Job title / role *"
                placeholderTextColor={colors.textMuted}
              />
              <TextInput
                style={styles.formInput}
                value={form.jd_company}
                onChangeText={set('jd_company')}
                placeholder="Company name"
                placeholderTextColor={colors.textMuted}
              />
              <TextInput
                style={styles.formInput}
                value={form.jd_skills}
                onChangeText={set('jd_skills')}
                placeholder="Required skills (e.g. Python, AWS, Docker)"
                placeholderTextColor={colors.textMuted}
              />
              <View style={styles.formRow}>
                <TextInput
                  style={[styles.formInput, styles.formHalf]}
                  value={form.jd_experience_years}
                  onChangeText={set('jd_experience_years')}
                  placeholder="Years of exp."
                  placeholderTextColor={colors.textMuted}
                  keyboardType="numeric"
                />
                <TextInput
                  style={[styles.formInput, styles.formHalf]}
                  value={form.jd_industry}
                  onChangeText={set('jd_industry')}
                  placeholder="Industry"
                  placeholderTextColor={colors.textMuted}
                />
              </View>
              <TextInput
                style={[styles.formInput, styles.textarea, { marginBottom: 0 }]}
                value={form.jd_extra_details}
                onChangeText={set('jd_extra_details')}
                placeholder="Any other important details…"
                placeholderTextColor={colors.textMuted}
                multiline
                numberOfLines={3}
                textAlignVertical="top"
              />
            </View>
          )}
        </View>

        {/* Submit */}
        <TouchableOpacity
          style={[styles.submitBtn, loading && styles.submitBtnDisabled]}
          onPress={handleSubmit}
          disabled={loading}
          activeOpacity={0.85}
        >
          {loading ? (
            <View style={styles.submitLoading}>
              <ActivityIndicator color={colors.surface} size="small" />
              <Text style={styles.submitText}>Analyzing your resume…</Text>
            </View>
          ) : (
            <View style={styles.submitInner}>
              <Ionicons name="sparkles-outline" size={18} color={colors.surface} />
              <Text style={styles.submitText}>Analyze Resume</Text>
            </View>
          )}
        </TouchableOpacity>
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
  headerSub: {
    fontSize: font.sm,
    color: colors.textSecondary,
    marginTop: spacing.xs,
    lineHeight: 18,
  },
  scroll: { flex: 1 },
  content: {
    paddingHorizontal: spacing.xl,
    paddingBottom: spacing.xxxl,
    gap: spacing.lg,
  },

  errorBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.errorLight,
    borderWidth: 1,
    borderColor: colors.errorBorder,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
  },
  errorText: { flex: 1, fontSize: font.sm, color: colors.error, lineHeight: 18 },

  // Card
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    padding: spacing.lg,
    ...shadow.sm,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  sectionIconWrap: {
    width: 28,
    height: 28,
    borderRadius: radius.sm,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sectionTitle: {
    fontSize: font.md,
    fontWeight: '700',
    color: colors.textPrimary,
    flex: 1,
  },
  sectionHint: { fontSize: font.xs, color: colors.textMuted },

  // Upload
  uploadArea: {
    borderWidth: 2,
    borderColor: colors.border,
    borderStyle: 'dashed',
    borderRadius: radius.lg,
    paddingVertical: spacing.xxl,
    paddingHorizontal: spacing.lg,
    alignItems: 'center',
  },
  uploadAreaDone: {
    borderStyle: 'solid',
    borderColor: colors.primary,
    backgroundColor: colors.primaryLight,
    paddingVertical: spacing.lg,
  },
  uploadEmpty: { alignItems: 'center', gap: spacing.sm },
  uploadIconWrap: {
    width: 56,
    height: 56,
    borderRadius: radius.xl,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.xs,
  },
  uploadTitle: {
    fontSize: font.md,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  uploadSub: { fontSize: font.sm, color: colors.textSecondary },
  fileInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    width: '100%',
    gap: spacing.md,
  },
  fileIconWrap: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    ...shadow.xs,
  },
  fileMeta: { flex: 1 },
  fileName: { fontSize: font.sm, fontWeight: '600', color: colors.textPrimary },
  fileSize: { fontSize: font.xs, color: colors.textSecondary, marginTop: 2 },
  checkCircle: {
    width: 24,
    height: 24,
    borderRadius: radius.full,
    backgroundColor: colors.success,
    alignItems: 'center',
    justifyContent: 'center',
  },

  // Tabs
  tabs: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  tab: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.full,
    borderWidth: 1.5,
    borderColor: colors.border,
  },
  tabActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primaryLight,
  },
  tabText: { fontSize: font.xs, fontWeight: '600', color: colors.textMuted },
  tabTextActive: { color: colors.primary },

  // Inputs
  textarea: {
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: '#f8fafc',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    fontSize: font.sm,
    color: colors.textPrimary,
    minHeight: 120,
    lineHeight: 20,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: '#f8fafc',
    paddingHorizontal: spacing.md,
    height: 50,
  },
  input: {
    flex: 1,
    fontSize: font.md,
    color: colors.textPrimary,
    height: '100%',
  },
  urlHint: {
    fontSize: font.xs,
    color: colors.textMuted,
    marginTop: spacing.sm,
    lineHeight: 17,
  },
  formFields: { gap: spacing.md },
  formInput: {
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: '#f8fafc',
    paddingHorizontal: spacing.md,
    height: 50,
    fontSize: font.sm,
    color: colors.textPrimary,
  },
  formRow: { flexDirection: 'row', gap: spacing.md },
  formHalf: { flex: 1 },

  // Submit
  submitBtn: {
    backgroundColor: colors.primary,
    borderRadius: radius.lg,
    height: 56,
    alignItems: 'center',
    justifyContent: 'center',
    ...shadow.lg,
  },
  submitBtnDisabled: { opacity: 0.65 },
  submitInner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  submitLoading: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  submitText: {
    fontSize: font.md,
    fontWeight: '700',
    color: colors.surface,
    letterSpacing: 0.2,
  },
})
