"""
HTML template for PDF export of analysis results.
Rendered server-side via WeasyPrint.
"""


def render_analysis_pdf_html(analysis):
    """Return an HTML string for the analysis report."""
    bd = analysis.ats_score_breakdown or {}
    sections = analysis.section_suggestions or {}
    bullets = analysis.rewritten_bullets or []
    gaps = analysis.keyword_gaps or []
    score = analysis.ats_score or 0

    score_color = '#22c55e' if score >= 75 else '#f59e0b' if score >= 50 else '#ef4444'
    score_label = 'Strong match' if score >= 75 else 'Moderate match' if score >= 50 else 'Needs work'

    def bar_html(label, value):
        bg = '#22c55e' if value >= 75 else '#f59e0b' if value >= 50 else '#ef4444'
        return f'''
        <div style="margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;font-size:11px;color:#6b7280;margin-bottom:3px;">
            <span>{label}</span><span style="font-weight:600;color:#374151;">{value}</span>
          </div>
          <div style="height:8px;background:#f3f4f6;border-radius:99px;overflow:hidden;">
            <div style="height:100%;width:{value}%;background:{bg};border-radius:99px;"></div>
          </div>
        </div>'''

    bars = ''.join([
        bar_html('Keyword Match', bd.get('keyword_match', 0)),
        bar_html('Format & Structure', bd.get('format_score', 0)),
        bar_html('Relevance', bd.get('relevance_score', 0)),
    ])

    gaps_html = ''
    if gaps:
        pills = ' '.join(
            f'<span style="display:inline-block;background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;'
            f'padding:3px 10px;border-radius:99px;font-size:11px;font-weight:500;margin:2px;">{kw}</span>'
            for kw in gaps
        )
        gaps_html = f'''
        <div style="margin-top:20px;">
          <h3 style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px;">
            Missing Keywords <span style="background:#fef2f2;color:#dc2626;font-size:10px;padding:2px 8px;border-radius:99px;">{len(gaps)}</span>
          </h3>
          <div>{pills}</div>
        </div>'''

    sections_html = ''
    if sections:
        items = ''.join(
            f'<div style="margin-bottom:12px;">'
            f'<h4 style="font-size:11px;font-weight:700;color:#4f46e5;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:4px;">{key}</h4>'
            f'<p style="font-size:12px;color:#374151;line-height:1.6;margin:0;">{text}</p>'
            f'</div>'
            for key, text in sections.items()
        )
        sections_html = f'''
        <div style="margin-top:20px;">
          <h3 style="font-size:13px;font-weight:600;color:#374151;margin-bottom:10px;">Section-by-Section Suggestions</h3>
          {items}
        </div>'''

    bullets_html = ''
    if bullets:
        items = ''.join(
            f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-bottom:10px;">'
            f'<p style="font-size:9px;font-weight:700;color:#9ca3af;text-transform:uppercase;margin:0 0 2px 0;">Original</p>'
            f'<p style="font-size:12px;color:#6b7280;text-decoration:line-through;margin:0 0 8px 0;">{item.get("original", "")}</p>'
            f'<p style="font-size:9px;font-weight:700;color:#22c55e;text-transform:uppercase;margin:0 0 2px 0;">Improved</p>'
            f'<p style="font-size:12px;color:#111827;font-weight:500;margin:0;">{item.get("rewritten", "")}</p>'
            f'{"<p style=font-size:10px;color:#9ca3af;font-style:italic;margin:6px 0 0 0;border-top:1px solid #e5e7eb;padding-top:6px;>" + item["reason"] + "</p>" if item.get("reason") else ""}'
            f'</div>'
            for item in bullets
        )
        bullets_html = f'''
        <div style="margin-top:20px;">
          <h3 style="font-size:13px;font-weight:600;color:#374151;margin-bottom:10px;">
            Rewritten Bullet Points <span style="background:#ecfdf5;color:#15803d;font-size:10px;padding:2px 8px;border-radius:99px;">{len(bullets)}</span>
          </h3>
          {items}
        </div>'''

    role_line = ''
    if analysis.jd_role or analysis.jd_company:
        parts = [p for p in [analysis.jd_role, analysis.jd_company] if p]
        role_line = f'<p style="font-size:13px;color:#6b7280;margin:2px 0 0 0;">{" at ".join(parts)}</p>'

    assessment_html = ''
    if analysis.overall_assessment:
        assessment_html = f'''
        <div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:10px;padding:14px;margin-top:20px;">
          <p style="font-size:10px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:0.05em;margin:0 0 6px 0;">Overall Assessment</p>
          <p style="font-size:12px;color:#1f2937;line-height:1.6;margin:0;">{analysis.overall_assessment}</p>
        </div>'''

    return f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    @page {{ size: A4; margin: 1.5cm; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #111827; margin: 0; padding: 0; font-size: 12px; }}
    * {{ box-sizing: border-box; }}
  </style>
</head>
<body>
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px;">
    <div>
      <h1 style="font-size:22px;font-weight:700;color:#111827;margin:0;">Resume Analysis Report</h1>
      {role_line}
      <p style="font-size:10px;color:#9ca3af;margin:4px 0 0 0;">
        {analysis.created_at.strftime('%B %d, %Y at %I:%M %p')} &middot; via {analysis.ai_provider_used or 'AI'}
      </p>
    </div>
    <div style="text-align:center;">
      <div style="width:80px;height:80px;border-radius:50%;border:6px solid {score_color};display:flex;align-items:center;justify-content:center;">
        <span style="font-size:26px;font-weight:700;color:#111827;">{score}</span>
      </div>
      <p style="font-size:10px;font-weight:600;color:{score_color};margin:4px 0 0 0;">{score_label}</p>
    </div>
  </div>

  <div style="border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:20px;">
    <p style="font-size:12px;font-weight:600;color:#374151;margin:0 0 12px 0;">Score Breakdown</p>
    {bars}
  </div>

  {assessment_html}
  {gaps_html}
  {sections_html}
  {bullets_html}

  <div style="margin-top:30px;border-top:1px solid #e5e7eb;padding-top:10px;text-align:center;">
    <p style="font-size:9px;color:#9ca3af;">Generated by Resume AI &middot; {analysis.created_at.strftime('%Y-%m-%d')}</p>
  </div>
</body>
</html>'''
