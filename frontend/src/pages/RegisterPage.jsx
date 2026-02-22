import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'
import toast from 'react-hot-toast'

const FIELDS = [
  { name: 'username', label: 'Username', type: 'text', min: 3 },
  { name: 'email', label: 'Email', type: 'email' },
  { name: 'password', label: 'Password', type: 'password', min: 8 },
  { name: 'password2', label: 'Confirm password', type: 'password' },
]

export default function RegisterPage() {
  const [form, setForm] = useState({ username: '', email: '', password: '', password2: '' })
  const [loading, setLoading] = useState(false)
  const [touched, setTouched] = useState({})
  const { login } = useAuth()
  const navigate = useNavigate()

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))
  const touch = (field) => () => setTouched((t) => ({ ...t, [field]: true }))

  // Field-level validation
  const fieldError = (name) => {
    if (!touched[name]) return null
    if (name === 'username' && form.username.length > 0 && form.username.length < 3) return 'At least 3 characters'
    if (name === 'email' && form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) return 'Enter a valid email'
    if (name === 'password' && form.password.length > 0 && form.password.length < 8) return 'At least 8 characters'
    if (name === 'password2' && form.password2 && form.password !== form.password2) return 'Passwords do not match'
    return null
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (form.password !== form.password2) {
      toast.error('Passwords do not match.')
      return
    }
    setLoading(true)
    try {
      const { data } = await api.post('/auth/register/', form)
      login(data.user, data.access, data.refresh)
      toast.success('Account created!')
      navigate('/')
    } catch (err) {
      const errs = err.response?.data
      if (errs && typeof errs === 'object') {
        toast.error(Object.values(errs).flat().join(' '))
      } else {
        toast.error('Registration failed. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-56px)] px-4">
      <div className="bg-white dark:bg-slate-900 p-8 rounded-2xl shadow-sm border border-gray-200 dark:border-slate-700 w-full max-w-sm">
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-1">Create account</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">Start optimizing your resume today</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {FIELDS.map(({ name, label, type, min }) => {
            const err = fieldError(name)
            return (
              <div key={name}>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">{label}</label>
                  {min && form[name].length > 0 && (
                    <span className={`text-xs ${form[name].length >= min ? 'text-green-500 dark:text-green-400' : 'text-gray-400 dark:text-gray-500'}`}>
                      {form[name].length}/{min}+
                    </span>
                  )}
                </div>
                <input
                  type={type}
                  value={form[name]}
                  onChange={set(name)}
                  onBlur={touch(name)}
                  className={`w-full border bg-white dark:bg-slate-800 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-colors ${
                    err ? 'border-red-400 dark:border-red-500' : 'border-gray-300 dark:border-slate-600'
                  }`}
                  required={name !== 'email'}
                  autoFocus={name === 'username'}
                />
                {err && <p className="text-xs text-red-500 dark:text-red-400 mt-1">{err}</p>}
              </div>
            )
          })}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-indigo-600 text-white py-2.5 rounded-lg text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-colors mt-2"
          >
            {loading ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="text-sm text-center text-gray-500 dark:text-gray-400 mt-5">
          Already have an account?{' '}
          <Link to="/login" className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
