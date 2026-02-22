export function SkeletonLine({ className = '' }) {
  return (
    <div
      className={`animate-pulse rounded bg-gray-200 dark:bg-slate-700 ${className}`}
    />
  )
}

export function SkeletonCircle({ className = '' }) {
  return (
    <div
      className={`animate-pulse rounded-full bg-gray-200 dark:bg-slate-700 ${className}`}
    />
  )
}

/** Skeleton that mimics the History list layout */
export function HistorySkeleton({ rows = 5 }) {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 sm:py-10">
      <div className="flex items-center justify-between mb-6">
        <SkeletonLine className="h-7 w-28" />
        <SkeletonLine className="h-8 w-32 rounded-lg" />
      </div>
      <div className="grid grid-cols-3 gap-3 sm:gap-4 mb-6">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 px-4 py-5 flex flex-col items-center gap-2">
            <SkeletonLine className="h-7 w-10" />
            <SkeletonLine className="h-3 w-16" />
          </div>
        ))}
      </div>
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 divide-y divide-gray-100 dark:divide-slate-700 overflow-hidden">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="flex items-center px-4 sm:px-5 py-4 gap-3">
            <div className="flex-1 space-y-2">
              <SkeletonLine className="h-4 w-40" />
              <SkeletonLine className="h-3 w-56" />
            </div>
            <SkeletonLine className="h-5 w-12 rounded-full" />
          </div>
        ))}
      </div>
    </div>
  )
}

/** Skeleton that mimics the Results page layout */
export function ResultsSkeleton() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 sm:py-10 space-y-5 sm:space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2 flex-1">
          <SkeletonLine className="h-7 w-48" />
          <SkeletonLine className="h-4 w-36" />
          <SkeletonLine className="h-3 w-52" />
        </div>
        <SkeletonLine className="h-8 w-16 rounded-lg" />
      </div>
      {/* Score card */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 p-5 sm:p-6 flex flex-col sm:flex-row gap-6 sm:gap-8 items-center">
        <SkeletonCircle className="w-28 h-28 sm:w-[136px] sm:h-[136px]" />
        <div className="flex-1 w-full space-y-5">
          <SkeletonLine className="h-4 w-32" />
          {[1, 2, 3].map((i) => (
            <div key={i} className="space-y-1.5">
              <div className="flex justify-between">
                <SkeletonLine className="h-3 w-24" />
                <SkeletonLine className="h-3 w-8" />
              </div>
              <SkeletonLine className="h-2 w-full rounded-full" />
            </div>
          ))}
        </div>
      </div>
      {/* Assessment */}
      <SkeletonLine className="h-28 w-full rounded-2xl" />
      {/* Keyword gaps */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-700 p-4 sm:p-5 space-y-3">
        <SkeletonLine className="h-4 w-36" />
        <div className="flex flex-wrap gap-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <SkeletonLine key={i} className="h-6 w-20 rounded-full" />
          ))}
        </div>
      </div>
    </div>
  )
}
