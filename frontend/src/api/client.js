import axios from 'axios'

// In production, VITE_API_URL points to the Railway backend
// (e.g. https://your-backend.up.railway.app/api).
// In local dev it falls back to '/api' which Vite proxies to Django.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
})

// Attach access token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Token refresh state — shared across all concurrent 401 responses
let isRefreshing = false
let refreshSubscribers = []

function onRefreshed(newToken) {
  refreshSubscribers.forEach((cb) => cb(newToken))
  refreshSubscribers = []
}

function addRefreshSubscriber(cb) {
  refreshSubscribers.push(cb)
}

// On 401: queue concurrent requests, refresh once, then replay all
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config

    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error)
    }

    const refresh = localStorage.getItem('refresh_token')
    if (!refresh) {
      window.location.href = '/login'
      return Promise.reject(error)
    }

    if (isRefreshing) {
      // Another refresh is already in-flight — queue this request
      return new Promise((resolve, reject) => {
        addRefreshSubscriber((newToken) => {
          if (newToken) {
            original.headers.Authorization = `Bearer ${newToken}`
            resolve(api(original))
          } else {
            reject(error)
          }
        })
      })
    }

    original._retry = true
    isRefreshing = true

    try {
      const baseURL = import.meta.env.VITE_API_URL || '/api'
      const { data } = await axios.post(`${baseURL}/auth/token/refresh/`, { refresh })
      const newToken = data.access
      localStorage.setItem('access_token', newToken)
      api.defaults.headers.common.Authorization = `Bearer ${newToken}`
      onRefreshed(newToken)
      original.headers.Authorization = `Bearer ${newToken}`
      return api(original)
    } catch {
      onRefreshed(null)
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      window.location.href = '/login'
      return Promise.reject(error)
    } finally {
      isRefreshing = false
    }
  }
)

export default api
