#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邮件通知模块 - 通过QQ SMTP发送情绪选股报告
"""

import re
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import (
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PORT,
    EMAIL_SENDER,
    EMAIL_PASSWORD,
    EMAIL_RECEIVERS,
)

logger = logging.getLogger(__name__)


class EmailSender:
    """邮件发送器 - QQ邮箱SMTP"""

    def __init__(self):
        self.smtp_host = EMAIL_SMTP_HOST
        self.smtp_port = EMAIL_SMTP_PORT
        self.sender = EMAIL_SENDER
        self.password = EMAIL_PASSWORD
        self.receivers = [r.strip() for r in EMAIL_RECEIVERS if r.strip()]
        self.available = bool(self.sender and self.password)

        if not self.available:
            logger.warning("邮件发送器未配置: EMAIL_SENDER 或 EMAIL_PASSWORD 为空")

    def send(self, subject: str, html_content: str) -> bool:
        """
        发送HTML邮件到所有收件人。

        Args:
            subject: 邮件主题
            html_content: HTML格式的邮件正文

        Returns:
            True 成功, False 失败
        """
        if not self.available:
            logger.warning("邮件发送器不可用，跳过发送")
            return False

        if not self.receivers:
            logger.warning("收件人列表为空，跳过发送")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.receivers)
            msg["Subject"] = subject

            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)

            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.receivers, msg.as_string())

            logger.info("邮件发送成功: %s -> %s", subject, self.receivers)
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error("邮件认证失败（请检查授权码）: %s", e)
            return False
        except smtplib.SMTPException as e:
            logger.error("SMTP错误: %s", e)
            return False
        except OSError as e:
            logger.error("网络连接错误: %s", e)
            return False
        except Exception as e:
            logger.error("邮件发送未知异常: %s", e)
            return False

    def send_daily_report(self, report_markdown: str, date: str) -> bool:
        """
        发送每日选股报告。

        Args:
            report_markdown: Markdown格式的报告内容
            date: 日期字符串，如 "2026-03-26"

        Returns:
            True 成功, False 失败
        """
        try:
            html_content = self._markdown_to_html(report_markdown)
            subject = f"\U0001f4ca A股情绪选股报告 | {date}"
            return self.send(subject, html_content)
        except Exception as e:
            logger.error("发送每日报告失败: %s", e)
            return False

    def _markdown_to_html(self, md: str) -> str:
        """
        将Markdown文本转换为适合邮件客户端的HTML。

        支持: 标题(h1-h3), 粗体, 列表, 分隔线, 简单表格。

        Args:
            md: Markdown文本

        Returns:
            完整的HTML文档字符串
        """
        lines = md.split("\n")
        html_lines = []
        in_table = False
        in_list = False

        for line in lines:
            stripped = line.strip()

            # 空行
            if not stripped:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                if in_table:
                    html_lines.append("</tbody></table>")
                    in_table = False
                html_lines.append("<br>")
                continue

            # 分隔线
            if stripped in ("---", "***", "___"):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                if in_table:
                    html_lines.append("</tbody></table>")
                    in_table = False
                html_lines.append('<hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">')
                continue

            # 表格行
            if "|" in stripped and stripped.startswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                # 跳过分隔行 (|---|---|)
                if all(re.match(r"^[-:]+$", c) for c in cells):
                    continue
                if not in_table:
                    in_table = True
                    html_lines.append(
                        '<table style="border-collapse:collapse;width:100%;margin:8px 0;'
                        'font-size:14px;">'
                    )
                    # 第一行作为表头
                    html_lines.append("<thead><tr>")
                    for cell in cells:
                        cell_html = self._inline_format(cell)
                        html_lines.append(
                            f'<th style="border:1px solid #ddd;padding:8px 12px;'
                            f'background:#f5f5f5;text-align:left;">{cell_html}</th>'
                        )
                    html_lines.append("</tr></thead><tbody>")
                    continue
                # 数据行
                html_lines.append("<tr>")
                for cell in cells:
                    cell_html = self._inline_format(cell)
                    html_lines.append(
                        f'<td style="border:1px solid #ddd;padding:8px 12px;">'
                        f'{cell_html}</td>'
                    )
                html_lines.append("</tr>")
                continue

            # 如果在表格中遇到非表格行，关闭表格
            if in_table:
                html_lines.append("</tbody></table>")
                in_table = False

            # 标题
            if stripped.startswith("### "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                content = self._inline_format(stripped[4:])
                html_lines.append(
                    f'<h3 style="color:#333;font-size:16px;margin:12px 0 8px;">'
                    f'{content}</h3>'
                )
                continue
            if stripped.startswith("## "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                content = self._inline_format(stripped[3:])
                html_lines.append(
                    f'<h2 style="color:#222;font-size:18px;margin:16px 0 8px;'
                    f'border-bottom:1px solid #eee;padding-bottom:4px;">'
                    f'{content}</h2>'
                )
                continue
            if stripped.startswith("# "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                content = self._inline_format(stripped[2:])
                html_lines.append(
                    f'<h1 style="color:#111;font-size:22px;margin:20px 0 12px;">'
                    f'{content}</h1>'
                )
                continue

            # 无序列表
            if stripped.startswith(("- ", "* ", "• ")):
                if not in_list:
                    in_list = True
                    html_lines.append(
                        '<ul style="margin:4px 0;padding-left:20px;">'
                    )
                item_text = self._inline_format(stripped[2:])
                html_lines.append(
                    f'<li style="margin:2px 0;">{item_text}</li>'
                )
                continue

            # 有序列表
            m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
            if m:
                if not in_list:
                    in_list = True
                    html_lines.append(
                        '<ul style="margin:4px 0;padding-left:20px;'
                        'list-style-type:decimal;">'
                    )
                item_text = self._inline_format(m.group(2))
                html_lines.append(
                    f'<li style="margin:2px 0;">{item_text}</li>'
                )
                continue

            # 关闭列表
            if in_list:
                html_lines.append("</ul>")
                in_list = False

            # 斜体段落 (用于免责声明等)
            if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
                content = self._inline_format(stripped)
                html_lines.append(
                    f'<p style="color:#999;font-size:12px;margin:4px 0;">'
                    f'{content}</p>'
                )
                continue

            # 普通段落
            content = self._inline_format(stripped)
            html_lines.append(
                f'<p style="margin:4px 0;line-height:1.6;">{content}</p>'
            )

        # 关闭未关闭的标签
        if in_list:
            html_lines.append("</ul>")
        if in_table:
            html_lines.append("</tbody></table>")

        body = "\n".join(html_lines)

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',
'Hiragino Sans GB','Microsoft YaHei',sans-serif;max-width:680px;margin:0 auto;
padding:20px;color:#333;background:#ffffff;font-size:14px;line-height:1.6;">
{body}
<br>
<p style="color:#aaa;font-size:11px;text-align:center;margin-top:24px;">
此邮件由 A股情绪选股系统 自动发送
</p>
</body>
</html>"""

    @staticmethod
    def _inline_format(text: str) -> str:
        """处理行内Markdown格式: 粗体、斜体。"""
        # 粗体 **text**
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        # 斜体 *text*
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        return text
