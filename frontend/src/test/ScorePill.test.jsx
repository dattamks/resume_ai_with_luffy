import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ScorePill from '../components/ScorePill'

describe('ScorePill', () => {
  it('renders dash when score is null', () => {
    render(<ScorePill score={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders the score value', () => {
    render(<ScorePill score={72} />)
    expect(screen.getByText('72')).toBeInTheDocument()
  })

  it('applies green style for high scores', () => {
    const { container } = render(<ScorePill score={80} />)
    const pill = container.querySelector('span')
    expect(pill.className).toContain('green')
  })

  it('applies amber style for mid scores', () => {
    const { container } = render(<ScorePill score={60} />)
    const pill = container.querySelector('span')
    expect(pill.className).toContain('amber')
  })

  it('applies red style for low scores', () => {
    const { container } = render(<ScorePill score={30} />)
    const pill = container.querySelector('span')
    expect(pill.className).toContain('red')
  })
})
