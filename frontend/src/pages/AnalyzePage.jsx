import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'

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
  const [error, setError] = useState('')
  const fileInputRef = useRef()
  const navigate = useNavigate()

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  const handleDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped?.type === 'application/pdf') {
      setFile(dropped)
      setError('')
    } else {
      setError('Only PDF files are accepted.')
    }
  }

  const handleFileInput = (e) => {
    const picked = e.target.files[0]
    if (picked) { setFile(picked); setError('') }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!file) { setError('Please upload a PDF resume.'); return }
    setError('')
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
      navigate(`/results/${data.id}`)
    } catch (err) {
      const errs = err.response?.data
      if (errs && typeof errs === 'object') {
        setError(Object.values(errs).flat().join(' '))
      } else {
        setError('Analysis failed. Ensure your API key is configured.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <h1 className="text-3xl font-bold text-gray-800 mb-1">Analyze Resume</h1>
      <p className="text-gray-500 text-sm mb-8">
        Upload your PDF resume and describe the job — get your ATS score and tailored optimization tips.
      </p>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl mb-6 text-sm">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* ── Resume upload ── */}
        <section>
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            Resume <span className="font-normal text-gray-400">(PDF only, max 5 MB)</span>
          </label>
          <div
            onDrop={handleDrop}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onClick={() => fileInputRef.current.click()}
            className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors select-none ${
              dragging
                ? 'border-indigo-400 bg-indigo-50'
                : file
                ? 'border-green-400 bg-green-50'
                : 'border-gray-300 hover:border-indigo-300 hover:bg-gray-50'
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
                <p className="text-sm font-semibold text-green-700">{file.name}</p>
                <p className="text-xs text-green-500 mt-1">
                  {(file.size / 1024).toFixed(0)} KB &mdash; click to replace
                </p>
              </div>
            ) : (
              <div>
                <p className="text-gray-500 text-sm">Drag & drop your PDF here</p>
                <p className="text-xs text-gray-400 mt-1">or click to browse</p>
              </div>
            )}
          </div>
        </section>

        {/* ── Job description ── */}
        <section>
          <label className="block text-sm font-semibold text-gray-700 mb-3">
            Job Description
          </label>

          {/* Tab selector */}
          <div className="flex gap-2 mb-4">
            {JD_TABS.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setJdType(t.value)}
                className={`px-4 py-1.5 rounded-full text-sm border font-medium transition-colors ${
                  jdType === t.value
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'border-gray-300 text-gray-600 hover:border-indigo-400 hover:text-indigo-600'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Text */}
          {jdType === 'text' && (
            <textarea
              value={form.jd_text}
              onChange={set('jd_text')}
              placeholder="Paste the full job description here…"
              rows={7}
              className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-y"
              required
            />
          )}

          {/* URL */}
          {jdType === 'url' && (
            <div className="space-y-2">
              <input
                type="url"
                value={form.jd_url}
                onChange={set('jd_url')}
                placeholder="https://company.com/careers/role-123"
                className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                required
              />
              <p className="text-xs text-gray-400">
                We will scrape the page and extract the job description automatically.
              </p>
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
                className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                required
              />
              <input
                type="text"
                value={form.jd_company}
                onChange={set('jd_company')}
                placeholder="Company name"
                className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <input
                type="text"
                value={form.jd_skills}
                onChange={set('jd_skills')}
                placeholder="Required skills, comma-separated (e.g. Python, AWS, Docker)"
                className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <div className="grid grid-cols-2 gap-3">
                <input
                  type="number"
                  value={form.jd_experience_years}
                  onChange={set('jd_experience_years')}
                  placeholder="Years of experience"
                  min={0}
                  max={40}
                  className="border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <input
                  type="text"
                  value={form.jd_industry}
                  onChange={set('jd_industry')}
                  placeholder="Industry"
                  className="border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              <textarea
                value={form.jd_extra_details}
                onChange={set('jd_extra_details')}
                placeholder="Any other important details…"
                rows={3}
                className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-y"
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
