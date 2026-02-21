import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import * as SecureStore from 'expo-secure-store'
import api from '../api/client'
import { setSignOutHandler } from '../api/authEvents'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const logout = useCallback(async () => {
    const refresh = await SecureStore.getItemAsync('refresh_token')
    try {
      if (refresh) await api.post('/auth/logout/', { refresh })
    } catch {
      // proceed even if blacklist fails
    }
    await SecureStore.deleteItemAsync('access_token')
    await SecureStore.deleteItemAsync('refresh_token')
    setUser(null)
  }, [])

  // Register the logout handler so the API client can trigger it on 401
  useEffect(() => {
    setSignOutHandler(logout)
  }, [logout])

  // Restore session on app launch
  useEffect(() => {
    const restore = async () => {
      const token = await SecureStore.getItemAsync('access_token')
      if (token) {
        try {
          const { data } = await api.get('/auth/me/')
          setUser(data)
        } catch {
          await SecureStore.deleteItemAsync('access_token')
          await SecureStore.deleteItemAsync('refresh_token')
        }
      }
      setLoading(false)
    }
    restore()
  }, [])

  const login = async (userData, accessToken, refreshToken) => {
    await SecureStore.setItemAsync('access_token', accessToken)
    await SecureStore.setItemAsync('refresh_token', refreshToken)
    setUser(userData)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
