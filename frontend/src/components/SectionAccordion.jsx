import { useState } from 'react'

export default function SectionAccordion({ sections }) {
  const [open, setOpen] = useState(null)
  const entries = Object.entries(sections)
  return (
    <div className="divide-y divide-gray-100 dark:divide-slate-700" role="region" aria-label="Section suggestions">
      {entries.map(([key, text]) => {
        const isOpen = open === key
        const panelId = `accordion-panel-${key.replace(/\s+/g, '-')}`
        const btnId = `accordion-btn-${key.replace(/\s+/g, '-')}`
        return (
          <div key={key}>
            <button
              id={btnId}
              onClick={() => setOpen(isOpen ? null : key)}
              aria-expanded={isOpen}
              aria-controls={panelId}
              className="w-full flex items-center justify-between px-4 sm:px-5 py-4 text-left hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
            >
              <span className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wide">{key}</span>
              <svg
                className={`h-4 w-4 text-gray-400 dark:text-gray-500 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {isOpen && (
              <div id={panelId} role="region" aria-labelledby={btnId} className="px-4 sm:px-5 pb-4">
                <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{text}</p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
