import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import Spinner from '../components/Spinner'

function ScorePill({ score }) {
  if (score == null) return <span className="text-xs text-gray-400">—</span>
  const cls =
    score >= 75
      ? 'bg-green-100 text-green-700'
      : score >= 50
      ? 'bg-amber-100 text-amber-700'
      : 'bg-red-100 text-red-700'
  return (
    <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${cls}`}>{score}</span>
  )
}

function StatusDot({ status }) {
  const map = {
    done: 'bg-green-400',
    processing: 'bg-blue-400 animate-pulse',
    pending: 'bg-gray-300',
    failed: 'bg-red-400',
  }
  return (
    <span className="flex items-center gap-1.5 text-xs text-gray-500 capitalize">
      <span className={`h-1.5 w-1.5 rounded-full ${map[status] || 'bg-gray-300'}`} />
      {status}
    </span>
  )
}

export default function HistoryPage() {
  const [analyses, setAnalyses] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/analyses/').then(({ data }) => setAnalyses(data)).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner />

  // Quick stats
  const done = analyses.filter((a) => a.status === 'done')
  const avgScore =
    done.length > 0
      ? Math.round(done.reduce((s, a) => s + (a.ats_score || 0), 0) / done.length)
      : null
  const best = done.length > 0 ? Math.max(...done.map((a) => a.ats_score || 0)) : null

  return (
    <div className="max-w-3xl mx-auto px-4 py-10">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">History</h1>
        <Link
          to="/"
          className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 transition-colors"
        >
          + New analysis
        </Link>
      </div>

      {/* Stats */}
      {done.length > 0 && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          {[
            { label: 'Total', value: analyses.length },
            { label: 'Avg score', value: avgScore ?? '—' },
            { label: 'Best score', value: best ?? '—' },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white rounded-2xl border border-gray-200 px-4 py-4 text-center">
              <p className="text-2xl font-bold text-gray-800">{value}</p>
              <p className="text-xs text-gray-400 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      )}

      {/* List */}
      {analyses.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <p className="text-base mb-3">No analyses yet.</p>
          <Link to="/" className="text-indigo-600 hover:underline text-sm">
            Analyze your first resume
          </Link>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-gray-200 divide-y divide-gray-100 overflow-hidden">
          {analyses.map((a) => (
            <Link
              key={a.id}
              to={`/results/${a.id}`}
              className="flex items-center px-5 py-4 hover:bg-gray-50 transition-colors group"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-800 truncate">
                  {a.jd_role || 'Untitled role'}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-gray-400">
                    {a.jd_company || 'Unknown company'}
                  </span>
                  <span className="text-gray-300 text-xs">&middot;</span>
                  <span className="text-xs text-gray-400">
                    {new Date(a.created_at).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-3 ml-4 shrink-0">
                <StatusDot status={a.status} />
                <ScorePill score={a.ats_score} />
                <svg
                  className="h-4 w-4 text-gray-300 group-hover:text-gray-400 transition-colors"
                  fill="none" viewBox="0 0 24 24" stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
