import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { HistorySkeleton } from '../components/Skeleton'

function MiniBar({ value, max, color }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-200 dark:bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 dark:text-gray-400 w-6 text-right">{value}</span>
    </div>
  )
}

export default function DashboardPage() {
  const [analyses, setAnalyses] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/analyses/').then(({ data }) => setAnalyses(data)).finally(() => setLoading(false))
  }, [])

  if (loading) return <HistorySkeleton />

  const done = analyses.filter((a) => a.status === 'done' && a.ats_score != null)

  // Score stats
  const scores = done.map((a) => a.ats_score)
  const avgScore = scores.length ? Math.round(scores.reduce((s, v) => s + v, 0) / scores.length) : 0
  const bestScore = scores.length ? Math.max(...scores) : 0
  const latestScore = done.length ? done[0].ats_score : 0

  // Score distribution
  const high = done.filter((a) => a.ats_score >= 75).length
  const mid = done.filter((a) => a.ats_score >= 50 && a.ats_score < 75).length
  const low = done.filter((a) => a.ats_score < 50).length

  // Score trend (last 10, oldest first)
  const trend = done.slice(0, 10).reverse()
  const trendMax = trend.length > 0 ? Math.max(...trend.map((a) => a.ats_score), 100) : 100

  // Common keyword gaps
  const gapMap = {}
  done.forEach((a) => {
    ;(a.keyword_gaps || []).forEach((kw) => {
      gapMap[kw] = (gapMap[kw] || 0) + 1
    })
  })
  const topGaps = Object.entries(gapMap)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
  const maxGap = topGaps.length ? topGaps[0][1] : 1

  const statCard = (label, value, sub) => (
    <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 p-4 sm:p-5 text-center">
      <p className="text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-800 dark:text-gray-100">{value}</p>
      {sub && <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{sub}</p>}
    </div>
  )

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 sm:py-10 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">Dashboard</h1>
        <Link to="/history" className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline">
          &larr; History
        </Link>
      </div>

      {done.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-gray-500 dark:text-gray-400 text-sm">No completed analyses yet.</p>
          <Link to="/" className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline mt-2 inline-block">
            Run your first analysis
          </Link>
        </div>
      ) : (
        <>
          {/* Stats cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
            {statCard('Total Analyses', done.length)}
            {statCard('Average Score', avgScore)}
            {statCard('Best Score', bestScore)}
            {statCard('Latest Score', latestScore)}
          </div>

          {/* Score distribution */}
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 p-4 sm:p-5">
            <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">Score Distribution</p>
            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-green-600 dark:text-green-400 font-medium">High (75–100)</span>
                  <span className="text-gray-500 dark:text-gray-400">{high}</span>
                </div>
                <div className="h-3 bg-gray-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div className="h-full bg-green-500 rounded-full transition-all" style={{ width: `${done.length ? (high / done.length) * 100 : 0}%` }} />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-amber-600 dark:text-amber-400 font-medium">Medium (50–74)</span>
                  <span className="text-gray-500 dark:text-gray-400">{mid}</span>
                </div>
                <div className="h-3 bg-gray-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div className="h-full bg-amber-400 rounded-full transition-all" style={{ width: `${done.length ? (mid / done.length) * 100 : 0}%` }} />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-red-600 dark:text-red-400 font-medium">Low (&lt;50)</span>
                  <span className="text-gray-500 dark:text-gray-400">{low}</span>
                </div>
                <div className="h-3 bg-gray-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div className="h-full bg-red-400 rounded-full transition-all" style={{ width: `${done.length ? (low / done.length) * 100 : 0}%` }} />
                </div>
              </div>
            </div>
          </div>

          {/* Score trend */}
          {trend.length >= 2 && (
            <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 p-4 sm:p-5">
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">Score Trend (Last {trend.length})</p>
              <div className="flex items-end gap-1.5 sm:gap-2 h-32">
                {trend.map((a, i) => {
                  const h = Math.max((a.ats_score / trendMax) * 100, 4)
                  const color = a.ats_score >= 75 ? 'bg-green-500' : a.ats_score >= 50 ? 'bg-amber-400' : 'bg-red-400'
                  return (
                    <div key={i} className="flex-1 flex flex-col items-center justify-end h-full">
                      <span className="text-[10px] text-gray-500 dark:text-gray-400 mb-1">{a.ats_score}</span>
                      <div className={`w-full rounded-t ${color}`} style={{ height: `${h}%` }} />
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Common keyword gaps */}
          {topGaps.length > 0 && (
            <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 p-4 sm:p-5">
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">
                Most Common Missing Keywords
              </p>
              <div className="space-y-2">
                {topGaps.map(([kw, count]) => (
                  <div key={kw} className="flex items-center gap-3">
                    <span className="text-xs text-gray-700 dark:text-gray-300 w-28 sm:w-36 truncate font-medium">
                      {kw}
                    </span>
                    <div className="flex-1">
                      <MiniBar value={count} max={maxGap} color="bg-red-400" />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
