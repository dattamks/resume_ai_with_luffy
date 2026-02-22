import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import StatusDot from '../components/StatusDot'

describe('StatusDot', () => {
  it('renders the status text', () => {
    render(<StatusDot status="done" />)
    expect(screen.getByText('done')).toBeInTheDocument()
  })

  it('shows green dot for done status', () => {
    const { container } = render(<StatusDot status="done" />)
    const dot = container.querySelector('span span')
    expect(dot.className).toContain('bg-green-400')
  })

  it('shows pulse animation for processing status', () => {
    const { container } = render(<StatusDot status="processing" />)
    const dot = container.querySelector('span span')
    expect(dot.className).toContain('animate-pulse')
  })
})
