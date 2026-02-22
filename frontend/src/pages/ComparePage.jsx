import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import toast from 'react-hot-toast'
import ScoreGauge from '../components/ScoreGauge'
import ScoreBar from '../components/ScoreBar'
import { HistorySkeleton } from '../components/Skeleton'

function CompareCard({ analysis }) {
  if (!analysis) return null
  const bd = analysis.ats_score_breakdown || {}
  const gaps = analysis.keyword_gaps || []

  return (
    <div className="flex-1 min-w-0 space-y-4">
      {/* Header */}
      <div className="text-center">
        <p className="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">
          {analysis.jd_role || 'Untitled'}
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
          {analysis.jd_company || 'Unknown company'} &middot;{' '}
          {new Date(analysis.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
        </p>
      </div>

      {/* Score */}
      <div className="flex justify-center">
        <ScoreGauge score={analysis.ats_score ?? 0} />
      </div>

      {/* Breakdown */}
      <div className="space-y-3">
        <ScoreBar label="Keywords" value={bd.keyword_match ?? 0} />
        <ScoreBar label="Format" value={bd.format_score ?? 0} />
        <ScoreBar label="Relevance" value={bd.relevance_score ?? 0} />
      </div>

      {/* Assessment */}
      {analysis.overall_assessment && (
        <div className="bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-800 rounded-xl p-3">
          <p className="text-xs text-gray-700 dark:text-gray-200 leading-relaxed line-clamp-4">
            {analysis.overall_assessment}
          </p>
        </div>
      )}

      {/* Keyword gaps */}
      {gaps.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-2">
            Missing Keywords <span className="text-red-500">({gaps.length})</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {gaps.map((kw) => (
              <span
                key={kw}
                className="bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800 px-2 py-0.5 rounded-full text-xs"
              >
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function ComparePage() {
  const [analyses, setAnalyses] = useState([])
  const [loading, setLoading] = useState(true)
  const [leftId, setLeftId] = useState('')
  const [rightId, setRightId] = useState('')
  const [left, setLeft] = useState(null)
  const [right, setRight] = useState(null)
  const [fetching, setFetching] = useState(false)

  useEffect(() => {
    api
      .get('/analyses/')
      .then(({ data }) => setAnalyses(data.filter((a) => a.status === 'done')))
      .finally(() => setLoading(false))
  }, [])

  const handleCompare = async () => {
    if (!leftId || !rightId) { toast.error('Select two analyses to compare.'); return }
    if (leftId === rightId) { toast.error('Pick two different analyses.'); return }
    setFetching(true)
    try {
      const [l, r] = await Promise.all([
        api.get(`/analyses/${leftId}/`),
        api.get(`/analyses/${rightId}/`),
      ])
      setLeft(l.data)
      setRight(r.data)
    } catch {
      toast.error('Failed to load analyses.')
    } finally {
      setFetching(false)
    }
  }

  if (loading) return <HistorySkeleton />

  const selectCls =
    'w-full border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'

  const optionLabel = (a) =>
    `${a.jd_role || 'Untitled'} — ${a.jd_company || '?'} (${a.ats_score ?? '?'})`

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 sm:py-10">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">Compare Analyses</h1>
        <Link
          to="/history"
          className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          &larr; History
        </Link>
      </div>

      {analyses.length < 2 ? (
        <div className="text-center py-16">
          <p className="text-gray-500 dark:text-gray-400 text-sm">
            You need at least 2 completed analyses to compare.
          </p>
          <Link to="/" className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline mt-2 inline-block">
            Run an analysis
          </Link>
        </div>
      ) : (
        <>
          {/* Selectors */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Analysis A</label>
              <select className={selectCls} value={leftId} onChange={(e) => setLeftId(e.target.value)}>
                <option value="">Select…</option>
                {analyses.map((a) => (
                  <option key={a.id} value={a.id}>{optionLabel(a)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Analysis B</label>
              <select className={selectCls} value={rightId} onChange={(e) => setRightId(e.target.value)}>
                <option value="">Select…</option>
                {analyses.map((a) => (
                  <option key={a.id} value={a.id}>{optionLabel(a)}</option>
                ))}
              </select>
            </div>
          </div>

          <button
            onClick={handleCompare}
            disabled={!leftId || !rightId || fetching}
            className="w-full sm:w-auto bg-indigo-600 text-white px-6 py-2.5 rounded-xl text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-colors mb-8"
          >
            {fetching ? 'Loading…' : 'Compare'}
          </button>

          {/* Side by side */}
          {left && right && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 sm:gap-8">
              <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 p-4 sm:p-5">
                <CompareCard analysis={left} />
              </div>
              <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 p-4 sm:p-5">
                <CompareCard analysis={right} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
