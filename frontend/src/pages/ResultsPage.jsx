import { useEffect, useState, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../api/client'
import toast from 'react-hot-toast'
import confetti from 'canvas-confetti'
import Spinner from '../components/Spinner'
import { ResultsSkeleton } from '../components/Skeleton'
import ScoreGauge from '../components/ScoreGauge'
import ScoreBar from '../components/ScoreBar'
import SectionAccordion from '../components/SectionAccordion'

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ResultsPage() {
  const { id } = useParams()
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retryCount, setRetryCount] = useState(0)
  const confettiFired = useRef(false)

  // Fire confetti for high scores
  useEffect(() => {
    if (
      analysis?.status === 'done' &&
      analysis.ats_score >= 85 &&
      !confettiFired.current
    ) {
      confettiFired.current = true
      const duration = 2000
      const end = Date.now() + duration
      const frame = () => {
        confetti({ particleCount: 3, angle: 60, spread: 55, origin: { x: 0 } })
        confetti({ particleCount: 3, angle: 120, spread: 55, origin: { x: 1 } })
        if (Date.now() < end) requestAnimationFrame(frame)
      }
      frame()
    }
  }, [analysis])

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

          if (data.status === 'processing' || data.status === 'pending') {
            timer = setTimeout(fetchAnalysis, 4000)
          }
        })
        .catch((err) => {
          if (cancelled) return
          if (err.response?.status === 429) {
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

  if (loading) return <ResultsSkeleton />
  if (error) return <div className="text-center py-20 text-red-500 dark:text-red-400 text-sm">{error}</div>
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
      <div className="max-w-3xl mx-auto px-4 py-16 sm:py-20 text-center space-y-6">
        <Spinner />
        <p className="text-gray-600 dark:text-gray-400 text-sm">Analyzing your resume... This may take a couple of minutes.</p>

        {/* Pipeline step progress */}
        <div className="max-w-xs sm:max-w-sm mx-auto space-y-2">
          {stepOrder.map((step, idx) => {
            const isDone = idx < currentIdx
            const isCurrent = idx === currentIdx
            return (
              <div key={step} className="flex items-center gap-3 text-sm">
                <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                  isDone ? 'bg-green-500 text-white' : isCurrent ? 'bg-indigo-500 text-white animate-pulse' : 'bg-gray-200 dark:bg-slate-700 text-gray-400 dark:text-gray-500'
                }`}>
                  {isDone ? '✓' : idx + 1}
                </div>
                <span className={isDone ? 'text-green-600 dark:text-green-400' : isCurrent ? 'text-indigo-600 dark:text-indigo-400 font-medium' : 'text-gray-400 dark:text-gray-500'}>
                  {stepLabels[step]}
                </span>
              </div>
            )
          })}
        </div>

        <p className="text-gray-400 dark:text-gray-500 text-xs">The page will update automatically when results are ready.</p>
      </div>
    )
  }

  // Show error state if analysis failed
  if (analysis.status === 'failed') {
    const handleRetry = async () => {
      try {
        await api.post(`/analyses/${id}/retry/`)
        toast.success('Retrying analysis...')
        setRetryCount((c) => c + 1)
      } catch (err) {
        toast.error(err.response?.data?.detail || 'Failed to retry analysis.')
      }
    }

    return (
      <div className="max-w-3xl mx-auto px-4 py-16 sm:py-20 text-center space-y-4">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-2xl px-5 sm:px-6 py-8">
          <p className="text-red-600 dark:text-red-400 font-semibold mb-2">Analysis Failed</p>
          <p className="text-sm text-red-500 dark:text-red-400">{analysis.error_message || 'An unexpected error occurred.'}</p>
          {analysis.pipeline_step && analysis.pipeline_step !== 'failed' && (
            <p className="text-xs text-red-400 dark:text-red-500 mt-2">Failed at step: {analysis.pipeline_step}</p>
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
            className="text-sm border border-gray-300 dark:border-slate-600 text-gray-600 dark:text-gray-300 px-6 py-2 rounded-lg hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
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
    <div className="max-w-3xl mx-auto px-4 py-8 sm:py-10 space-y-5 sm:space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 sm:gap-4">
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold text-gray-800 dark:text-gray-100">Analysis Results</h1>
          {(analysis.jd_role || analysis.jd_company) && (
            <p className="text-gray-500 dark:text-gray-400 text-sm mt-1 truncate">
              {[analysis.jd_role, analysis.jd_company].filter(Boolean).join(' at ')}
            </p>
          )}
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
            {new Date(analysis.created_at).toLocaleString()} &middot; via {analysis.ai_provider_used}
          </p>
        </div>
        <Link
          to="/"
          className="shrink-0 text-sm bg-indigo-600 text-white px-3 sm:px-4 py-1.5 rounded-lg hover:bg-indigo-700 transition-colors"
        >
          + New
        </Link>
      </div>

      {/* Score card */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 p-5 sm:p-6 flex flex-col sm:flex-row gap-6 sm:gap-8 items-center">
        <ScoreGauge score={analysis.ats_score ?? 0} />
        <div className="flex-1 w-full space-y-4">
          <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">Score Breakdown</p>
          <ScoreBar label="Keyword Match" value={bd.keyword_match ?? 0} />
          <ScoreBar label="Format & Structure" value={bd.format_score ?? 0} />
          <ScoreBar label="Relevance" value={bd.relevance_score ?? 0} />
        </div>
      </div>

      {/* Overall assessment */}
      {analysis.overall_assessment && (
        <div className="bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-800 rounded-2xl px-4 sm:px-5 py-4">
          <p className="text-xs font-semibold text-indigo-500 dark:text-indigo-400 uppercase tracking-wide mb-2">
            Overall Assessment
          </p>
          <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed">{analysis.overall_assessment}</p>
        </div>
      )}

      {/* Keyword gaps */}
      {gaps.length > 0 && (
        <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 px-4 sm:px-5 py-4">
          <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
            Missing Keywords
            <span className="ml-2 bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-xs font-semibold px-2 py-0.5 rounded-full">
              {gaps.length}
            </span>
          </p>
          <div className="flex flex-wrap gap-2">
            {gaps.map((kw) => (
              <span
                key={kw}
                className="bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800 px-3 py-1 rounded-full text-xs font-medium"
              >
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Section suggestions */}
      {Object.keys(sections).length > 0 && (
        <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 overflow-hidden">
          <div className="px-4 sm:px-5 py-4 border-b border-gray-100 dark:border-slate-700">
            <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">Section-by-Section Suggestions</p>
          </div>
          <SectionAccordion sections={sections} />
        </div>
      )}

      {/* Rewritten bullets */}
      {bullets.length > 0 && (
        <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 px-4 sm:px-5 py-4">
          <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">
            Rewritten Bullet Points
            <span className="ml-2 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-xs font-semibold px-2 py-0.5 rounded-full">
              {bullets.length}
            </span>
          </p>
          <div className="space-y-4">
            {bullets.map((item, i) => (
              <div key={i} className="rounded-xl bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 p-3 sm:p-4 space-y-3">
                <div>
                  <p className="text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">
                    Original
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400 line-through">{item.original}</p>
                </div>
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-[10px] font-semibold text-green-500 dark:text-green-400 uppercase tracking-wide mb-1">
                        Improved
                      </p>
                      <p className="text-sm text-gray-800 dark:text-gray-100 font-medium">{item.rewritten}</p>
                    </div>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(item.rewritten)
                        toast.success('Copied to clipboard!')
                      }}
                      className="shrink-0 mt-1 p-1.5 rounded-lg text-gray-300 dark:text-gray-600 hover:text-indigo-500 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors"
                      aria-label="Copy improved bullet"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    </button>
                  </div>
                </div>
                {item.reason && (
                  <p className="text-xs text-gray-400 dark:text-gray-500 italic border-t border-gray-200 dark:border-slate-700 pt-2">
                    {item.reason}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-col sm:flex-row gap-3 pt-2">
        <button
          onClick={async () => {
            try {
              const res = await api.get(`/analyses/${id}/export-pdf/`, { responseType: 'blob' })
              const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
              const a = document.createElement('a')
              a.href = url
              a.download = `resume_ai_report_${id}.pdf`
              a.click()
              window.URL.revokeObjectURL(url)
              toast.success('PDF downloaded!')
            } catch {
              toast.error('Failed to generate PDF.')
            }
          }}
          className="flex-1 text-center border border-indigo-600 text-indigo-600 dark:text-indigo-400 dark:border-indigo-400 py-2.5 rounded-xl text-sm font-semibold hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors flex items-center justify-center gap-2"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          Download PDF
        </button>
        <Link
          to="/"
          className="flex-1 text-center bg-indigo-600 text-white py-2.5 rounded-xl text-sm font-semibold hover:bg-indigo-700 transition-colors"
        >
          Analyze Another
        </Link>
        <Link
          to="/history"
          className="flex-1 text-center border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-gray-300 py-2.5 rounded-xl text-sm font-semibold hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
        >
          View History
        </Link>
      </div>
    </div>
  )
}
