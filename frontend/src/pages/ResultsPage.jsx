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
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    let cancelled = false
    let timer = null

    const fetchAnalysis = () => {
      api
        .get(`/analyses/${id}/`)
        .then(({ data }) => {
          if (cancelled) return
          setAnalysis(data)
          setLoading(false)

          // If still processing, poll every 4 seconds
          if (data.status === 'processing' || data.status === 'pending') {
            timer = setTimeout(fetchAnalysis, 4000)
          }
        })
        .catch((err) => {
          if (cancelled) return
          if (err.response?.status === 429) {
            // Rate-limited — back off and retry after 10 seconds instead of giving up
            timer = setTimeout(fetchAnalysis, 10000)
            return
          }
          setError('Could not load this analysis.')
          setLoading(false)
        })
    }

    setLoading(true)
    setError('')
    fetchAnalysis()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [id, retryCount])

  if (loading) return <Spinner />
  if (error) return <div className="text-center py-20 text-red-500 text-sm">{error}</div>
  if (!analysis) return null

  // Show loading state while analysis is still processing
  if (analysis.status === 'processing' || analysis.status === 'pending') {
    const stepLabels = {
      pending: 'Queued',
      pdf_extract: 'Extracting PDF text',
      jd_scrape: 'Fetching job description',
      llm_call: 'Analyzing with AI',
      parse_result: 'Processing results',
    }
    const stepOrder = ['pending', 'pdf_extract', 'jd_scrape', 'llm_call', 'parse_result']
    const currentIdx = stepOrder.indexOf(analysis.pipeline_step || 'pending')

    return (
      <div className="max-w-3xl mx-auto px-4 py-20 text-center space-y-6">
        <Spinner />
        <p className="text-gray-600 text-sm">Analyzing your resume... This may take a couple of minutes.</p>

        {/* Pipeline step progress */}
        <div className="max-w-sm mx-auto space-y-2">
          {stepOrder.map((step, idx) => {
            const isDone = idx < currentIdx
            const isCurrent = idx === currentIdx
            return (
              <div key={step} className="flex items-center gap-3 text-sm">
                <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                  isDone ? 'bg-green-500 text-white' : isCurrent ? 'bg-indigo-500 text-white animate-pulse' : 'bg-gray-200 text-gray-400'
                }`}>
                  {isDone ? '✓' : idx + 1}
                </div>
                <span className={isDone ? 'text-green-600' : isCurrent ? 'text-indigo-600 font-medium' : 'text-gray-400'}>
                  {stepLabels[step]}
                </span>
              </div>
            )
          })}
        </div>

        <p className="text-gray-400 text-xs">The page will update automatically when results are ready.</p>
      </div>
    )
  }

  // Show error state if analysis failed
  if (analysis.status === 'failed') {
    const handleRetry = async () => {
      try {
        await api.post(`/analyses/${id}/retry/`)
        // Bump retryCount to restart the polling useEffect
        setRetryCount((c) => c + 1)
      } catch (err) {
        setError(err.response?.data?.detail || 'Failed to retry analysis.')
      }
    }

    return (
      <div className="max-w-3xl mx-auto px-4 py-20 text-center space-y-4">
        <div className="bg-red-50 border border-red-200 rounded-2xl px-6 py-8">
          <p className="text-red-600 font-semibold mb-2">Analysis Failed</p>
          <p className="text-sm text-red-500">{analysis.error_message || 'An unexpected error occurred.'}</p>
          {analysis.pipeline_step && analysis.pipeline_step !== 'failed' && (
            <p className="text-xs text-red-400 mt-2">Failed at step: {analysis.pipeline_step}</p>
          )}
        </div>
        <div className="flex gap-3 justify-center mt-4">
          <button
            onClick={handleRetry}
            className="text-sm bg-indigo-600 text-white px-6 py-2 rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Retry
          </button>
          <Link
            to="/"
            className="text-sm border border-gray-300 text-gray-600 px-6 py-2 rounded-lg hover:bg-gray-50 transition-colors"
          >
            New Analysis
          </Link>
        </div>
      </div>
    )
  }

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
