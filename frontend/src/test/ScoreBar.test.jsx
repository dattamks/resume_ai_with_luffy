import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ScoreBar from '../components/ScoreBar'

describe('ScoreBar', () => {
  it('renders the label and value', () => {
    render(<ScoreBar label="Keywords" value={85} />)
    expect(screen.getByText('Keywords')).toBeInTheDocument()
    expect(screen.getByText('85')).toBeInTheDocument()
  })

  it('renders the progress bar with correct width', () => {
    const { container } = render(<ScoreBar label="Format" value={60} />)
    const bar = container.querySelector('[style]')
    expect(bar.style.width).toBe('60%')
  })
})
