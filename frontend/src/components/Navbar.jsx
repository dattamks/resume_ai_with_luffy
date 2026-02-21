import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const navLink = (to, label) => (
    <Link
      to={to}
      className={`text-sm transition-colors ${
        pathname === to
          ? 'text-indigo-600 font-medium'
          : 'text-gray-500 hover:text-indigo-600'
      }`}
    >
      {label}
    </Link>
  )

  return (
    <nav className="bg-white border-b border-gray-200 sticky top-0 z-10">
      <div className="max-w-4xl mx-auto px-4 h-14 flex items-center justify-between">
        <Link to="/" className="text-lg font-bold text-indigo-600 tracking-tight">
          Resume AI
        </Link>

        {user ? (
          <div className="flex items-center gap-6">
            {navLink('/', 'Analyze')}
            {navLink('/history', 'History')}
            <span className="text-xs text-gray-400 border-l border-gray-200 pl-4">
              {user.username}
            </span>
            <button
              onClick={handleLogout}
              className="text-sm text-red-400 hover:text-red-600 transition-colors"
            >
              Logout
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <Link
              to="/login"
              className="text-sm text-gray-600 hover:text-indigo-600"
            >
              Login
            </Link>
            <Link
              to="/register"
              className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 transition-colors"
            >
              Register
            </Link>
          </div>
        )}
      </div>
    </nav>
  )
}
