import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import toast from 'react-hot-toast'

const JD_TABS = [
  { value: 'text', label: 'Paste text' },
  { value: 'url', label: 'Job URL' },
  { value: 'form', label: 'Fill form' },
]

const INITIAL_FORM = {
  jd_text: '',
  jd_url: '',
  jd_role: '',
  jd_company: '',
  jd_skills: '',
  jd_experience_years: '',
  jd_industry: '',
  jd_extra_details: '',
}

export default function AnalyzePage() {
  const [file, setFile] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [jdType, setJdType] = useState('text')
  const [form, setForm] = useState(INITIAL_FORM)
  const [loading, setLoading] = useState(false)
  const fileInputRef = useRef()
  const navigate = useNavigate()

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  const MAX_FILE_BYTES = 5 * 1024 * 1024

  const handleDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    const dropped = e.dataTransfer.files[0]
    if (!dropped) return
    if (dropped.type !== 'application/pdf') {
      toast.error('Only PDF files are accepted.')
      return
    }
    if (dropped.size > MAX_FILE_BYTES) {
      toast.error('File exceeds 5 MB limit.')
      return
    }
    setFile(dropped)
  }

  const handleFileInput = (e) => {
    const picked = e.target.files[0]
    if (!picked) return
    if (picked.size > MAX_FILE_BYTES) {
      toast.error('File exceeds 5 MB limit.')
      return
    }
    setFile(picked)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!file) { toast.error('Please upload a PDF resume.'); return }
    setLoading(true)

    const fd = new FormData()
    fd.append('resume_file', file)
    fd.append('jd_input_type', jdType)

    if (jdType === 'text') fd.append('jd_text', form.jd_text)
    if (jdType === 'url') fd.append('jd_url', form.jd_url)
    if (jdType === 'form') {
      ;['jd_role', 'jd_company', 'jd_skills', 'jd_industry', 'jd_extra_details'].forEach((k) => {
        if (form[k]) fd.append(k, form[k])
      })
      if (form.jd_experience_years) fd.append('jd_experience_years', form.jd_experience_years)
    }

    try {
      const { data } = await api.post('/analyze/', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      // Store optimistic entry so HistoryPage can show it immediately
      sessionStorage.setItem('optimistic_analysis', JSON.stringify({
        id: data.id,
        jd_role: form.jd_role || (jdType === 'url' ? 'Job via URL' : ''),
        jd_company: form.jd_company || '',
        status: 'processing',
        ats_score: null,
        created_at: new Date().toISOString(),
      }))
      toast.success('Analysis started!')
      navigate(`/results/${data.id}`)
    } catch (err) {
      const responseData = err.response?.data
      if (responseData?.detail) {
        toast.error(responseData.detail)
      } else if (responseData && typeof responseData === 'object') {
        toast.error(Object.values(responseData).flat().join(' '))
      } else if (err.response?.status === 429) {
        toast.error('Too many requests. Please wait before submitting another analysis.')
      } else {
        toast.error('An unexpected error occurred. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  const inputCls =
    'w-full border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-gray-100 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 placeholder:text-gray-400 dark:placeholder:text-gray-500'

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 sm:py-10">
      <h1 className="text-2xl sm:text-3xl font-bold text-gray-800 dark:text-gray-100 mb-1">Analyze Resume</h1>
      <p className="text-gray-500 dark:text-gray-400 text-sm mb-8">
        Upload your PDF resume and describe the job — get your ATS score and tailored optimization tips.
      </p>

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* ── Resume upload ── */}
        <section>
          <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
            Resume <span className="font-normal text-gray-400 dark:text-gray-500">(PDF only, max 5 MB)</span>
          </label>
          <div
            onDrop={handleDrop}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onClick={() => fileInputRef.current.click()}
            className={`border-2 border-dashed rounded-xl p-8 sm:p-10 text-center cursor-pointer transition-colors select-none ${
              dragging
                ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/20'
                : file
                ? 'border-green-400 bg-green-50 dark:bg-green-900/20'
                : 'border-gray-300 dark:border-slate-600 hover:border-indigo-300 dark:hover:border-indigo-500 hover:bg-gray-50 dark:hover:bg-slate-700/50'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              onChange={handleFileInput}
              className="hidden"
            />
            {file ? (
              <div>
                <p className="text-sm font-semibold text-green-700 dark:text-green-400">{file.name}</p>
                <p className="text-xs text-green-500 dark:text-green-500 mt-1">
                  {(file.size / 1024).toFixed(0)} KB &mdash; tap to replace
                </p>
              </div>
            ) : (
              <div>
                <p className="text-gray-500 dark:text-gray-400 text-sm">Drag & drop your PDF here</p>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">or tap to browse</p>
              </div>
            )}
          </div>
        </section>

        {/* ── Job description ── */}
        <section>
          <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
            Job Description
          </label>

          {/* Tab selector */}
          <div className="flex gap-2 mb-4 overflow-x-auto pb-1 -mx-1 px-1">
            {JD_TABS.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setJdType(t.value)}
                className={`px-4 py-1.5 rounded-full text-sm border font-medium transition-colors whitespace-nowrap ${
                  jdType === t.value
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'border-gray-300 dark:border-slate-600 text-gray-600 dark:text-gray-300 hover:border-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-400'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Text */}
          {jdType === 'text' && (
            <div>
              <textarea
                value={form.jd_text}
                onChange={set('jd_text')}
                placeholder="Paste the full job description here…"
                rows={7}
                className={`${inputCls} resize-y`}
                required
              />
              <div className="flex justify-end mt-1">
                <span className={`text-xs ${form.jd_text.length > 50 ? 'text-green-500 dark:text-green-400' : 'text-gray-400 dark:text-gray-500'}`}>
                  {form.jd_text.length} chars
                </span>
              </div>
            </div>
          )}

          {/* URL */}
          {jdType === 'url' && (
            <div className="space-y-2">
              <input
                type="url"
                value={form.jd_url}
                onChange={set('jd_url')}
                placeholder="https://company.com/careers/role-123"
                className={`${inputCls} ${form.jd_url && !/^https?:\/\/.+\..+/.test(form.jd_url) ? 'border-red-400 dark:border-red-500' : ''}`}
                required
              />
              {form.jd_url && !/^https?:\/\/.+\..+/.test(form.jd_url) ? (
                <p className="text-xs text-red-500 dark:text-red-400">Enter a valid URL starting with http:// or https://</p>
              ) : (
                <p className="text-xs text-gray-400 dark:text-gray-500">
                  We will scrape the page and extract the job description automatically.
                </p>
              )}
            </div>
          )}

          {/* Form */}
          {jdType === 'form' && (
            <div className="space-y-3">
              <input
                type="text"
                value={form.jd_role}
                onChange={set('jd_role')}
                placeholder="Job title / role *"
                className={inputCls}
                required
              />
              <input
                type="text"
                value={form.jd_company}
                onChange={set('jd_company')}
                placeholder="Company name"
                className={inputCls}
              />
              <input
                type="text"
                value={form.jd_skills}
                onChange={set('jd_skills')}
                placeholder="Required skills, comma-separated (e.g. Python, AWS, Docker)"
                className={inputCls}
              />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <input
                  type="number"
                  value={form.jd_experience_years}
                  onChange={set('jd_experience_years')}
                  placeholder="Years of experience"
                  min={0}
                  max={40}
                  className={inputCls}
                />
                <input
                  type="text"
                  value={form.jd_industry}
                  onChange={set('jd_industry')}
                  placeholder="Industry"
                  className={inputCls}
                />
              </div>
              <textarea
                value={form.jd_extra_details}
                onChange={set('jd_extra_details')}
                placeholder="Any other important details…"
                rows={3}
                className={`${inputCls} resize-y`}
              />
            </div>
          )}
        </section>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-indigo-600 text-white py-3 rounded-xl text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Analyzing your resume…
            </>
          ) : (
            'Analyze Resume'
          )}
        </button>
      </form>
    </div>
  )
}
