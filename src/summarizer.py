"""
summarizer.py — Uses Groq (Llama) to produce category-specific research digests.

Four categories are supported, each with a tailored system prompt:
  - analysis          : Stock picks, conviction calls, technical/fundamental
  - company_updates   : Corporate actions, order wins, business developments
  - quarterly_updates : Earnings results, concall highlights, guidance
  - macro             : Economy, FII/DII, global cues, RBI/policy
"""

import logging
from datetime import datetime, timezone, timedelta

from groq import Groq

from .fetcher import Post

logger = logging.getLogger(__name__)

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Category Metadata
# ---------------------------------------------------------------------------

CATEGORIES = {
    "analysis": {
        "label": "📊 Analysis",
        "color": "#0f3460",
    },
    "company_updates": {
        "label": "🏢 Company Updates",
        "color": "#1a6b3c",
    },
    "quarterly_updates": {
        "label": "📋 Quarterly Updates",
        "color": "#7b4a00",
    },
    "macro": {
        "label": "🌐 Macro",
        "color": "#4a1a7b",
    },
}

# ---------------------------------------------------------------------------
# System Prompts — one per category
# ---------------------------------------------------------------------------

_BASE_RULES = """
Rules:
1. Only use information from the provided posts — do not hallucinate tickers, numbers, or data.
2. Always credit the researcher's handle (e.g., @handle) for every insight.
3. Flag if any post looks like a paid promotion or pump-and-dump.
4. Be concise — the reader is a busy investor.
5. Use Indian stock market terminology (NSE/BSE codes, SME board, T2T, circuit filters).
6. End with a SEBI disclaimer.
"""

_SYSTEM_PROMPTS = {
    "analysis": f"""You are an expert Indian equity research analyst specialising in BSE/NSE
small-cap, micro-cap, and SME IPO stocks.

Your job: digest stock analysis posts from Indian researchers on X (Twitter) and produce
a focused HTML digest covering stock picks, conviction calls, buy/sell levels, technical
setups, and fundamental insights.
{_BASE_RULES}""",

    "company_updates": f"""You are an expert Indian equity research analyst tracking corporate
developments across BSE/NSE listed companies.

Your job: digest posts about company-level news — order wins, capex plans, management
interviews, corporate actions (dividends, buybacks, splits), business model changes,
and any developments that affect a specific company's outlook.
{_BASE_RULES}""",

    "quarterly_updates": f"""You are an expert Indian equity analyst specialising in earnings
analysis for BSE/NSE listed companies.

Your job: digest posts covering quarterly results — revenue, PAT, EBITDA margins,
YoY/QoQ comparisons, concall highlights, management guidance, and any notable beats
or misses. Present numbers clearly and contextualise them.
{_BASE_RULES}""",

    "macro": f"""You are an expert Indian macro and equity strategist.

Your job: digest posts covering the broad market — FII/DII flows, RBI policy, Union
Budget commentary, global triggers (US Fed, crude oil, currency), sector rotation,
and broad Nifty/Sensex outlook. Connect macro dots to Indian equity implications.
{_BASE_RULES}""",
}

# ---------------------------------------------------------------------------
# User Prompt Template — shared across all categories
# ---------------------------------------------------------------------------

_USER_PROMPT = """\
Below are {num_posts} posts from {num_handles} researchers on X (Twitter),
collected from the last {hours} hours. Category: {category_label}. Today is {date} IST.

=== POSTS START ===
{posts_block}
=== POSTS END ===

Generate a focused digest in clean HTML (no markdown, no code fences).
Use the following structure — skip any section where no relevant content exists:

<h2>{category_label} Digest — {date}</h2>
<p style="color:#555;font-size:14px;">
  Compiled from <b>{num_handles} researchers</b> | <b>{num_posts} posts</b> | Last {hours}h
</p>

<hr>

<h3>🔑 Key Highlights</h3>
<!-- 3-5 bullet points summarising the most important insights from this category -->

<h3>📌 Stock / Topic Breakdown</h3>
<!-- For each stock or topic mentioned:
     - Name + NSE/BSE ticker if inferable
     - Sentiment: [🟢 BULLISH] / [🔴 BEARISH] / [🟡 NEUTRAL / WATCHING]
     - 1-2 sentence insight
     - Credit: @handle
     Separate entries with <hr> -->

<h3>⚠️ Flags & Cautions</h3>
<!-- Risk warnings, exit calls, suspected pumps, or caution flags.
     If none: <p>No flags today.</p> -->

<h3>💡 Top Takeaway</h3>
<!-- Single most actionable or interesting insight from today's posts. -->

<hr>
<p style="font-size:12px;color:#888;">
  ⚠️ <b>Disclaimer:</b> This digest is AI-generated for informational purposes only.
  It does not constitute SEBI-registered investment advice.
  Please consult a registered advisor before making investment decisions.
</p>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_posts_block(posts: list) -> str:
    """Format posts into a numbered text block for the prompt."""
    lines = []
    for i, p in enumerate(posts, 1):
        ts = p.timestamp.astimezone(IST).strftime("%d %b %Y %H:%M IST")
        lines.append(f"[{i}] @{p.handle} — {ts}\n{p.text}\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main summarize function
# ---------------------------------------------------------------------------

def summarize(
    posts: list,
    api_key: str,
    model_name: str = "llama-3.3-70b-versatile",
    lookback_hours: int = 24,
    category: str = "analysis",
) -> str:
    """
    Generate a category-specific HTML digest using Groq (Llama).

    Args:
        posts:          List of Post objects to summarise.
        api_key:        Groq API key.
        model_name:     Groq model identifier.
        lookback_hours: Lookback window (cosmetic, used in digest text).
        category:       One of: analysis, company_updates, quarterly_updates, macro.

    Returns:
        HTML string ready to be inserted into the email body.
    """
    client = Groq(api_key=api_key)
    category_label = CATEGORIES.get(category, {}).get("label", category.replace("_", " ").title())
    system_prompt = _SYSTEM_PROMPTS.get(category, _SYSTEM_PROMPTS["analysis"])

    if not posts:
        return (
            f"<h3>📭 No Posts Found</h3>"
            f"<p>No posts were collected for the <b>{category_label}</b> category "
            f"in the last {lookback_hours} hours. Add handles to this category in "
            f"<code>config.yaml</code> or check if Nitter instances are up.</p>"
        )

    handles = sorted(set(p.handle for p in posts))
    today = datetime.now(IST).strftime("%d %B %Y")
    posts_block = _format_posts_block(posts)

    prompt = _USER_PROMPT.format(
        num_posts=len(posts),
        num_handles=len(handles),
        hours=lookback_hours,
        date=today,
        posts_block=posts_block,
        category_label=category_label,
    )

    logger.info(f"[{category_label}] Sending {len(posts)} posts to Groq ({model_name}) …")

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
        )
        html = response.choices[0].message.content.strip()

        # Strip accidental markdown code fences if the model adds them
        if html.startswith("```"):
            html = html.split("```", 2)[1]
            if html.startswith("html"):
                html = html[4:]
            html = html.rsplit("```", 1)[0].strip()

        logger.info(f"[{category_label}] Digest generated successfully.")
        return html

    except Exception as e:
        logger.error(f"[{category_label}] Groq API error: {e}")
        raise
