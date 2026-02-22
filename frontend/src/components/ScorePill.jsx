export default function ScorePill({ score }) {
  if (score == null) return <span className="text-xs text-gray-400 dark:text-gray-500">—</span>
  const cls =
    score >= 75
      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
      : score >= 50
      ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
      : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
  return (
    <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${cls}`}>{score}</span>
  )
}
