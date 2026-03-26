"""LLM情绪验证分析器 — 使用Kimi K2.5 API对候选股票进行深度情绪分析"""

import json
import logging
import re
import time
from typing import Dict, List

import config

logger = logging.getLogger(__name__)

# 尝试导入 openai，不可用时优雅降级
try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    logger.warning("openai 包未安装，LLM情绪分析功能不可用。请执行: pip install openai")

# 默认中性结果，API不可用或调用失败时返回
_NEUTRAL_DEFAULT: dict = {
    "sentiment": "neutral",
    "score": 50,
    "confidence": 0.0,
    "key_themes": [],
    "risk_signals": [],
    "summary": "LLM分析不可用，返回中性默认值。",
    "contrarian_signal": False,
}

# 重试配置
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2  # 指数退避基数（秒）
_REQUEST_TIMEOUT = 60  # 单次请求超时（秒）


class LLMAnalyzer:
    """基于Kimi K2.5的LLM情绪验证分析器。

    使用OpenAI兼容接口调用Kimi K2.5，对SnowNLP初筛后的候选股票
    进行更深入的情绪分析和风险信号识别。
    """

    def __init__(self):
        self.available = False
        self.model = config.LLM_MODEL
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0

        if not _HAS_OPENAI:
            logger.warning("LLMAnalyzer: openai库未安装，分析功能已禁用")
            return

        if not config.LLM_API_KEY:
            logger.warning("LLMAnalyzer: LLM_API_KEY未配置，分析功能已禁用")
            return

        try:
            import httpx
            self.client = OpenAI(
                api_key=config.LLM_API_KEY,
                base_url=config.LLM_BASE_URL,
                default_headers={"User-Agent": "claude-code/2.1.84"},
                http_client=httpx.Client(
                    headers={"User-Agent": "claude-code/2.1.84"},
                    verify=False,
                ),
            )
            self.available = True
            logger.info(
                "LLMAnalyzer初始化成功: model=%s, base_url=%s",
                self.model,
                config.LLM_BASE_URL,
            )
        except Exception as exc:
            logger.error("LLMAnalyzer初始化失败: %s", exc)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def analyze_stock_sentiment(
        self,
        stock_code: str,
        stock_name: str,
        posts_titles: List[str],
        market_context: str = "",
    ) -> dict:
        """对单只股票的社交帖子标题进行LLM情绪分析。

        Args:
            stock_code: 股票代码，如 '600519'
            stock_name: 股票名称，如 '贵州茅台'
            posts_titles: 社交帖子标题列表
            market_context: 可选的市场背景信息

        Returns:
            包含 sentiment / score / confidence / key_themes /
            risk_signals / summary / contrarian_signal 的字典。
            API不可用或失败时返回中性默认值。
        """
        if not self.available:
            return dict(_NEUTRAL_DEFAULT)

        if not posts_titles:
            logger.debug("股票 %s(%s) 无帖子标题，跳过LLM分析", stock_code, stock_name)
            return dict(_NEUTRAL_DEFAULT)

        prompt = self._build_prompt(stock_code, stock_name, posts_titles, market_context)

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是一位专业的A股市场情绪分析师。你擅长从投资者社交讨论中"
                                "提取情绪信号、识别风险和发现潜在的逆向交易机会。"
                                "请始终以JSON格式输出分析结果。"
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    timeout=_REQUEST_TIMEOUT,
                )

                # 记录token用量
                if response.usage:
                    self._total_prompt_tokens += response.usage.prompt_tokens
                    self._total_completion_tokens += response.usage.completion_tokens
                    logger.debug(
                        "Token用量 [%s]: prompt=%d, completion=%d",
                        stock_code,
                        response.usage.prompt_tokens,
                        response.usage.completion_tokens,
                    )

                response_text = response.choices[0].message.content or ""
                result = self._parse_response(response_text)
                logger.info(
                    "LLM分析完成 [%s %s]: sentiment=%s, score=%d, confidence=%.2f",
                    stock_code,
                    stock_name,
                    result["sentiment"],
                    result["score"],
                    result["confidence"],
                )
                return result

            except Exception as exc:
                wait_time = _RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "LLM API调用失败 [%s] 第%d/%d次: %s，%.1f秒后重试",
                    stock_code,
                    attempt,
                    _MAX_RETRIES,
                    exc,
                    wait_time,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(wait_time)

        logger.error("LLM API调用最终失败 [%s %s]，返回中性默认值", stock_code, stock_name)
        return dict(_NEUTRAL_DEFAULT)

    def batch_analyze(self, candidates: List[dict]) -> Dict[str, dict]:
        """批量分析候选股票列表。

        Args:
            candidates: 候选列表，每项包含:
                - stock_code: 股票代码
                - stock_name: 股票名称
                - titles: 帖子标题列表
                - market_context: 市场背景（可选）

        Returns:
            {stock_code: analysis_result} 字典
        """
        results: Dict[str, dict] = {}

        if not self.available:
            logger.warning("LLMAnalyzer不可用，批量分析返回中性默认值")
            for candidate in candidates:
                results[candidate["stock_code"]] = dict(_NEUTRAL_DEFAULT)
            return results

        total = len(candidates)
        for idx, candidate in enumerate(candidates, 1):
            stock_code = candidate["stock_code"]
            stock_name = candidate.get("stock_name", "")
            titles = candidate.get("titles", [])
            market_context = candidate.get("market_context", "")

            logger.info("LLM批量分析进度: %d/%d — %s %s", idx, total, stock_code, stock_name)

            result = self.analyze_stock_sentiment(
                stock_code=stock_code,
                stock_name=stock_name,
                posts_titles=titles,
                market_context=market_context,
            )
            results[stock_code] = result

            # 在请求之间加入短暂延时，避免触发速率限制
            if idx < total:
                time.sleep(1.0)

        logger.info(
            "LLM批量分析完成: %d只股票, 累计token用量: prompt=%d, completion=%d",
            total,
            self._total_prompt_tokens,
            self._total_completion_tokens,
        )
        return results

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _build_prompt(
        self,
        stock_code: str,
        stock_name: str,
        titles: List[str],
        market_context: str,
    ) -> str:
        """构造发送给LLM的分析提示词。"""
        # 限制标题数量，避免prompt过长
        max_titles = 50
        if len(titles) > max_titles:
            titles = titles[:max_titles]

        titles_text = "\n".join(f"  {i}. {t}" for i, t in enumerate(titles, 1))

        context_section = ""
        if market_context:
            context_section = f"\n【市场背景】\n{market_context}\n"

        prompt = f"""请对以下A股股票的投资者社交讨论进行深度情绪分析。

【分析目标】
股票代码: {stock_code}
股票名称: {stock_name}
{context_section}
【投资者讨论帖子标题】（共{len(titles)}条）
{titles_text}

【分析要求】
请从以下维度进行分析，并以严格的JSON格式输出结果：

1. **整体情绪判断**（sentiment）: 判断投资者整体情绪倾向
   - "bullish"（看多）: 乐观情绪主导，多数讨论看好后市
   - "neutral"（中性）: 多空分歧明显或讨论以信息分享为主
   - "bearish"（看空）: 悲观情绪主导，多数讨论担忧后市

2. **情绪评分**（score）: 0-100的整数
   - 0-30: 极度看空
   - 31-45: 偏空
   - 46-55: 中性
   - 56-70: 偏多
   - 71-100: 极度看多

3. **置信度**（confidence）: 0-1的浮点数，表示你对分析结果的确信程度

4. **关键主题**（key_themes）: 投资者讨论的核心话题列表（3-5个）

5. **风险信号**（risk_signals）: 检测到的风险信号列表，如：
   - 过度乐观/一致看多（可能见顶）
   - 恐慌性抛售言论
   - 涉及重大利空消息
   - 异常炒作迹象
   - 基本面质疑

6. **摘要**（summary）: 用1-2句中文总结投资者情绪状态和核心关注点

7. **逆向信号**（contrarian_signal）: 布尔值
   - true: 情绪过于极端（极度乐观或极度悲观），可能出现反转
   - false: 情绪正常范围

【输出格式】
请严格按照以下JSON格式输出，不要包含其他文字：
```json
{{
  "sentiment": "bullish/neutral/bearish",
  "score": 65,
  "confidence": 0.8,
  "key_themes": ["主题1", "主题2", "主题3"],
  "risk_signals": ["风险信号1"],
  "summary": "一句话中文摘要",
  "contrarian_signal": false
}}
```"""
        return prompt

    def _parse_response(self, response_text: str) -> dict:
        """从LLM响应文本中提取结构化分析结果。

        优先尝试JSON解析，失败时回退到文本解析，
        始终返回包含所有必要字段的有效字典。
        """
        result = dict(_NEUTRAL_DEFAULT)

        if not response_text:
            return result

        # 第一步：尝试直接JSON解析
        parsed = self._try_parse_json(response_text)

        if parsed is None:
            # 第二步：尝试从markdown代码块中提取JSON
            json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL)
            if json_match:
                parsed = self._try_parse_json(json_match.group(1))

        if parsed is None:
            # 第三步：尝试找到第一个 { 到最后一个 } 之间的内容
            brace_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if brace_match:
                parsed = self._try_parse_json(brace_match.group(0))

        if parsed is None:
            logger.warning("无法从LLM响应中解析JSON，使用文本回退解析")
            return self._fallback_text_parse(response_text)

        # 验证并填充字段
        return self._validate_and_fill(parsed)

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        """尝试解析JSON字符串，失败返回None。"""
        try:
            data = json.loads(text.strip())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    @staticmethod
    def _validate_and_fill(parsed: dict) -> dict:
        """验证解析结果并填充缺失字段为默认值。"""
        result = dict(_NEUTRAL_DEFAULT)

        # sentiment
        sentiment = str(parsed.get("sentiment", "neutral")).lower().strip()
        if sentiment in ("bullish", "neutral", "bearish"):
            result["sentiment"] = sentiment

        # score
        try:
            score = int(parsed.get("score", 50))
            result["score"] = max(0, min(100, score))
        except (TypeError, ValueError):
            pass

        # confidence
        try:
            confidence = float(parsed.get("confidence", 0.0))
            result["confidence"] = max(0.0, min(1.0, round(confidence, 4)))
        except (TypeError, ValueError):
            pass

        # key_themes
        themes = parsed.get("key_themes", [])
        if isinstance(themes, list):
            result["key_themes"] = [str(t) for t in themes if t]

        # risk_signals
        signals = parsed.get("risk_signals", [])
        if isinstance(signals, list):
            result["risk_signals"] = [str(s) for s in signals if s]

        # summary
        summary = parsed.get("summary", "")
        if isinstance(summary, str) and summary.strip():
            result["summary"] = summary.strip()

        # contrarian_signal
        contrarian = parsed.get("contrarian_signal", False)
        if isinstance(contrarian, bool):
            result["contrarian_signal"] = contrarian
        elif isinstance(contrarian, str):
            result["contrarian_signal"] = contrarian.lower() in ("true", "1", "yes")

        return result

    def _fallback_text_parse(self, text: str) -> dict:
        """当JSON解析完全失败时，从文本中尽力提取信息。"""
        result = dict(_NEUTRAL_DEFAULT)
        text_lower = text.lower()

        # 尝试判断情绪方向
        bullish_keywords = ["看多", "看涨", "利好", "bullish", "乐观", "上涨"]
        bearish_keywords = ["看空", "看跌", "利空", "bearish", "悲观", "下跌"]

        bullish_count = sum(1 for kw in bullish_keywords if kw in text_lower)
        bearish_count = sum(1 for kw in bearish_keywords if kw in text_lower)

        if bullish_count > bearish_count:
            result["sentiment"] = "bullish"
            result["score"] = 65
        elif bearish_count > bullish_count:
            result["sentiment"] = "bearish"
            result["score"] = 35

        # 置信度较低，因为是文本回退
        result["confidence"] = 0.3
        result["summary"] = text[:200].strip() if len(text) > 200 else text.strip()

        logger.debug("文本回退解析结果: sentiment=%s, score=%d", result["sentiment"], result["score"])
        return result

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def get_token_usage(self) -> dict:
        """返回累计token用量统计。"""
        return {
            "prompt_tokens": self._total_prompt_tokens,
            "completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
        }
