"""
腾讯财经行情 API — akshare ``stock_zh_a_spot_em()`` 的备选方案

使用 ``http://qt.gtimg.cn/q=...`` 接口批量获取 A 股实时行情。
当 akshare 在沙盒或腾讯云环境不稳定时，本模块作为可靠的降级备选。

主要函数:
    get_all_stock_codes()   — 获取全部 A 股代码列表
    fetch_realtime_quotes() — 批量查询腾讯行情
    get_stock_universe()    — 一步到位，替代 ak.stock_zh_a_spot_em()
"""

import logging
import re
import time
from typing import List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# 腾讯行情接口
_TENCENT_QT_URL = "http://qt.gtimg.cn/q="

# 每批最多查询 400 只股票
_BATCH_SIZE = 400

# 请求超时（秒）
_REQUEST_TIMEOUT = 15

# 重试次数
_MAX_RETRIES = 2

# User-Agent
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "http://finance.qq.com/",
}


# ======================================================================
# 1. 获取全部 A 股代码
# ======================================================================

def get_all_stock_codes() -> List[str]:
    """获取全部 A 股股票代码。

    使用 akshare 的 ``stock_info_sh_name_code()`` 和
    ``stock_info_sz_name_code()`` 接口，这两个接口比
    ``stock_zh_a_spot_em()`` 稳定得多（仅拉取代码列表，不涉及行情）。

    Returns:
        代码列表，如 ['600519', '000001', ...]
    """
    codes: List[str] = []

    # --- 上海 ---
    try:
        import akshare as ak
        sh_df = ak.stock_info_sh_name_code()
        if sh_df is not None and not sh_df.empty:
            # 列名通常为 "证券代码" 或 "code"
            code_col = None
            for col_name in ("证券代码", "code", "SECURITY_CODE_A"):
                if col_name in sh_df.columns:
                    code_col = col_name
                    break
            if code_col is None and len(sh_df.columns) > 0:
                code_col = sh_df.columns[0]

            if code_col:
                sh_codes = sh_df[code_col].astype(str).tolist()
                # 只保留 6 位数字（排除基金、债券等）
                sh_codes = [c.strip() for c in sh_codes if re.match(r"^6\d{5}$", c.strip())]
                codes.extend(sh_codes)
                logger.info("[TencentAPI] 上海股票代码: %d 只", len(sh_codes))
    except Exception as exc:
        logger.warning("[TencentAPI] 获取上海代码失败: %s", exc)

    # --- 深圳 ---
    try:
        import akshare as ak
        sz_df = ak.stock_info_sz_name_code(indicator="A股列表")
        if sz_df is not None and not sz_df.empty:
            code_col = None
            for col_name in ("A股代码", "code", "证券代码"):
                if col_name in sz_df.columns:
                    code_col = col_name
                    break
            if code_col is None and len(sz_df.columns) > 0:
                code_col = sz_df.columns[0]

            if code_col:
                sz_codes = sz_df[code_col].astype(str).tolist()
                # 保留 000xxx, 001xxx, 002xxx, 003xxx, 300xxx 开头的 A 股
                sz_codes = [
                    c.strip() for c in sz_codes
                    if re.match(r"^(000|001|002|003|300)\d{3}$", c.strip())
                ]
                codes.extend(sz_codes)
                logger.info("[TencentAPI] 深圳股票代码: %d 只", len(sz_codes))
    except Exception as exc:
        logger.warning("[TencentAPI] 获取深圳代码失败: %s", exc)

    if not codes:
        logger.warning("[TencentAPI] 未能获取任何股票代码")

    # 去重
    codes = list(dict.fromkeys(codes))
    logger.info("[TencentAPI] 合计: %d 只 A 股代码", len(codes))
    return codes


def _code_to_tencent(code: str) -> str:
    """将 6 位股票代码转换为腾讯格式。

    上海: 6xxxxx -> sh6xxxxx
    深圳: 0xxxxx / 3xxxxx -> sz0xxxxx / sz3xxxxx
    """
    code = code.strip()
    if code.startswith("6"):
        return f"sh{code}"
    else:
        return f"sz{code}"


# ======================================================================
# 2. 批量获取腾讯行情
# ======================================================================

def _parse_tencent_line(line: str) -> Optional[dict]:
    """解析腾讯行情 API 单行响应。

    格式示例:
        v_sh600519="1~贵州茅台~600519~1800.00~1795.00~..."

    字段（``~`` 分隔，0-based）:
        1: 名称
        2: 代码
        3: 最新价
        4: 昨收价
        32: 涨跌幅(%)
        38: 换手率(%)
        37: 成交额(万)
        49: 流通市值(亿)
        36: 成交量(手)

    Returns:
        解析后的字典，或 None（解析失败时）。
    """
    if not line or "=" not in line:
        return None

    # 提取引号内的内容
    match = re.search(r'"(.+)"', line)
    if not match:
        return None

    content = match.group(1)
    fields = content.split("~")

    # 最少需要的字段数
    if len(fields) < 40:
        return None

    try:
        code = fields[2].strip()
        name = fields[1].strip()
        price_str = fields[3].strip()
        yesterday_close_str = fields[4].strip()

        if not price_str or float(price_str) <= 0:
            return None

        price = float(price_str)
        yesterday_close = float(yesterday_close_str) if yesterday_close_str else 0

        # 涨跌幅: 优先用 index 32，不可用时自行计算
        change_pct = 0.0
        if len(fields) > 32 and fields[32].strip():
            try:
                change_pct = float(fields[32].strip())
            except (ValueError, IndexError):
                pass
        if change_pct == 0.0 and yesterday_close > 0:
            change_pct = round((price - yesterday_close) / yesterday_close * 100, 2)

        # 换手率
        turnover_rate = 0.0
        if len(fields) > 38 and fields[38].strip():
            try:
                turnover_rate = float(fields[38].strip())
            except (ValueError, IndexError):
                pass

        # 成交额（腾讯返回单位为万元，akshare 的单位为元）
        amount = 0.0
        if len(fields) > 37 and fields[37].strip():
            try:
                amount = float(fields[37].strip()) * 10000  # 转为元
            except (ValueError, IndexError):
                pass

        # 流通市值（腾讯返回单位为亿元，akshare 的单位为元）
        market_cap = 0.0
        if len(fields) > 44 and fields[44].strip():
            try:
                market_cap = float(fields[44].strip()) * 100000000  # 转为元
            except (ValueError, IndexError):
                pass

        # 量比
        vol_ratio = 0.0
        if len(fields) > 49 and fields[49].strip():
            try:
                vol_ratio = float(fields[49].strip())
            except (ValueError, IndexError):
                pass

        # 成交量（手）
        volume = 0.0
        if len(fields) > 36 and fields[36].strip():
            try:
                volume = float(fields[36].strip())
            except (ValueError, IndexError):
                pass

        return {
            "代码": code,
            "名称": name,
            "最新价": price,
            "涨跌幅": change_pct,
            "换手率": turnover_rate,
            "量比": vol_ratio if vol_ratio > 0 else 1.0,
            "流通市值": market_cap,
            "成交额": amount,
        }

    except (ValueError, IndexError) as exc:
        logger.debug("[TencentAPI] 解析行失败: %s | line=%s", exc, line[:80])
        return None


def fetch_realtime_quotes(codes: List[str]) -> pd.DataFrame:
    """从腾讯财经 API 批量获取实时行情。

    Args:
        codes: 股票代码列表，如 ['600519', '000001', ...]

    Returns:
        DataFrame，列名与 akshare ``stock_zh_a_spot_em()`` 兼容:
            代码, 名称, 最新价, 涨跌幅, 换手率, 量比, 流通市值, 成交额
    """
    if not codes:
        return pd.DataFrame()

    # 转换为腾讯格式
    tencent_codes = [_code_to_tencent(c) for c in codes]

    all_records: List[dict] = []

    # 分批请求
    total_batches = (len(tencent_codes) + _BATCH_SIZE - 1) // _BATCH_SIZE
    for batch_idx in range(total_batches):
        start = batch_idx * _BATCH_SIZE
        end = start + _BATCH_SIZE
        batch = tencent_codes[start:end]

        query_str = ",".join(batch)
        url = f"{_TENCENT_QT_URL}{query_str}"

        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.get(
                    url,
                    headers=_HEADERS,
                    timeout=_REQUEST_TIMEOUT,
                )
                resp.encoding = "gbk"

                if resp.status_code != 200:
                    logger.warning(
                        "[TencentAPI] HTTP %d (batch %d/%d, attempt %d)",
                        resp.status_code, batch_idx + 1, total_batches, attempt + 1,
                    )
                    if attempt < _MAX_RETRIES:
                        time.sleep(1)
                    continue

                # 按行解析
                lines = resp.text.strip().split(";")
                batch_records = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    record = _parse_tencent_line(line)
                    if record:
                        batch_records.append(record)

                all_records.extend(batch_records)
                logger.debug(
                    "[TencentAPI] batch %d/%d: %d/%d 解析成功",
                    batch_idx + 1, total_batches,
                    len(batch_records), len(batch),
                )
                break  # 成功，跳出重试

            except requests.RequestException as exc:
                logger.warning(
                    "[TencentAPI] 请求失败 (batch %d/%d, attempt %d): %s",
                    batch_idx + 1, total_batches, attempt + 1, exc,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(1)

        # 批次间小间隔，避免被限流
        if batch_idx < total_batches - 1:
            time.sleep(0.3)

    if not all_records:
        logger.warning("[TencentAPI] 未获取到任何行情数据")
        return pd.DataFrame()

    df = pd.DataFrame(all_records)

    # 确保数值类型
    numeric_cols = ["最新价", "涨跌幅", "换手率", "量比", "流通市值", "成交额"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info(
        "[TencentAPI] 合计获取 %d 只股票行情 (请求 %d 只)",
        len(df), len(codes),
    )
    return df


# ======================================================================
# 3. 一步到位：替代 ak.stock_zh_a_spot_em()
# ======================================================================

def get_stock_universe() -> pd.DataFrame:
    """获取全 A 股实时行情 DataFrame。

    等价于 ``ak.stock_zh_a_spot_em()``，但使用腾讯财经 API。

    流程:
        1. 通过 akshare 获取所有代码（stock_info_sh/sz_name_code）
        2. 通过腾讯 API 批量查询行情
        3. 返回 DataFrame（列名兼容 akshare 格式）

    Returns:
        DataFrame with columns: 代码, 名称, 最新价, 涨跌幅, 换手率, 量比, 流通市值, 成交额
    """
    codes = get_all_stock_codes()
    if not codes:
        logger.error("[TencentAPI] 无法获取股票代码列表，返回空 DataFrame")
        return pd.DataFrame()

    logger.info("[TencentAPI] 开始批量查询 %d 只股票行情...", len(codes))
    df = fetch_realtime_quotes(codes)
    return df


# ======================================================================
# 快速测试
# ======================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 测试少量代码
    test_codes = ["600519", "000001", "300750", "000858", "601318"]
    print(f"\n=== 测试 fetch_realtime_quotes ({len(test_codes)} 只) ===")
    result = fetch_realtime_quotes(test_codes)
    if not result.empty:
        print(result.to_string(index=False))
        print(f"\n列: {list(result.columns)}")
        print(f"数据类型:\n{result.dtypes}")
    else:
        print("(无数据)")

    print("\n=== 测试 get_all_stock_codes ===")
    all_codes = get_all_stock_codes()
    print(f"获取到 {len(all_codes)} 只股票代码")
    if all_codes:
        print(f"前10: {all_codes[:10]}")
        print(f"后10: {all_codes[-10:]}")
