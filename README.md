# 📈 Stock Research Aggregator

Automatically tracks 20–30 Indian stock market researchers on X (Twitter),
summarises their posts using **Google Gemini AI**, and delivers a structured
**Morning Research Digest to your Gmail** every weekday at 7 AM IST.

**Total cost: ₹0 / month.**

---

## How It Works

```
Nitter RSS (public X profiles)
        │
        ▼ (fetcher.py)
Collect all posts from last 24h
        │
        ▼ (summarizer.py)
Gemini AI → structured HTML digest
(stocks mentioned, sentiment, sector themes, flags)
        │
        ▼ (notifier.py)
Gmail → your inbox at 7 AM IST
        │
   (GitHub Actions cron — free)
```

---

## Setup (One-Time, ~20 Minutes)

### Step 1 — Get a Gemini API Key (Free)

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Click **"Create API Key"**
3. Copy the key — looks like `AIzaSy...`

> **Free tier**: 1,500 requests/day and 1M tokens/minute — more than enough.

---

### Step 2 — Create a Gmail App Password

You cannot use your regular Gmail password. You need an **App Password**.

1. Go to your Google Account → [Security](https://myaccount.google.com/security)
2. Make sure **2-Step Verification is ON** (required)
3. Search for **"App passwords"** or go to: `myaccount.google.com/apppasswords`
4. Select app: **Mail** | Select device: **Other** → type "StockDigest"
5. Click **Generate** → copy the 16-character password (e.g., `abcd efgh ijkl mnop`)

---

### Step 3 — Add Your Handles to config.yaml

Open [`config.yaml`](config.yaml) and add the X handles of the researchers you follow:

```yaml
handles:
  - marketsmojo
  - vivekbajaj_
  - varinder_bansal
  # ... add up to 30 handles (without the @ symbol)
```

---

### Step 4 — Test Locally (Optional but Recommended)

```bash
# Clone/download this project
cd stock-research-aggregator

# Create a virtual environment
python -m venv venv
source venv/bin/activate      # Mac/Linux
# venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt

# Copy the env template and fill in your credentials
cp .env.example .env
# Edit .env with your actual keys

# Test with a dry run (no email sent, prints digest to terminal)
python main.py --dry-run

# If the digest looks good, send a real email
python main.py
```

---

### Step 5 — Deploy to GitHub Actions (Automated, Free)

This makes the script run **automatically every weekday at 7 AM IST**.

#### 5a. Create a GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Name it `stock-research-aggregator` (private is fine)
3. Push this project to the repo:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/stock-research-aggregator.git
   git push -u origin main
   ```

#### 5b. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

Add these 4 secrets:

| Secret Name | Value |
|-------------|-------|
| `GEMINI_API_KEY` | Your Gemini API key |
| `GMAIL_SENDER` | Your Gmail address (e.g. `you@gmail.com`) |
| `GMAIL_APP_PASSWORD` | Your 16-char App Password |
| `RECIPIENT_EMAIL` | Where to send digest (can be same as sender) |

#### 5c. Enable GitHub Actions

1. Go to your repo → **Actions** tab
2. If prompted, click **"I understand my workflows, go ahead and enable them"**
3. The workflow will now run automatically at **1:30 AM UTC = 7:00 AM IST, Mon–Fri**

#### 5d. Test It Manually

- Go to **Actions → "📈 Daily Stock Research Digest"**
- Click **"Run workflow"** → check "Dry run" first → **Run workflow**
- Watch the logs. If green, uncheck dry run and run again to send the email!

---

## Troubleshooting

### No posts fetched
- Nitter instances may be temporarily down. The script tries multiple instances.
- Try running again after 30 minutes.
- You can self-host a Nitter instance for reliability (see [Nitter GitHub](https://github.com/zedeus/nitter)).

### Gmail authentication failed
- Ensure you're using an **App Password**, not your regular Gmail password.
- Ensure 2-Step Verification is enabled on your Google Account.
- The App Password should be 16 characters (spaces are ok, the script strips them).

### Gemini API error
- Check your API key is valid at [aistudio.google.com](https://aistudio.google.com).
- The free tier limit is 1,500 requests/day — this script uses ~1 request per run.

### GitHub Actions not running
- GitHub may disable cron schedules on inactive repos. Push any commit to re-enable.
- Check the **Actions** tab for error logs.

---

## Customisation

### Change the digest schedule
Edit `.github/workflows/daily_digest.yml`:
```yaml
- cron: "30 1 * * 1-5"   # 7:00 AM IST, Mon–Fri
# Change to run weekends too:
- cron: "30 1 * * *"     # Every day
# Change to 8:00 AM IST:
- cron: "30 2 * * 1-5"   # 8:00 AM IST, Mon–Fri
```

### Change lookback window
Fetch the last 48 hours instead of 24:
```bash
python main.py --hours 48
```

Or update `config.yaml`:
```yaml
settings:
  fetch_hours: 48
```

### Tune the Gemini prompt
Edit `src/summarizer.py` → `_USER_PROMPT` to change the digest format,
add specific companies to watch, or adjust the tone.

---

## Project Structure

```
stock-research-aggregator/
├── main.py                          # Orchestrator — run this
├── config.yaml                      # Your handles + settings
├── requirements.txt                 # Python dependencies
├── .env.example                     # Template for credentials
├── .env                             # Your actual credentials (DO NOT commit!)
├── src/
│   ├── fetcher.py                   # Nitter RSS fetching
│   ├── summarizer.py                # Gemini AI digest generation
│   └── notifier.py                  # Gmail SMTP delivery
└── .github/workflows/
    └── daily_digest.yml             # GitHub Actions cron job
```

---

## Privacy & Security

- Your API keys are stored as **GitHub Secrets** — they are encrypted and never visible in logs.
- The `.env` file is for local use only — **never commit it** (add `.env` to `.gitignore`).
- Nitter fetches only public X profiles — no login required.

---

## Cost Summary

| Component | Cost |
|-----------|------|
| Gemini 1.5 Flash API | **Free** (1,500 req/day) |
| Gmail SMTP | **Free** |
| GitHub Actions | **Free** (2,000 min/month) |
| Nitter RSS | **Free** (public instances) |
| **Total** | **₹0 / month** |
