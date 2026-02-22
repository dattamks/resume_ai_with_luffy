export default function ScoreGauge({ score }) {
  const radius = 52
  const stroke = 11
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference
  const color = score >= 75 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#ef4444'
  const label = score >= 75 ? 'Strong match' : score >= 50 ? 'Moderate match' : 'Needs work'

  return (
    <div className="flex flex-col items-center gap-1" role="img" aria-label={`ATS score: ${score} out of 100. ${label}`}>
      <svg width="120" height="120" viewBox="0 0 136 136" className="sm:w-[136px] sm:h-[136px]" aria-hidden="true">
        <circle cx="68" cy="68" r={radius} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-gray-100 dark:text-slate-700" />
        <circle
          cx="68" cy="68" r={radius} fill="none"
          stroke={color} strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 68 68)"
          style={{ transition: 'stroke-dashoffset 1s cubic-bezier(.4,0,.2,1)' }}
        />
        <text x="68" y="64" dominantBaseline="middle" textAnchor="middle" fontSize="30" fontWeight="700" className="fill-gray-800 dark:fill-gray-100">
          {score}
        </text>
        <text x="68" y="84" dominantBaseline="middle" textAnchor="middle" fontSize="11" className="fill-gray-400 dark:fill-gray-500">
          / 100
        </text>
      </svg>
      <span className="text-xs font-semibold" style={{ color }}>{label}</span>
    </div>
  )
}
