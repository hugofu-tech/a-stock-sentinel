"""
Email Notification Module
Sends trading signals via SMTP email.
Supports both plain text and HTML formatted emails.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

from trump_config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    EMAIL_RECIPIENTS,
)

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Sends trading signal emails via SMTP."""

    def __init__(self):
        self.host = SMTP_HOST
        self.port = SMTP_PORT
        self.user = SMTP_USER
        self.password = SMTP_PASSWORD
        self.recipients = [r.strip() for r in EMAIL_RECIPIENTS if r.strip()]

    def is_configured(self):
        """Check if email sending is properly configured."""
        return bool(self.user and self.password and self.recipients)

    def send_signal(self, signal):
        """Send a single trading signal via email.

        Args:
            signal: Trading signal dict from SignalGenerator.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.is_configured():
            logger.warning("Email not configured, printing signal to console")
            self._print_signal(signal)
            return False

        subject = self._build_subject(signal)
        html_body = self._build_html(signal)
        text_body = self._build_text(signal)

        return self._send_email(subject, html_body, text_body)

    def send_batch(self, signals):
        """Send multiple signals in a single digest email.

        Args:
            signals: List of trading signal dicts.

        Returns:
            True if sent successfully.
        """
        if not signals:
            return True

        if len(signals) == 1:
            return self.send_signal(signals[0])

        if not self.is_configured():
            logger.warning("Email not configured, printing signals to console")
            for s in signals:
                self._print_signal(s)
            return False

        subject = f"[Trump Sentinel] {len(signals)} Trading Signals"
        html_parts = [self._build_html(s) for s in signals]
        html_body = "<hr style='margin:20px 0'>".join(html_parts)
        html_body = f"""
        <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto">
        <h1 style="color:#1a1a1a">Trump Sentinel - {len(signals)} Signals</h1>
        <p style="color:#666">Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
        {html_body}
        <hr><p style="color:#999;font-size:12px">
        Disclaimer: This is an automated trading signal. Not financial advice.
        Always do your own research before trading.
        </p></body></html>
        """

        text_body = "\n\n" + "="*60 + "\n\n".join(
            [self._build_text(s) for s in signals]
        )

        return self._send_email(subject, html_body, text_body)

    def _send_email(self, subject, html_body, text_body):
        """Send an email via SMTP."""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.user
            msg['To'] = ", ".join(self.recipients)

            msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(msg)

            logger.info(f"Email sent: {subject}")
            return True

        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False

    @staticmethod
    def _build_subject(signal):
        """Build email subject line."""
        action = signal.get('action', 'UNKNOWN')
        urgency = signal.get('urgency', 'watch')
        confidence = signal.get('confidence', 0)
        market_q = signal.get('market', {}).get('question', '')[:60]

        urgency_prefix = {
            'immediate': '[URGENT]',
            'watch': '[SIGNAL]',
            'low': '[INFO]',
        }.get(urgency, '[SIGNAL]')

        return f"{urgency_prefix} {action} - {market_q} ({confidence}% conf)"

    @staticmethod
    def _build_html(signal):
        """Build HTML email body for a single signal."""
        post = signal.get('post', {})
        analysis = signal.get('analysis', {})
        market = signal.get('market', {})
        action = signal.get('action', 'UNKNOWN')
        confidence = signal.get('confidence', 0)

        # Color coding
        if 'BUY_YES' in action:
            action_color = '#22c55e'  # green
            action_label = 'BUY YES'
        elif 'BUY_NO' in action:
            action_color = '#ef4444'  # red
            action_label = 'BUY NO'
        else:
            action_color = '#666'
            action_label = action

        urgency = signal.get('urgency', 'watch')
        urgency_colors = {
            'immediate': '#ef4444',
            'watch': '#f59e0b',
            'low': '#6b7280',
        }

        source_name = "Truth Social" if post.get('source') == 'truth_social' else "X/Twitter"

        return f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:20px;margin:10px 0">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px">
                <span style="background:{action_color};color:white;padding:6px 16px;border-radius:4px;
                       font-weight:bold;font-size:18px">{action_label}</span>
                <span style="background:{urgency_colors.get(urgency, '#6b7280')};color:white;
                       padding:4px 12px;border-radius:4px;font-size:14px">
                    {urgency.upper()}</span>
            </div>

            <h2 style="color:#1a1a1a;margin:10px 0">
                <a href="{market.get('url', '#')}" style="color:#2563eb;text-decoration:none">
                    {market.get('question', 'Unknown Market')}</a>
            </h2>

            <table style="width:100%;border-collapse:collapse;margin:15px 0">
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;width:40%">
                        Confidence</td>
                    <td style="padding:8px;border-bottom:1px solid #eee">
                        <strong>{confidence}%</strong></td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold">
                        Current YES Price</td>
                    <td style="padding:8px;border-bottom:1px solid #eee">
                        ${market.get('yes_price', 0):.2f}</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold">
                        Current NO Price</td>
                    <td style="padding:8px;border-bottom:1px solid #eee">
                        ${market.get('no_price', 0):.2f}</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold">
                        Suggested Size</td>
                    <td style="padding:8px;border-bottom:1px solid #eee">
                        ${signal.get('suggested_size_usdc', 0):.2f} USDC</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold">
                        Impact Score</td>
                    <td style="padding:8px;border-bottom:1px solid #eee">
                        {analysis.get('impact_score', 0)}/10</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold">
                        Topic</td>
                    <td style="padding:8px;border-bottom:1px solid #eee">
                        {analysis.get('topic', 'unknown')}</td>
                </tr>
            </table>

            <div style="background:#f9fafb;border-radius:4px;padding:12px;margin:10px 0">
                <strong>Source:</strong> {source_name}<br>
                <strong>Post:</strong> {post.get('content', '')[:300]}
                {'...' if len(post.get('content', '')) > 300 else ''}<br>
                {f'<a href="{post.get("url")}" style="color:#2563eb">View original post</a>'
                 if post.get('url') else ''}
            </div>

            <div style="background:#fffbeb;border-radius:4px;padding:12px;margin:10px 0">
                <strong>Reasoning:</strong> {signal.get('reasoning', '')}
            </div>
        </div>
        """

    @staticmethod
    def _build_text(signal):
        """Build plain text email body for a single signal."""
        post = signal.get('post', {})
        analysis = signal.get('analysis', {})
        market = signal.get('market', {})

        source_name = "Truth Social" if post.get('source') == 'truth_social' else "X/Twitter"

        return f"""
=== TRADING SIGNAL ===
Action: {signal.get('action', 'UNKNOWN')}
Urgency: {signal.get('urgency', 'watch').upper()}
Confidence: {signal.get('confidence', 0)}%

Market: {market.get('question', 'Unknown')}
URL: {market.get('url', '')}
YES Price: ${market.get('yes_price', 0):.2f}
NO Price: ${market.get('no_price', 0):.2f}
Suggested Size: ${signal.get('suggested_size_usdc', 0):.2f} USDC

Source: {source_name}
Post: {post.get('content', '')[:300]}
Post URL: {post.get('url', '')}

Impact: {analysis.get('impact_score', 0)}/10 | Topic: {analysis.get('topic', 'unknown')}
Reasoning: {signal.get('reasoning', '')}

Disclaimer: Automated trading signal. Not financial advice.
""".strip()

    @staticmethod
    def _print_signal(signal):
        """Print signal to console when email is not configured."""
        post = signal.get('post', {})
        market = signal.get('market', {})

        print("\n" + "="*60)
        print(f"  TRADING SIGNAL: {signal.get('action', 'UNKNOWN')}")
        print(f"  Urgency: {signal.get('urgency', 'watch').upper()}")
        print(f"  Confidence: {signal.get('confidence', 0)}%")
        print("-"*60)
        print(f"  Market: {market.get('question', 'Unknown')}")
        print(f"  YES: ${market.get('yes_price', 0):.2f} | "
              f"NO: ${market.get('no_price', 0):.2f}")
        print(f"  Size: ${signal.get('suggested_size_usdc', 0):.2f} USDC")
        print("-"*60)
        print(f"  Post: {post.get('content', '')[:200]}")
        print(f"  Reasoning: {signal.get('reasoning', '')[:200]}")
        print("="*60 + "\n")
