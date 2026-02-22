import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SectionAccordion from '../components/SectionAccordion'

describe('SectionAccordion', () => {
  const sections = {
    Experience: 'Add more quantifiable achievements.',
    Education: 'Include GPA if above 3.5.',
  }

  it('renders all section headers', () => {
    render(<SectionAccordion sections={sections} />)
    expect(screen.getByText('Experience')).toBeInTheDocument()
    expect(screen.getByText('Education')).toBeInTheDocument()
  })

  it('does not show content by default', () => {
    render(<SectionAccordion sections={sections} />)
    expect(screen.queryByText('Add more quantifiable achievements.')).not.toBeInTheDocument()
  })

  it('shows content when header is clicked', () => {
    render(<SectionAccordion sections={sections} />)
    fireEvent.click(screen.getByText('Experience'))
    expect(screen.getByText('Add more quantifiable achievements.')).toBeInTheDocument()
  })

  it('hides content when clicked again', () => {
    render(<SectionAccordion sections={sections} />)
    fireEvent.click(screen.getByText('Experience'))
    fireEvent.click(screen.getByText('Experience'))
    expect(screen.queryByText('Add more quantifiable achievements.')).not.toBeInTheDocument()
  })

  it('sets aria-expanded correctly', () => {
    render(<SectionAccordion sections={sections} />)
    const btn = screen.getByText('Experience').closest('button')
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(btn)
    expect(btn).toHaveAttribute('aria-expanded', 'true')
  })
})
