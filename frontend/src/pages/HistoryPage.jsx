import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import toast from 'react-hot-toast'
import { HistorySkeleton } from '../components/Skeleton'
import ScorePill from '../components/ScorePill'
import StatusDot from '../components/StatusDot'

export default function HistoryPage() {
  const [analyses, setAnalyses] = useState([])
  const [loading, setLoading] = useState(true)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [search, setSearch] = useState('')
  const [scoreFilter, setScoreFilter] = useState('all')   // all | high | mid | low
  const [sortBy, setSortBy] = useState('newest')           // newest | oldest | score-high | score-low

  useEffect(() => {
    api.get('/analyses/').then(({ data }) => {
      setAnalyses(data)
      // Clear optimistic entry once real data has loaded
      sessionStorage.removeItem('optimistic_analysis')
    }).finally(() => setLoading(false))

    // Prepend optimistic entry if present (user just submitted an analysis)
    const opt = sessionStorage.getItem('optimistic_analysis')
    if (opt) {
      try {
        const entry = JSON.parse(opt)
        setAnalyses((prev) => prev.some((a) => a.id === entry.id) ? prev : [entry, ...prev])
      } catch { /* ignore bad JSON */ }
    }
  }, [])

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.delete(`/analyses/${deleteTarget}/delete/`)
      setAnalyses((prev) => prev.filter((a) => a.id !== deleteTarget))
      toast.success('Analysis deleted.')
    } catch {
      toast.error('Failed to delete analysis.')
    } finally {
      setDeleting(false)
      setDeleteTarget(null)
    }
  }

  if (loading) return <HistorySkeleton />

  // Quick stats
  const done = analyses.filter((a) => a.status === 'done')
  const avgScore =
    done.length > 0
      ? Math.round(done.reduce((s, a) => s + (a.ats_score || 0), 0) / done.length)
      : null
  const best = done.length > 0 ? Math.max(...done.map((a) => a.ats_score || 0)) : null

  // Filter & sort
  const filtered = analyses
    .filter((a) => {
      if (search) {
        const q = search.toLowerCase()
        const role = (a.jd_role || '').toLowerCase()
        const company = (a.jd_company || '').toLowerCase()
        if (!role.includes(q) && !company.includes(q)) return false
      }
      if (scoreFilter === 'high' && (a.ats_score == null || a.ats_score < 75)) return false
      if (scoreFilter === 'mid' && (a.ats_score == null || a.ats_score < 50 || a.ats_score >= 75)) return false
      if (scoreFilter === 'low' && (a.ats_score == null || a.ats_score >= 50)) return false
      return true
    })
    .sort((a, b) => {
      if (sortBy === 'oldest') return new Date(a.created_at) - new Date(b.created_at)
      if (sortBy === 'score-high') return (b.ats_score || 0) - (a.ats_score || 0)
      if (sortBy === 'score-low') return (a.ats_score || 0) - (b.ats_score || 0)
      return new Date(b.created_at) - new Date(a.created_at) // newest
    })

  const selectCls = 'border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-300 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500'

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 sm:py-10">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">History</h1>
        <div className="flex items-center gap-2">
          <Link
            to="/compare"
            className="text-sm border border-gray-300 dark:border-slate-600 text-gray-600 dark:text-gray-300 px-3 py-1.5 rounded-lg hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
          >
            Compare
          </Link>
          <Link
            to="/"
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 transition-colors"
          >
            + New analysis
          </Link>
        </div>
      </div>

      {/* Stats */}
      {done.length > 0 && (
        <div className="grid grid-cols-3 gap-3 sm:gap-4 mb-6">
          {[
            { label: 'Total', value: analyses.length },
            { label: 'Avg score', value: avgScore ?? '—' },
            { label: 'Best score', value: best ?? '—' },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 px-3 sm:px-4 py-4 text-center">
              <p className="text-xl sm:text-2xl font-bold text-gray-800 dark:text-gray-100">{value}</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Search & filter bar */}
      {analyses.length > 0 && (
        <div className="flex flex-col sm:flex-row gap-2 sm:gap-3 mb-4">
          <div className="relative flex-1">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search role or company..."
              className="w-full border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-gray-100 rounded-lg pl-9 pr-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 placeholder:text-gray-400 dark:placeholder:text-gray-500"
            />
          </div>
          <div className="flex gap-2">
            <select value={scoreFilter} onChange={(e) => setScoreFilter(e.target.value)} className={selectCls}>
              <option value="all">All scores</option>
              <option value="high">75+ (Strong)</option>
              <option value="mid">50–74 (Moderate)</option>
              <option value="low">&lt;50 (Needs work)</option>
            </select>
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className={selectCls}>
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="score-high">Score: High → Low</option>
              <option value="score-low">Score: Low → High</option>
            </select>
          </div>
        </div>
      )}

      {/* List */}
      {filtered.length === 0 && analyses.length > 0 ? (
        <div className="text-center py-16 text-gray-400 dark:text-gray-500">
          <p className="text-sm">No analyses match your filters.</p>
        </div>
      ) : analyses.length === 0 ? (
        <div className="text-center py-20 text-gray-400 dark:text-gray-500">
          <p className="text-base mb-3">No analyses yet.</p>
          <Link to="/" className="text-indigo-600 dark:text-indigo-400 hover:underline text-sm">
            Analyze your first resume
          </Link>
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 divide-y divide-gray-100 dark:divide-slate-700 overflow-hidden">
          {filtered.map((a) => (
            <div
              key={a.id}
              className="flex items-center px-4 sm:px-5 py-4 hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors group"
            >
              <Link to={`/results/${a.id}`} className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">
                  {a.jd_role || 'Untitled role'}
                </p>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    {a.jd_company || 'Unknown company'}
                  </span>
                  <span className="text-gray-300 dark:text-gray-600 text-xs">&middot;</span>
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    {new Date(a.created_at).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}
                  </span>
                </div>
              </Link>
              <div className="flex items-center gap-2 sm:gap-3 ml-3 sm:ml-4 shrink-0">
                <StatusDot status={a.status} />
                <ScorePill score={a.ats_score} />
                {a.status === 'done' && (
                  <button
                    onClick={async (e) => {
                      e.preventDefault()
                      try {
                        const res = await api.get(`/analyses/${a.id}/export-pdf/`, { responseType: 'blob' })
                        const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
                        const link = document.createElement('a')
                        link.href = url
                        link.download = `resume_ai_report_${a.id}.pdf`
                        link.click()
                        window.URL.revokeObjectURL(url)
                        toast.success('PDF downloaded!')
                      } catch {
                        toast.error('Failed to generate PDF.')
                      }
                    }}
                    className="p-1.5 rounded-lg text-gray-300 dark:text-gray-600 hover:text-indigo-500 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors sm:opacity-0 sm:group-hover:opacity-100"
                    aria-label="Download PDF"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  </button>
                )}
                <button
                  onClick={(e) => { e.preventDefault(); setDeleteTarget(a.id) }}
                  className="p-1.5 rounded-lg text-gray-300 dark:text-gray-600 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors sm:opacity-0 sm:group-hover:opacity-100"
                  aria-label="Delete analysis"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <div className="absolute inset-0 bg-black/40 dark:bg-black/60" onClick={() => !deleting && setDeleteTarget(null)} />
          <div className="relative bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 shadow-xl p-6 max-w-sm w-full text-center space-y-4">
            <div className="mx-auto w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
              <svg className="h-6 w-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100">Delete Analysis?</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">This action cannot be undone.</p>
            <div className="flex gap-3">
              <button
                onClick={() => setDeleteTarget(null)}
                disabled={deleting}
                className="flex-1 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-gray-300 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="flex-1 bg-red-600 text-white py-2 rounded-lg text-sm font-medium hover:bg-red-700 transition-colors disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
