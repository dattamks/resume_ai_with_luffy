# i-Luffy — User Guide

> **Last updated:** 2026-03-01 &nbsp;|&nbsp; **Platform version:** v0.27.0
> Everything you need to know about using i-Luffy to optimize your resume, prepare for interviews, and land your dream job.

---

## Table of Contents

1. [What is i-Luffy?](#1-what-is-i-luffy)
2. [Getting Started](#2-getting-started)
3. [Your Dashboard](#3-your-dashboard)
4. [Resume Analysis — The Core Feature](#4-resume-analysis--the-core-feature)
5. [Understanding Your Analysis Results](#5-understanding-your-analysis-results)
6. [Generate an Improved Resume](#6-generate-an-improved-resume)
7. [Resume Builder (Conversational Chat)](#7-resume-builder-conversational-chat)
8. [Interview Prep](#8-interview-prep)
9. [Cover Letter Generator](#9-cover-letter-generator)
10. [Smart Job Alerts](#10-smart-job-alerts)
11. [Sharing Your Analysis](#11-sharing-your-analysis)
12. [Resume Version History](#12-resume-version-history)
13. [Your Profile & Settings](#13-your-profile--settings)
14. [Plans & Credits](#14-plans--credits)
15. [Payments & Billing](#15-payments--billing)
16. [Notifications](#16-notifications)
17. [Data Privacy & Export](#17-data-privacy--export)
18. [FAQ](#18-faq)

---

## 1. What is i-Luffy?

**i-Luffy** is an AI-powered resume optimization platform that helps you:

- **Score your resume** against any job description to see how ATS (Applicant Tracking Systems) will rank you
- **Find keyword gaps** — discover exactly which skills and terms you're missing
- **Get section-by-section feedback** — improvement suggestions for every part of your resume
- **Rewrite weak bullet points** — AI rewrites them with action verbs and metrics
- **Generate improved resumes** — get an optimized PDF/DOCX tailored to the job
- **Build resumes from scratch** — guided conversational builder
- **Prepare for interviews** — AI-generated questions based on your resume + job description
- **Generate cover letters** — personalized, role-specific cover letters
- **Get smart job alerts** — AI finds and matches jobs based on your resume

---

## 2. Getting Started

### Creating Your Account

**Option A — Email Registration:**
1. Go to the signup page
2. Enter your **username**, **email**, **password**, and **mobile number** (optional)
3. Accept the Terms of Service and Data Usage Policy
4. Optionally opt in to marketing emails for tips and newsletters
5. Click **Register**
6. Check your email for a **verification link** — click it to verify your account

**Option B — Google Sign-In:**
1. Click **Sign in with Google**
2. Select your Google account
3. If it's your first time, you'll be asked to complete a quick profile setup (accept terms)
4. Your email is auto-verified via Google

### After Registration

- You start on the **Free plan** with initial credits
- A wallet is auto-created with your starting credit balance
- You can immediately start analyzing resumes

### Logging In

- Enter your username/email and password
- You'll receive an **access token** (valid 1 hour) and a **refresh token** (valid 7 days)
- The app automatically refreshes your session — you stay logged in for up to 7 days

---

## 3. Your Dashboard

The dashboard gives you a bird's-eye view of your resume optimization journey:

| Widget | What It Shows |
|--------|--------------|
| **Total Analyses** | How many resume analyses you've run |
| **Average ATS Score** | Your overall average score across all analyses |
| **Industry Benchmark** | Your percentile rank among all users |
| **Score Trend** | Your last 10 ATS scores — see if you're improving |
| **Grade Distribution** | Breakdown of your A/B/C/D/F grades |
| **Top Roles Analyzed** | Most-analyzed job roles |
| **Top Industries** | Most-analyzed industries |
| **Monthly Activity** | Analyses per month over last 6 months |
| **Top Missing Keywords** | Most commonly missing skills across analyses |
| **Credit Usage** | Credit spending over time |
| **Weekly Job Matches** | New job matches in the last 7 days |

---

## 4. Resume Analysis — The Core Feature

### How to Analyze Your Resume

1. **Upload your resume** (PDF format, max 5MB)
2. **Provide the job description** — three ways:
   - **Paste text**: Copy-paste the full job description
   - **Enter a URL**: Paste a link to the job posting (LinkedIn, Indeed, etc.) — we'll scrape it
   - **Fill a form**: Enter the job title, company, required skills, experience, and industry

3. **Click Analyze** — the AI processes your resume in the background
4. **Poll for results** — the app checks every few seconds until done (typically 20-60 seconds)

### What Happens Behind the Scenes

```
Upload PDF → Extract text → Resolve job description → AI analysis → Parse results → Generate PDF report
```

- Your resume text is extracted from the PDF
- If you provided a URL, the job posting is scraped
- The AI compares your resume against the job requirements
- Results are saved and a PDF report is auto-generated

### Bulk Analysis

Analyze one resume against **multiple job descriptions** at once (up to 10):
- Upload once, provide multiple JDs
- Each JD creates a separate analysis
- Credits deducted per analysis

### Retrying Failed Analyses

If an analysis fails (network issue, AI timeout):
1. Go to the analysis detail
2. Click **Retry** — it resumes from where it left off
3. Credits are deducted again (refunded if it fails again)

### Cancelling an Analysis

If an analysis is stuck:
1. Click **Cancel**
2. The background task is stopped
3. Your credits are automatically refunded

---

## 5. Understanding Your Analysis Results

### Overall Grade

| Grade | Score Range | Meaning |
|-------|-----------|---------|
| **A** | 85-100 | Excellent match — submit with confidence |
| **B** | 70-84 | Good match — minor improvements recommended |
| **C** | 55-69 | Fair match — significant gaps to address |
| **D** | 40-54 | Poor match — major rewrites needed |
| **F** | 0-39 | Very poor — consider different approach |

### ATS Scores

You get three platform-specific ATS scores:

| Score | What It Simulates |
|-------|------------------|
| **Generic ATS** | Standard ATS keyword matching |
| **Workday ATS** | Workday's parsing behavior |
| **Greenhouse ATS** | Greenhouse's evaluation criteria |

Plus a **Keyword Match Percent** showing how many required keywords your resume contains.

### Keyword Analysis

- **Matched Keywords** — Skills/terms found in your resume that match the JD ✅
- **Missing Keywords** — Critical terms you need to add ❌
- **Recommended to Add** — Strategic keywords to boost your score 💡

### Section Feedback

AI reviews each resume section individually:
- **Summary/Objective** — Is it targeted? Does it mention the role?
- **Experience** — Are bullets action-verb-led? Do they have metrics?
- **Skills** — Are missing tools/technologies listed?
- **Education** — Is it properly formatted?
- **Projects** — Are they relevant to the role?

Each section gets a score, rating, and specific improvement suggestions.

### Sentence Suggestions

The AI identifies weak bullet points and provides:
- **Original** — Your current text
- **Suggested** — An improved version
- **Reason** — Why the change helps

### Formatting Flags

Issues with your resume's formatting:
- Inconsistent date formats
- Missing sections
- Too many pages
- Non-standard section headers

### Quick Wins

Prioritized actions to boost your score quickly:
- Each has a **priority** (high/medium/low) and a specific **action** to take

---

## 6. Generate an Improved Resume

After analysis, let AI build an optimized version of your resume:

1. Go to a **completed analysis**
2. Click **Generate Improved Resume**
3. Choose a **template**:
   - `ats_classic` — Clean, ATS-friendly (default)
   - `executive` — Elegant layout with gold accents, for leadership positions
   - `creative` — Bold purple gradient design with skill pills
   - `minimal` — Ultra-clean, whitespace-heavy, distraction-free
   - ~~`modern`~~ — *Currently unavailable (under redesign)*
4. Choose **format**: PDF or DOCX
5. Click Generate — AI rewrites your entire resume incorporating all improvements
6. Download when ready

**Cost:** 1 credit per generation

The generated resume includes:
- All missing keywords naturally integrated
- Rewritten bullet points with metrics and action verbs
- Proper formatting for ATS compatibility
- Tailored to the specific job description

---

## 7. Resume Builder (Conversational Chat)

Build a resume from scratch through a guided conversation:

### Starting a Session

Choose how to begin:
- **Start Fresh** — Build from nothing
- **From Profile Data** — Pre-fill with your profile info
- **From Previous Resume** — Use an existing resume as a starting point

### The Wizard Steps

| Step | What You Provide |
|------|-----------------|
| 1. **Contact Info** | Name, email, phone, location, LinkedIn, GitHub, website |
| 2. **Target Role** | Job title, company, industry, experience level |
| 3. **Experience** | Work history — companies, roles, dates, bullet points |
| 4. **Experience Review** | AI polishes your bullets with action verbs and metrics |
| 5. **Education** | Degrees, institutions, dates, GPA, honors |
| 6. **Skills** | Technical skills, tools, frameworks, soft skills |
| 7. **Certifications** | Professional certifications and dates |
| 8. **Projects** | Notable projects with descriptions |
| 9. **Review & Polish** | AI gives final suggestions, you make last edits |
| 10. **Done** | Generate your PDF/DOCX |

### Key Features

- **Navigate freely** — Go back and forth between steps
- **AI assistance** — The assistant provides suggestions at each step
- **Interactive UI** — Each step has tailored input components (not just text)
- **Save progress** — Your session is saved and can be resumed anytime
- **Max 5 active sessions** — Complete or delete old sessions to start new ones

### Finalizing

When you're done:
1. Click **Finalize**
2. Choose a template and format
3. The AI generates your resume (costs 2 credits)
4. Download the file

---

## 8. Interview Prep

Get AI-generated interview questions customized to your resume + job:

1. Run a resume analysis first
2. Go to the completed analysis
3. Click **Generate Interview Prep**
4. The AI creates:
   - **Behavioral questions** — Based on your experience
   - **Technical questions** — Based on the role's required skills
   - **Gap-based questions** — Covering areas where your resume is weak
   - **Situational questions** — Role-specific scenarios
5. Each question includes:
   - The question itself
   - **Why it's likely to be asked** (linked to your resume/gaps)
   - **A sample answer** tailored to your background
   - **Difficulty level** (basic/intermediate/advanced)
6. Plus **general interview tips** based on the role

**Cost:** 1 credit

---

## 9. Cover Letter Generator

Create personalized cover letters for any analyzed job:

1. Go to a completed analysis
2. Click **Generate Cover Letter**
3. Choose your **tone**:
   - `professional` — Formal, traditional
   - `conversational` — Friendly, approachable
   - `enthusiastic` — Energetic, passionate
4. The AI generates a cover letter that:
   - Highlights your most relevant experience
   - Addresses the company and role specifically
   - Bridges any gaps identified in the analysis
   - Matches the requested tone

**Cost:** 1 credit

You receive:
- Plain text version
- HTML-formatted version
- PDF download

---

## 10. Smart Job Alerts

Let AI find and match jobs for you automatically:

### Setting Up a Job Alert

1. You need a **Pro plan** (job alerts are a premium feature)
2. Go to **Job Alerts**
3. Click **Create Alert**
4. Select a **resume** to match against
5. Choose **frequency**: daily or weekly
6. Set **preferences**:
   - Remote-friendly only?
   - Preferred location
   - Minimum salary
   - Companies to exclude
   - Priority companies

### How It Works

1. AI extracts your **Job Search Profile** from the selected resume (titles, skills, seniority, industries)
2. On your schedule (daily/weekly), the system:
   - Searches job boards (LinkedIn, Indeed, etc.) using your profile
   - Discovers new job postings
   - Scores each job for relevance (0-100) using AI
   - Creates matches above the threshold
3. You get notified via **email** and **in-app notification**

### Viewing Matches

Each match shows:
- Job title, company, location, salary range
- **Relevance score** (0-100)
- **Why it matches** — AI-generated explanation
- Link to the original posting

### Providing Feedback

Rate each match:
- **Relevant** — Good match, saving for later
- **Applied** — Already applied
- **Irrelevant** — Not a good match (helps improve future results)
- **Dismissed** — Not interested right now

### Manual Run

Trigger an on-demand job search:
- Click **Run Now** on any alert
- Costs 1 credit
- Results appear in a few minutes

---

## 11. Sharing Your Analysis

Share your analysis results publicly:

1. Go to a completed analysis
2. Click **Share** — generates a unique public URL
3. Anyone with the link can view:
   - ATS scores
   - Keyword analysis
   - Section feedback
   - (No personal contact info is included)
4. To revoke access, click **Unshare**

### Share Summary

A lightweight version of the shared analysis is available for social card previews — shows only score, grade, and role (no PII).

---

## 12. Resume Version History

Track how your resume improves over time:

1. Upload different versions of the same resume (same filename)
2. The system automatically detects versions and creates a history chain
3. View version history for any resume:
   - Version number
   - Upload date
   - Best ATS score achieved with that version
   - Best grade achieved
   - What changed between versions

This lets you see your **improvement timeline** — how each revision improved (or didn't improve) your ATS score.

---

## 13. Your Profile & Settings

### Viewing Your Profile

**GET** your profile to see:
- Username, email, first/last name
- Phone (country code + number)
- Current plan and billing details
- Social links (website, GitHub, LinkedIn)
- Auth provider (email or Google)
- Email verification status
- Credit balance

### Updating Your Profile

Update your:
- Username
- Email (re-verification required)
- First and last names
- Country code, mobile number
- Social links (website, GitHub, LinkedIn)

### Uploading an Avatar

Upload a profile picture (JPEG/PNG):
- Replaces any existing avatar
- Stored securely

### Changing Password

Requires your current password. Doesn't apply to Google OAuth accounts.

### Forgot Password

1. Enter your email on the forgot password page
2. Receive a reset link via email (valid for 1 hour)
3. Click the link and set a new password

### Notification Preferences

Control what notifications you receive:

| Category | Email | Mobile/SMS |
|----------|-------|------------|
| Job Alerts | ✅ default on | ❌ default off |
| Feature Updates | ✅ default on | ❌ default off |
| Newsletters | ✅ default on | ❌ default off |
| Policy Changes | ✅ always on | ✅ always on |

---

## 14. Plans & Credits

### Free Plan

| Feature | Limit |
|---------|-------|
| Analyses per month | Limited (varies) |
| Credits per month | Included free credits |
| Resume uploads | Limited storage |
| Max file size | 5 MB |
| PDF export | ✅ |
| Share analysis | ✅ |
| Job alerts | ❌ |
| Premium templates | ❌ |

### Pro Plan

| Feature | Limit |
|---------|-------|
| Analyses per month | Higher limit |
| Credits per month | More credits |
| Resume uploads | More storage |
| Max file size | Varies |
| PDF export | ✅ |
| Share analysis | ✅ |
| Job alerts | ✅ |
| Premium templates | ✅ |
| Priority processing | ✅ |
| Email support | ✅ |
| Credit top-ups | ✅ |

### How Credits Work

- Every AI-powered action costs credits
- You receive credits monthly based on your plan
- Free plan users get a starter balance
- Pro users can buy **top-up packs** for additional credits
- Failed analyses automatically **refund** credits
- Cancelled analyses automatically **refund** credits

### Credit Costs

| Action | Approximate Cost |
|--------|-----------------|
| Resume Analysis | 1 credit |
| Generate Improved Resume | 1 credit |
| Interview Prep | 1 credit |
| Cover Letter | 1 credit |
| Job Alert Manual Run | 1 credit |
| Resume Builder Finalize | 2 credits |

### Checking Your Balance

Your credit balance is shown:
- On your dashboard
- In your profile/wallet area
- After every action that uses credits (response includes `credits_used` and `balance`)

### Wallet Transactions

View your complete credit history:
- Monthly plan credits
- Top-up purchases
- Analysis debits
- Refunds
- Upgrade bonuses

Export your transaction history as CSV.

---

## 15. Payments & Billing

### Subscribing to Pro

1. Go to the **Pricing** page
2. Click **Subscribe** on the Pro plan
3. Complete payment via **Razorpay** (cards, UPI, net banking, wallets)
4. Your plan is activated immediately
5. Credits are granted as an upgrade bonus

### Buying Credit Top-Ups

1. Go to your **Wallet**
2. Click **Top Up**
3. Choose the number of packs
4. Complete payment via Razorpay
5. Credits added instantly to your wallet

### Cancelling Your Subscription

1. Go to **Billing** or **Subscription Settings**
2. Click **Cancel Subscription**
3. Your current plan stays active until the end of the billing cycle
4. After that, you'll be downgraded to the Free plan

### Viewing Payment History

See all your past payments:
- Payment type (subscription or top-up)
- Amount
- Status (created, captured, failed, refunded)
- Date

---

## 16. Notifications

### In-App Notifications

The notification bell shows:
- **Analysis Complete** — Your analysis is done, view results
- **Resume Generated** — Your improved resume is ready to download
- **Job Matches** — New matching jobs found
- **System** — Platform updates, maintenance notices

### Unread Count

A badge shows how many unread notifications you have.

### Marking as Read

- Click a notification to mark it as read
- Or click **Mark All as Read** to clear the badge

---

## 17. Data Privacy & Export

### GDPR Data Export

Download all your data as a JSON file:
- Your profile information
- All analyses (metadata)
- Uploaded resumes
- Wallet transactions
- Consent history
- Notifications

### Deleting Your Account

Permanently delete your account and all data:
1. Go to **Profile Settings**
2. Click **Delete Account**
3. Confirm the action
4. All data is permanently removed (cascade delete)

---

## 18. FAQ

### How accurate are the ATS scores?

The scores simulate how real ATS platforms (generic, Workday, Greenhouse) would evaluate your resume. They focus on keyword matching, formatting, and relevance. While not identical to any specific ATS, they provide a reliable indicator of how well your resume will perform.

### Can I use i-Luffy for any job type?

Yes! The AI adapts to any role, industry, and experience level — from software engineering to marketing to healthcare to executive positions.

### What file formats are supported?

- **Upload**: PDF only (max 5MB)
- **Download**: PDF and DOCX templates available

### How long does an analysis take?

Typically 20-60 seconds. You'll see a progress indicator showing which step is currently running (extracting PDF, scraping JD, calling AI, parsing results).

### What happens if my analysis fails?

Your credits are automatically refunded. You can retry the analysis — it resumes from where it left off (no duplicate work).

### Can I analyze the same resume against different jobs?

Absolutely! That's the recommended approach:
1. Upload your resume once
2. Analyze it against each job description separately
3. Compare the results to see which job you're best suited for
4. Use the comparison feature to view analyses side-by-side

### How do I improve my ATS score?

1. **Add missing keywords** — The analysis shows exactly which terms to add
2. **Follow quick wins** — Do the high-priority actions first
3. **Apply sentence suggestions** — Replace weak bullets with AI-improved versions
4. **Generate an improved resume** — Let AI create an optimized version for you
5. **Track versions** — Upload the improved version and analyze again to see your progress

### Is my data secure?

- All data is encrypted in transit (HTTPS/TLS)
- Passwords are hashed using Django's default PBKDF2
- JWT tokens are rotated on refresh and blacklisted after use
- Files stored in Cloudflare R2 with signed URLs
- GDPR-compliant data export and deletion
- No data shared with third parties (beyond the AI model for analysis)

### Can multiple people collaborate?

Currently, i-Luffy is a single-user platform. Each account is individual. You can share analysis results via public links, but there's no real-time collaboration.

### What AI model is used?

The platform uses state-of-the-art AI models via OpenRouter (Claude, GPT-4o, Gemini), selected by the platform administrator for optimal quality and cost.

### I signed in with Google but want to add a password — can I?

Google OAuth users don't have a password set. This is by design for security. You can continue using Google sign-in.

### How do I contact support?

- Use the **Contact Form** on the landing page
- If you're on the Pro plan, you have access to **email support**

---

*For technical API documentation, see `FRONTEND_API_GUIDE.md`. For admin operations, see `docs/ADMIN_USAGE_GUIDE.md`.*
