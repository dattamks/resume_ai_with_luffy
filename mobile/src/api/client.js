import axios from 'axios'
import { Platform } from 'react-native'
import * as SecureStore from 'expo-secure-store'
import { triggerSignOut } from './authEvents'

/**
 * Base URL configuration.
 * - Android emulator uses 10.0.2.2 to reach the host machine's localhost.
 * - iOS simulator can use localhost directly.
 * - Change to your production URL for release builds.
 */
const BASE_URL = __DEV__
  ? Platform.OS === 'android'
    ? 'http://10.0.2.2:8000/api'
    : 'http://localhost:8000/api'
  : 'https://your-production-domain.com/api'

const api = axios.create({ baseURL: BASE_URL })

// Attach access token to every request
api.interceptors.request.use(async (config) => {
  const token = await SecureStore.getItemAsync('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// On 401: silently refresh once, then retry original request
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      const refresh = await SecureStore.getItemAsync('refresh_token')
      if (refresh) {
        try {
          const { data } = await axios.post(`${BASE_URL}/auth/token/refresh/`, { refresh })
          await SecureStore.setItemAsync('access_token', data.access)
          original.headers.Authorization = `Bearer ${data.access}`
          return api(original)
        } catch {
          await SecureStore.deleteItemAsync('access_token')
          await SecureStore.deleteItemAsync('refresh_token')
          triggerSignOut()
        }
      } else {
        triggerSignOut()
      }
    }
    return Promise.reject(error)
  }
)

export default api
