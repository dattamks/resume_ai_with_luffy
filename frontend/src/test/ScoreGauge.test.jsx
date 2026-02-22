import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ScoreGauge from '../components/ScoreGauge'

describe('ScoreGauge', () => {
  it('renders the score number', () => {
    render(<ScoreGauge score={82} />)
    expect(screen.getByText('82')).toBeInTheDocument()
  })

  it('shows "Strong match" for high scores', () => {
    render(<ScoreGauge score={85} />)
    expect(screen.getByText('Strong match')).toBeInTheDocument()
  })

  it('shows "Moderate match" for mid scores', () => {
    render(<ScoreGauge score={60} />)
    expect(screen.getByText('Moderate match')).toBeInTheDocument()
  })

  it('shows "Needs work" for low scores', () => {
    render(<ScoreGauge score={30} />)
    expect(screen.getByText('Needs work')).toBeInTheDocument()
  })

  it('has accessible aria-label', () => {
    render(<ScoreGauge score={75} />)
    expect(screen.getByRole('img')).toHaveAttribute(
      'aria-label',
      'ATS score: 75 out of 100. Strong match'
    )
  })
})
