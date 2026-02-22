export default function StatusDot({ status }) {
  const map = {
    done: 'bg-green-400',
    processing: 'bg-blue-400 animate-pulse',
    pending: 'bg-gray-300 dark:bg-gray-600',
    failed: 'bg-red-400',
  }
  return (
    <span className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 capitalize">
      <span className={`h-1.5 w-1.5 rounded-full ${map[status] || 'bg-gray-300'}`} />
      {status}
    </span>
  )
}
