import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../api/client'
import Spinner from '../components/Spinner'

// ── Sub-components ────────────────────────────────────────────────────────────

function ScoreGauge({ score }) {
  const radius = 52
  const stroke = 11
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference
  const color = score >= 75 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#ef4444'
  const label = score >= 75 ? 'Strong match' : score >= 50 ? 'Moderate match' : 'Needs work'

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="136" height="136" viewBox="0 0 136 136">
        <circle cx="68" cy="68" r={radius} fill="none" stroke="#f3f4f6" strokeWidth={stroke} />
        <circle
          cx="68" cy="68" r={radius} fill="none"
          stroke={color} strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 68 68)"
          style={{ transition: 'stroke-dashoffset 1s cubic-bezier(.4,0,.2,1)' }}
        />
        <text x="68" y="64" dominantBaseline="middle" textAnchor="middle" fontSize="30" fontWeight="700" fill="#111827">
          {score}
        </text>
        <text x="68" y="84" dominantBaseline="middle" textAnchor="middle" fontSize="11" fill="#9ca3af">
          / 100
        </text>
      </svg>
      <span className="text-xs font-semibold" style={{ color }}>{label}</span>
    </div>
  )
}

function ScoreBar({ label, value }) {
  const bg = value >= 75 ? 'bg-green-500' : value >= 50 ? 'bg-amber-400' : 'bg-red-400'
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{label}</span>
        <span className="font-medium text-gray-700">{value}</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={`h-full ${bg} rounded-full`}
          style={{ width: `${value}%`, transition: 'width 1s cubic-bezier(.4,0,.2,1)' }}
        />
      </div>
    </div>
  )
}

function SectionAccordion({ sections }) {
  const [open, setOpen] = useState(null)
  const entries = Object.entries(sections)
  return (
    <div className="divide-y divide-gray-100">
      {entries.map(([key, text]) => (
        <div key={key}>
          <button
            onClick={() => setOpen(open === key ? null : key)}
            className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-50 transition-colors"
          >
            <span className="text-xs font-semibold text-indigo-600 uppercase tracking-wide">{key}</span>
            <svg
              className={`h-4 w-4 text-gray-400 transition-transform ${open === key ? 'rotate-180' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {open === key && (
            <div className="px-5 pb-4">
              <p className="text-sm text-gray-700 leading-relaxed">{text}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ResultsPage() {
  const { id } = useParams()
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get(`/analyses/${id}/`)
      .then(({ data }) => setAnalysis(data))
      .catch(() => setError('Could not load this analysis.'))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <Spinner />
  if (error) return <div className="text-center py-20 text-red-500 text-sm">{error}</div>
  if (!analysis) return null

  const bd = analysis.ats_score_breakdown || {}
  const sections = analysis.section_suggestions || {}
  const bullets = analysis.rewritten_bullets || []
  const gaps = analysis.keyword_gaps || []

  return (
    <div className="max-w-3xl mx-auto px-4 py-10 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Analysis Results</h1>
          {(analysis.jd_role || analysis.jd_company) && (
            <p className="text-gray-500 text-sm mt-1">
              {[analysis.jd_role, analysis.jd_company].filter(Boolean).join(' at ')}
            </p>
          )}
          <p className="text-xs text-gray-400 mt-0.5">
            {new Date(analysis.created_at).toLocaleString()} &middot; via {analysis.ai_provider_used}
          </p>
        </div>
        <Link
          to="/"
          className="shrink-0 text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 transition-colors"
        >
          + New
        </Link>
      </div>

      {/* Score card */}
      <div className="bg-white rounded-2xl border border-gray-200 p-6 flex flex-col sm:flex-row gap-8 items-center">
        <ScoreGauge score={analysis.ats_score ?? 0} />
        <div className="flex-1 w-full space-y-4">
          <p className="text-sm font-semibold text-gray-700">Score Breakdown</p>
          <ScoreBar label="Keyword Match" value={bd.keyword_match ?? 0} />
          <ScoreBar label="Format & Structure" value={bd.format_score ?? 0} />
          <ScoreBar label="Relevance" value={bd.relevance_score ?? 0} />
        </div>
      </div>

      {/* Overall assessment */}
      {analysis.overall_assessment && (
        <div className="bg-indigo-50 border border-indigo-100 rounded-2xl px-5 py-4">
          <p className="text-xs font-semibold text-indigo-500 uppercase tracking-wide mb-2">
            Overall Assessment
          </p>
          <p className="text-sm text-gray-800 leading-relaxed">{analysis.overall_assessment}</p>
        </div>
      )}

      {/* Keyword gaps */}
      {gaps.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 px-5 py-4">
          <p className="text-sm font-semibold text-gray-700 mb-3">
            Missing Keywords
            <span className="ml-2 bg-red-100 text-red-600 text-xs font-semibold px-2 py-0.5 rounded-full">
              {gaps.length}
            </span>
          </p>
          <div className="flex flex-wrap gap-2">
            {gaps.map((kw) => (
              <span
                key={kw}
                className="bg-red-50 text-red-700 border border-red-200 px-3 py-1 rounded-full text-xs font-medium"
              >
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Section suggestions */}
      {Object.keys(sections).length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-700">Section-by-Section Suggestions</p>
          </div>
          <SectionAccordion sections={sections} />
        </div>
      )}

      {/* Rewritten bullets */}
      {bullets.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 px-5 py-4">
          <p className="text-sm font-semibold text-gray-700 mb-4">
            Rewritten Bullet Points
            <span className="ml-2 bg-green-100 text-green-700 text-xs font-semibold px-2 py-0.5 rounded-full">
              {bullets.length}
            </span>
          </p>
          <div className="space-y-4">
            {bullets.map((item, i) => (
              <div key={i} className="rounded-xl bg-gray-50 border border-gray-200 p-4 space-y-3">
                <div>
                  <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">
                    Original
                  </p>
                  <p className="text-sm text-gray-500 line-through">{item.original}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold text-green-500 uppercase tracking-wide mb-1">
                    Improved
                  </p>
                  <p className="text-sm text-gray-800 font-medium">{item.rewritten}</p>
                </div>
                {item.reason && (
                  <p className="text-xs text-gray-400 italic border-t border-gray-200 pt-2">
                    {item.reason}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3 pt-2">
        <Link
          to="/"
          className="flex-1 text-center bg-indigo-600 text-white py-2.5 rounded-xl text-sm font-semibold hover:bg-indigo-700 transition-colors"
        >
          Analyze Another
        </Link>
        <Link
          to="/history"
          className="flex-1 text-center border border-gray-300 text-gray-700 py-2.5 rounded-xl text-sm font-semibold hover:bg-gray-50 transition-colors"
        >
          View History
        </Link>
      </div>
    </div>
  )
}
