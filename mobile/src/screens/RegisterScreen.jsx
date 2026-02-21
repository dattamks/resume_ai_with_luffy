import { useState } from 'react'
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Ionicons } from '@expo/vector-icons'
import * as Haptics from 'expo-haptics'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { colors, shadow, radius, spacing, font } from '../theme'

const FIELDS = [
  { name: 'username', label: 'Username', placeholder: 'Choose a username', icon: 'person-outline', type: 'default' },
  { name: 'email', label: 'Email', placeholder: 'your@email.com', icon: 'mail-outline', type: 'email-address' },
  { name: 'password', label: 'Password', placeholder: 'Create a password', icon: 'lock-closed-outline', secure: true },
  { name: 'password2', label: 'Confirm Password', placeholder: 'Repeat your password', icon: 'lock-closed-outline', secure: true },
]

export default function RegisterScreen({ navigation }) {
  const [form, setForm] = useState({ username: '', email: '', password: '', password2: '' })
  const [showPwd, setShowPwd] = useState({ password: false, password2: false })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()

  const set = (field) => (value) => setForm((f) => ({ ...f, [field]: value }))

  const handleSubmit = async () => {
    if (!form.username.trim() || !form.password) {
      setError('Username and password are required.')
      return
    }
    if (form.password !== form.password2) {
      setError('Passwords do not match.')
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning)
      return
    }
    setError('')
    setLoading(true)
    try {
      const { data } = await api.post('/auth/register/', form)
      await login(data.user, data.access, data.refresh)
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)
    } catch (err) {
      const errs = err.response?.data
      if (errs && typeof errs === 'object') {
        setError(Object.values(errs).flat().join(' '))
      } else {
        setError('Registration failed. Please try again.')
      }
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <ScrollView
          contentContainerStyle={styles.container}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {/* Back */}
          <TouchableOpacity style={styles.backBtn} onPress={() => navigation.goBack()}>
            <Ionicons name="arrow-back" size={20} color={colors.textSecondary} />
          </TouchableOpacity>

          {/* Brand */}
          <View style={styles.brand}>
            <View style={styles.logoWrap}>
              <Ionicons name="document-text" size={30} color={colors.surface} />
            </View>
            <Text style={styles.brandName}>Create Account</Text>
            <Text style={styles.brandTagline}>Start optimizing your resume today</Text>
          </View>

          {/* Card */}
          <View style={styles.card}>
            {error ? (
              <View style={styles.errorBox}>
                <Ionicons name="alert-circle-outline" size={15} color={colors.error} />
                <Text style={styles.errorText}>{error}</Text>
              </View>
            ) : null}

            {FIELDS.map(({ name, label, placeholder, icon, type, secure }) => (
              <View key={name} style={styles.field}>
                <Text style={styles.label}>{label}</Text>
                <View style={styles.inputRow}>
                  <Ionicons name={icon} size={17} color={colors.textMuted} />
                  <TextInput
                    style={[styles.input, secure && styles.inputFlex]}
                    value={form[name]}
                    onChangeText={set(name)}
                    placeholder={placeholder}
                    placeholderTextColor={colors.textMuted}
                    secureTextEntry={secure ? !showPwd[name] : false}
                    keyboardType={type || 'default'}
                    autoCapitalize="none"
                    autoCorrect={false}
                    returnKeyType={name === 'password2' ? 'done' : 'next'}
                    onSubmitEditing={name === 'password2' ? handleSubmit : undefined}
                  />
                  {secure && (
                    <TouchableOpacity
                      onPress={() => setShowPwd((p) => ({ ...p, [name]: !p[name] }))}
                      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    >
                      <Ionicons
                        name={showPwd[name] ? 'eye-off-outline' : 'eye-outline'}
                        size={17}
                        color={colors.textMuted}
                      />
                    </TouchableOpacity>
                  )}
                </View>
              </View>
            ))}

            <TouchableOpacity
              style={[styles.btn, loading && styles.btnDisabled]}
              onPress={handleSubmit}
              disabled={loading}
              activeOpacity={0.85}
            >
              {loading ? (
                <ActivityIndicator color={colors.surface} size="small" />
              ) : (
                <Text style={styles.btnText}>Create Account</Text>
              )}
            </TouchableOpacity>

            <View style={styles.footer}>
              <Text style={styles.footerText}>Already have an account? </Text>
              <TouchableOpacity onPress={() => navigation.navigate('Login')}>
                <Text style={styles.footerLink}>Sign in</Text>
              </TouchableOpacity>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  container: {
    flexGrow: 1,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.xxl,
  },
  backBtn: {
    width: 36,
    height: 36,
    borderRadius: radius.full,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.xl,
    ...shadow.sm,
  },
  brand: {
    alignItems: 'center',
    marginBottom: spacing.xxl,
  },
  logoWrap: {
    width: 64,
    height: 64,
    borderRadius: radius.xl,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.md,
    ...shadow.hero,
  },
  brandName: {
    fontSize: font.xl,
    fontWeight: '800',
    color: colors.textPrimary,
    letterSpacing: -0.3,
  },
  brandTagline: {
    fontSize: font.sm,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.xxl,
    padding: spacing.xxl,
    ...shadow.md,
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
    marginBottom: spacing.lg,
  },
  errorText: {
    flex: 1,
    fontSize: font.sm,
    color: colors.error,
    lineHeight: 18,
  },
  field: { marginBottom: spacing.lg },
  label: {
    fontSize: font.sm,
    fontWeight: '600',
    color: colors.textPrimary,
    marginBottom: spacing.sm,
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
  inputFlex: { flex: 1 },
  btn: {
    backgroundColor: colors.primary,
    borderRadius: radius.md,
    height: 52,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: spacing.sm,
    ...shadow.lg,
  },
  btnDisabled: { opacity: 0.6 },
  btnText: {
    fontSize: font.md,
    fontWeight: '700',
    color: colors.surface,
    letterSpacing: 0.2,
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'center',
    marginTop: spacing.xl,
  },
  footerText: { fontSize: font.sm, color: colors.textSecondary },
  footerLink: { fontSize: font.sm, color: colors.primary, fontWeight: '600' },
})
