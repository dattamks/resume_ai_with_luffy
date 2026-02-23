"""
HTML template for PDF export of analysis results.
Rendered server-side via WeasyPrint.
"""


def render_analysis_pdf_html(analysis):
    """Return an HTML string for the analysis report."""
    scores = analysis.scores or {}
    kw = analysis.keyword_analysis or {}
    sections = analysis.section_feedback or []
    suggestions = analysis.sentence_suggestions or []
    flags = analysis.formatting_flags or []
    wins = analysis.quick_wins or []
    grade = analysis.overall_grade or '?'
    generic_ats = scores.get('generic_ats', 0)
    workday_ats = scores.get('workday_ats', 0)
    greenhouse_ats = scores.get('greenhouse_ats', 0)
    kw_match = scores.get('keyword_match_percent', 0)

    grade_color = {
        'A': '#22c55e', 'B': '#3b82f6', 'C': '#f59e0b', 'D': '#f97316', 'F': '#ef4444',
    }.get(grade.upper(), '#6b7280')

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
        bar_html('Generic ATS', generic_ats),
        bar_html('Workday ATS', workday_ats),
        bar_html('Greenhouse ATS', greenhouse_ats),
        bar_html('Keyword Match', kw_match),
    ])

    # Keyword analysis
    missing = kw.get('missing_keywords', [])
    matched = kw.get('matched_keywords', [])
    recs = kw.get('recommended_to_add', [])

    keywords_html = ''
    if missing or matched:
        matched_pills = ' '.join(
            f'<span style="display:inline-block;background:#ecfdf5;color:#15803d;border:1px solid #bbf7d0;'
            f'padding:3px 10px;border-radius:99px;font-size:11px;font-weight:500;margin:2px;">{kw_item}</span>'
            for kw_item in matched
        )
        missing_pills = ' '.join(
            f'<span style="display:inline-block;background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;'
            f'padding:3px 10px;border-radius:99px;font-size:11px;font-weight:500;margin:2px;">{kw_item}</span>'
            for kw_item in missing
        )
        recs_html = ''
        if recs:
            recs_items = ''.join(f'<li style="font-size:12px;color:#374151;margin-bottom:4px;">{r}</li>' for r in recs)
            recs_html = f'<p style="font-size:11px;font-weight:600;color:#374151;margin:8px 0 4px;">Recommended Actions:</p><ul style="margin:0;padding-left:18px;">{recs_items}</ul>'
        keywords_html = f'''
        <div style="margin-top:20px;">
          <h3 style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px;">Keyword Analysis</h3>
          <p style="font-size:10px;font-weight:600;color:#15803d;margin:0 0 4px;">Matched ({len(matched)})</p>
          <div>{matched_pills}</div>
          <p style="font-size:10px;font-weight:600;color:#dc2626;margin:10px 0 4px;">Missing ({len(missing)})</p>
          <div>{missing_pills}</div>
          {recs_html}
        </div>'''

    # Section feedback
    sections_html = ''
    if sections:
        items = ''
        for sec in sections:
            fb_list = ''.join(f'<li style="font-size:12px;color:#374151;margin-bottom:3px;">{f}</li>' for f in sec.get('feedback', []))
            flags_list = ''.join(
                f'<li style="font-size:11px;color:#dc2626;margin-bottom:2px;">⚠ {fl}</li>'
                for fl in sec.get('ats_flags', [])
            )
            items += f'''
            <div style="margin-bottom:14px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                <h4 style="font-size:11px;font-weight:700;color:#4f46e5;text-transform:uppercase;letter-spacing:0.05em;margin:0;">{sec.get("section_name", "")}</h4>
                <span style="font-size:11px;font-weight:600;color:#374151;">{sec.get("score", "")}/100</span>
              </div>
              <ul style="margin:0;padding-left:18px;">{fb_list}</ul>
              {"<ul style='margin:4px 0 0;padding-left:18px;'>" + flags_list + "</ul>" if flags_list else ""}
            </div>'''
        sections_html = f'''
        <div style="margin-top:20px;">
          <h3 style="font-size:13px;font-weight:600;color:#374151;margin-bottom:10px;">Section Feedback</h3>
          {items}
        </div>'''

    # Sentence suggestions
    suggestions_html = ''
    if suggestions:
        items = ''.join(
            f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-bottom:10px;">'
            f'<p style="font-size:9px;font-weight:700;color:#9ca3af;text-transform:uppercase;margin:0 0 2px 0;">Original</p>'
            f'<p style="font-size:12px;color:#6b7280;text-decoration:line-through;margin:0 0 8px 0;">{item.get("original", "")}</p>'
            f'<p style="font-size:9px;font-weight:700;color:#22c55e;text-transform:uppercase;margin:0 0 2px 0;">Suggested</p>'
            f'<p style="font-size:12px;color:#111827;font-weight:500;margin:0;">{item.get("suggested", "")}</p>'
            f'{"<p style=font-size:10px;color:#9ca3af;font-style:italic;margin:6px 0 0 0;border-top:1px solid #e5e7eb;padding-top:6px;>" + item["reason"] + "</p>" if item.get("reason") else ""}'
            f'</div>'
            for item in suggestions
        )
        suggestions_html = f'''
        <div style="margin-top:20px;">
          <h3 style="font-size:13px;font-weight:600;color:#374151;margin-bottom:10px;">
            Sentence Suggestions <span style="background:#ecfdf5;color:#15803d;font-size:10px;padding:2px 8px;border-radius:99px;">{len(suggestions)}</span>
          </h3>
          {items}
        </div>'''

    # Formatting flags
    flags_html = ''
    if flags:
        flag_items = ''.join(f'<li style="font-size:12px;color:#dc2626;margin-bottom:4px;">⚠ {f}</li>' for f in flags)
        flags_html = f'''
        <div style="margin-top:20px;">
          <h3 style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px;">Formatting Issues</h3>
          <ul style="margin:0;padding-left:18px;">{flag_items}</ul>
        </div>'''

    # Quick wins
    wins_html = ''
    if wins:
        win_items = ''.join(
            f'<div style="display:flex;gap:8px;margin-bottom:8px;">'
            f'<span style="background:#eef2ff;color:#4f46e5;font-weight:700;font-size:11px;'
            f'width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;">{w.get("priority", "")}</span>'
            f'<p style="font-size:12px;color:#374151;margin:0;">{w.get("action", "")}</p>'
            f'</div>'
            for w in wins
        )
        wins_html = f'''
        <div style="margin-top:20px;">
          <h3 style="font-size:13px;font-weight:600;color:#374151;margin-bottom:10px;">Quick Wins</h3>
          {win_items}
        </div>'''

    # Summary
    summary_html = ''
    if analysis.summary:
        summary_html = f'''
        <div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:10px;padding:14px;margin-top:20px;">
          <p style="font-size:10px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:0.05em;margin:0 0 6px 0;">Summary</p>
          <p style="font-size:12px;color:#1f2937;line-height:1.6;margin:0;">{analysis.summary}</p>
        </div>'''

    role_line = ''
    if analysis.jd_role or analysis.jd_company:
        parts = [p for p in [analysis.jd_role, analysis.jd_company] if p]
        role_line = f'<p style="font-size:13px;color:#6b7280;margin:2px 0 0 0;">{" at ".join(parts)}</p>'

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
      <div style="width:80px;height:80px;border-radius:50%;border:6px solid {grade_color};display:flex;align-items:center;justify-content:center;">
        <span style="font-size:30px;font-weight:700;color:#111827;">{grade}</span>
      </div>
      <p style="font-size:11px;font-weight:600;color:{grade_color};margin:4px 0 0 0;">ATS: {generic_ats}</p>
    </div>
  </div>

  <div style="border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:20px;">
    <p style="font-size:12px;font-weight:600;color:#374151;margin:0 0 12px 0;">Score Breakdown</p>
    {bars}
  </div>

  {summary_html}
  {keywords_html}
  {sections_html}
  {suggestions_html}
  {flags_html}
  {wins_html}

  <div style="margin-top:30px;border-top:1px solid #e5e7eb;padding-top:10px;text-align:center;">
    <p style="font-size:9px;color:#9ca3af;">Generated by Resume AI &middot; {analysis.created_at.strftime('%Y-%m-%d')}</p>
  </div>
</body>
</html>'''
