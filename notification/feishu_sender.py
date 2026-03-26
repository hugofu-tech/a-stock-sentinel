#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书通知模块 - 通过飞书API/Webhook发送情绪选股报告
"""

import logging

import requests

from config import (
    FEISHU_WEBHOOK_URL,
    FEISHU_APP_ID,
    FEISHU_APP_SECRET,
)

logger = logging.getLogger(__name__)

# 飞书文本消息长度上限（字符数）
FEISHU_TEXT_MAX_LENGTH = 4000

# 请求超时（秒）
REQUEST_TIMEOUT = 15


class FeishuSender:
    """飞书消息发送器 - 支持API和Webhook两种方式"""

    def __init__(self):
        self.app_id = FEISHU_APP_ID
        self.app_secret = FEISHU_APP_SECRET
        self.webhook_url = FEISHU_WEBHOOK_URL
        self._token = None
        self.available = bool(self.app_id and self.app_secret)

        if not self.available:
            logger.warning(
                "飞书API发送器未配置: FEISHU_APP_ID 或 FEISHU_APP_SECRET 为空"
            )
        if not self.webhook_url:
            logger.info("飞书Webhook未配置，webhook发送不可用")

    def _get_token(self) -> str:
        """
        获取飞书 tenant_access_token。

        Returns:
            token字符串，失败返回空字符串
        """
        if self._token:
            return self._token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }

        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            data = resp.json()

            if data.get("code") == 0:
                self._token = data.get("tenant_access_token", "")
                logger.info("飞书token获取成功")
                return self._token
            else:
                logger.error("飞书token获取失败: code=%s, msg=%s",
                             data.get("code"), data.get("msg"))
                return ""

        except requests.exceptions.Timeout:
            logger.error("飞书token请求超时")
            return ""
        except requests.exceptions.ConnectionError:
            logger.error("飞书token请求网络连接失败")
            return ""
        except Exception as e:
            logger.error("飞书token请求异常: %s", e)
            return ""

    def send_message(self, text: str, receive_id: str = "") -> bool:
        """
        通过飞书API发送文本消息。

        Args:
            text: 消息文本
            receive_id: 接收者的open_id，为空则跳过

        Returns:
            True 成功, False 失败
        """
        if not self.available:
            logger.warning("飞书API发送器不可用，跳过发送")
            return False

        if not receive_id:
            logger.warning("receive_id为空，跳过API发送")
            return False

        token = self._get_token()
        if not token:
            logger.error("无法获取飞书token，发送失败")
            return False

        url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": f'{{"text": {self._escape_json_string(text)}}}',
        }

        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
            )
            data = resp.json()

            if data.get("code") == 0:
                logger.info("飞书消息发送成功: receive_id=%s", receive_id)
                return True
            else:
                # token可能过期，清空缓存以便下次重新获取
                if data.get("code") == 99991663:
                    self._token = None
                    logger.warning("飞书token已过期，已清除缓存")
                logger.error(
                    "飞书消息发送失败: code=%s, msg=%s",
                    data.get("code"), data.get("msg"),
                )
                return False

        except requests.exceptions.Timeout:
            logger.error("飞书消息发送超时")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("飞书消息发送网络连接失败")
            return False
        except Exception as e:
            logger.error("飞书消息发送异常: %s", e)
            return False

    def send_daily_report(self, report_text: str, date: str) -> bool:
        """
        发送每日选股报告。

        优先使用webhook发送，如果webhook不可用则尝试API发送。

        Args:
            report_text: 报告文本内容
            date: 日期字符串，如 "2026-03-26"

        Returns:
            True 成功, False 失败
        """
        try:
            header = f"\U0001f4ca A股情绪选股报告 | {date}\n{'=' * 30}\n\n"
            full_text = header + report_text

            # 截断过长内容
            if len(full_text) > FEISHU_TEXT_MAX_LENGTH:
                truncated_notice = "\n\n... (内容过长已截断，完整报告请查看邮件)"
                max_len = FEISHU_TEXT_MAX_LENGTH - len(truncated_notice)
                full_text = full_text[:max_len] + truncated_notice

            # 优先webhook
            if self.webhook_url:
                return self.send_webhook(full_text)

            # 备选API（需要receive_id，此处无法自动获取，记录日志）
            logger.warning("飞书webhook未配置，且send_daily_report无receive_id，无法发送")
            return False

        except Exception as e:
            logger.error("发送飞书每日报告失败: %s", e)
            return False

    def send_webhook(self, text: str) -> bool:
        """
        通过飞书Webhook发送文本消息（群机器人）。

        Args:
            text: 消息文本

        Returns:
            True 成功, False 失败
        """
        if not self.webhook_url:
            logger.warning("飞书Webhook URL未配置，跳过发送")
            return False

        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }

        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            data = resp.json()

            if data.get("code") == 0:
                logger.info("飞书Webhook消息发送成功")
                return True
            else:
                logger.error(
                    "飞书Webhook发送失败: code=%s, msg=%s",
                    data.get("code"), data.get("msg"),
                )
                return False

        except requests.exceptions.Timeout:
            logger.error("飞书Webhook请求超时")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("飞书Webhook网络连接失败")
            return False
        except Exception as e:
            logger.error("飞书Webhook发送异常: %s", e)
            return False

    @staticmethod
    def _escape_json_string(text: str) -> str:
        """将文本转义为JSON字符串值（含引号）。"""
        import json
        return json.dumps(text, ensure_ascii=False)
