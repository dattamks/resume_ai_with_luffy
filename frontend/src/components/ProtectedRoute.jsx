import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  // Auth loading gate is handled at App level, so loading should be false here.
  // But keep fallback just in case.
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />
  return children
}
