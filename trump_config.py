"""
Trump Social Media -> Polymarket Trading Signal System
Configuration Module
"""

import os

# ============================================================
# Social Media Monitoring
# ============================================================

# Twitter/X API
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
TRUMP_TWITTER_USER_ID = "25073877"  # @realDonaldTrump numeric ID
TRUMP_TWITTER_USERNAME = "realDonaldTrump"

# Truth Social
TRUTH_SOCIAL_USERNAME = "realDonaldTrump"
TRUTH_SOCIAL_BASE_URL = "https://truthsocial.com"

# Polling interval (seconds)
POLL_INTERVAL = 30

# ============================================================
# LLM Analysis (Claude API)
# ============================================================

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"

# Topics that may impact Polymarket
TOPIC_CATEGORIES = [
    "tariffs_trade",        # Tariffs, trade war, trade deals
    "crypto_digital",       # Bitcoin, crypto regulation, CBDC
    "foreign_policy",       # China, Russia, Ukraine, NATO, sanctions
    "election_politics",    # Elections, candidates, campaigns
    "economy_fiscal",       # Tax, spending, debt ceiling, Fed
    "regulation_policy",    # Executive orders, regulation changes
    "personnel",            # Cabinet picks, firings, appointments
    "legal_judicial",       # Court cases, investigations, pardons
    "military_defense",     # Military actions, defense spending
    "tech_social_media",    # TikTok, Big Tech, Section 230
]

# ============================================================
# Polymarket
# ============================================================

POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB_API = "https://clob.polymarket.com"

# Phase 2: Trading credentials
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_SECRET = os.getenv("POLYMARKET_SECRET", "")
POLYMARKET_PASSPHRASE = os.getenv("POLYMARKET_PASSPHRASE", "")

# Trading parameters
MAX_POSITION_SIZE_USDC = 50  # Maximum position per trade
MIN_CONFIDENCE_THRESHOLD = 60  # Minimum confidence % to generate signal
MAX_DAILY_TRADES = 10

# ============================================================
# Email Notification
# ============================================================

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS", "").split(",")

# ============================================================
# State Management
# ============================================================

POST_STORE_FILE = os.getenv("POST_STORE_FILE", "data/seen_posts.json")
MAX_STORED_POSTS = 1000  # Keep last N posts for dedup

# ============================================================
# Logging
# ============================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
