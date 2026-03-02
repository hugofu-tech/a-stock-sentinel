# A股情绪晨间预警 - Akshare API 技术文档

> 本文档整理了用于"情绪晨间预警"系统的 Akshare 库关键 API
> 
> **Akshare 版本**: 1.18.21
> 
> **数据来源**: 东方财富网

---

## 目录

1. [市场概况 - 指数行情](#1-市场概况---指数行情)
2. [涨跌统计](#2-涨跌统计)
3. [资金流向](#3-资金流向)
4. [板块热度](#4-板块热度)
5. [情绪指标](#5-情绪指标)
6. [调用示例](#6-调用示例)

---

## 1. 市场概况 - 指数行情

### 1.1 指数实时行情 `stock_zh_index_spot_em`

获取沪深京主要指数的实时行情数据。

**调用方式:**
```python
import akshare as ak

df = ak.stock_zh_index_spot_em(symbol="上证系列指数")
```

**参数说明:**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| symbol | str | "上证系列指数" | 指数类型 |

**symbol 可选值:**
- `"沪深重要指数"` - 沪深重要指数
- `"上证系列指数"` - 上证系列指数
- `"深证系列指数"` - 深证系列指数
- `"指数成份"` - 指数成份股
- `"中证系列指数"` - 中证系列指数

**返回字段:**
| 字段 | 说明 |
|------|------|
| 序号 | 序号 |
| 代码 | 指数代码 |
| 名称 | 指数名称 |
| 最新价 | 最新收盘价 |
| 涨跌幅 | 涨跌幅(%) |
| 涨跌额 | 涨跌额 |
| 成交量 | 成交量(手) |
| 成交额 | 成交额(元) |
| 振幅 | 振幅(%) |
| 最高 | 最高价 |
| 最低 | 最低价 |
| 今开 | 开盘价 |
| 昨收 | 昨收价 |
| 量比 | 量比 |

**注意事项:**
- 默认返回当天交易日的实时数据
- 非交易时段可能返回空或历史数据

---

### 1.2 获取上证/深证/创业板指特定指数

使用 `stock_zh_index_daily` 获取历史数据，最新数据可用于实时监控。

```python
# 获取上证指数历史数据（取最新一条即为当日）
df = ak.stock_zh_index_daily(symbol="sh000001")

# 获取深证成指
df = ak.stock_zh_index_daily(symbol="sz399001")

# 获取创业板指
df = ak.stock_zh_index_daily(symbol="sz399006")
```

**symbol 参数说明:**
| symbol | 指数 |
|--------|------|
| sh000001 | 上证指数 |
| sz399001 | 深证成指 |
| sz399006 | 创业板指 |

---

## 2. 涨跌统计

### 2.1 涨停股池 `stock_zt_pool_em`

获取当日涨停股票池数据。

**调用方式:**
```python
import akshare as ak
from datetime import datetime

# 获取当日涨停股池（默认最新交易日）
date_str = datetime.now().strftime("%Y%m%d")
df = ak.stock_zt_pool_em(date=date_str)
```

**参数说明:**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| date | str | "20241008" | 交易日，格式YYYYMMDD |

**返回字段:**
| 字段 | 说明 |
|------|------|
| 序号 | 序号 |
| 代码 | 股票代码 |
| 名称 | 股票名称 |
| 涨跌幅 | 涨跌幅(%) |
| 最新价 | 最新价 |
| 成交额 | 成交额(元) |
| 流通市值 | 流通市值(元) |
| 总市值 | 总市值(元) |
| 换手率 | 换手率(%) |
| 封板资金 | 封板资金(元) |
| 首次封板时间 | 首次封板时间(HHMMSS) |
| 最后封板时间 | 最后封板时间(HHMMSS) |
| 炸板次数 | 炸板次数 |
| 涨停统计 | 涨停天数/总涨停天数 |
| 连板数 | 连续涨停板数 |
| 所属行业 | 所属行业 |

**注意事项:**
- 返回数据包含所有涨停股票（含未封住）
- 可通过 `len(df)` 获取涨停家数

---

### 2.2 跌停股池 `stock_zt_pool_dtgc_em`

获取当日跌停股票池数据。

**调用方式:**
```python
import akshare as ak

df = ak.stock_zt_pool_dtgc_em(date="20241011")
```

**返回字段:** 同涨停股池

**注意事项:**
- 可通过 `len(df)` 获取跌停家数

---

### 2.3 涨跌停池次日预期 `stock_zt_pool_previous_em`

获取涨跌停股池的次日预期数据。

```python
df = ak.stock_zt_pool_previous_em(date="20241011")
```

---

### 2.4 市场涨跌统计 `stock_a_high_low_statistics`

获取市场创新高、新低的股票数量统计。

**调用方式:**
```python
import akshare as ak

df = ak.stock_a_high_low_statistics(symbol="all")
```

**参数说明:**
| 参数 | 默认值 | 说明 |
|------|--------|------|
| symbol | "all" | 股票池选择 |

**symbol 可选值:**
| 值 | 说明 |
|----|------|
| "all" | 全部A股 |
| "sz50" | 上证50 |
| "hs300" | 沪深300 |
| "zz500" | 中证500 |

**返回字段:**
| 字段 | 说明 |
|------|------|
| date | 统计日期 |
| close | 收盘价 |
| high20 | 20日新高数量 |
| low20 | 20日新低数量 |
| high60 | 60日新高数量 |
| low60 | 60日新低数量 |
| high120 | 120日新高数量 |
| low120 | 120日新低数量 |

---

### 2.5 市场概况速览 `stock_zh_a_spot_em`

获取沪深A股全景数据，用于计算涨跌家数。

**调用方式:**
```python
import akshare as ak

df = ak.stock_zh_a_spot_em()

# 计算涨跌家数
up_count = len(df[df['涨跌幅'] > 0])
down_count = len(df[df['涨跌幅'] < 0])
flat_count = len(df[df['涨跌幅'] == 0])
```

**返回字段:**
| 字段 | 说明 |
|------|------|
| 序号 | 序号 |
| 代码 | 股票代码 |
| 名称 | 股票名称 |
| 最新价 | 最新价 |
| 涨跌幅 | 涨跌幅(%) |
| 涨跌额 | 涨跌额 |
| 成交量 | 成交量 |
| 成交额 | 成交额 |
| 振幅 | 振幅(%) |
| 最高 | 最高价 |
| 最低 | 最低价 |
| 今开 | 开盘价 |
| 昨收 | 昨收价 |
| 量比 | 量比 |
| 换手率 | 换手率(%) |
| 市盈率-动态 | 市盈率-动态 |
| 市净率 | 市净率 |
| 总市值 | 总市值(元) |
| 流通市值 | 流通市值(元) |

---

## 3. 资金流向

### 3.1 沪深港通历史资金 `stock_hsgt_hist_em`

获取北向资金（沪股通+深股通）的历史流向数据。

**调用方式:**
```python
import akshare as ak

# 获取北向资金历史数据
df = ak.stock_hsgt_hist_em(symbol="北向资金")

# 获取最新一条数据
latest = df.iloc[-1]
```

**参数说明:**
| 参数 | 默认值 | 说明 |
|------|--------|------|
| symbol | "北向资金" | 资金类型 |

**symbol 可选值:**
| 值 | 说明 |
|----|------|
| "北向资金" | 沪股通+深股通 |
| "沪股通" | 沪股通 |
| "深股通" | 深股通 |
| "南向资金" | 港股通 |
| "港股通沪" | 港股通(沪) |
| "港股通深" | 港股通(深) |

**返回字段:**
| 字段 | 说明 |
|------|------|
| 日期 | 交易日期 |
| 当日成交净买额 | 当日成交净买额(亿元) |
| 买入成交额 | 买入成交额(亿元) |
| 卖出成交额 | 卖出成交额(亿元) |
| 历史累计净买额 | 历史累计净买额(亿元/万亿元) |
| 当日资金流入 | 当日资金流入(亿元) |
| 当日余额 | 当日余额(亿元) |
| 持股市值 | 持股市值(亿元) |
| 领涨股 | 领涨股名称 |
| 领涨股-涨跌幅 | 领涨股涨跌幅(%) |
| 沪深300 | 沪深300指数收盘价 |
| 沪深300-涨跌幅 | 沪深300涨跌幅(%) |

**注意事项:**
- 数据单位已转换为亿元
- 负值表示净流出

---

### 3.2 主力资金流向 `stock_main_fund_flow`

获取当日主力资金净流入排名。

**调用方式:**
```python
import akshare as ak

# 获取全部股票主力资金流向
df = ak.stock_main_fund_flow(symbol="全部股票")

# 获取沪深A股
df = ak.stock_main_fund_flow(symbol="沪深A股")

# 获取创业板
df = ak.stock_main_fund_flow(symbol="创业板")
```

**参数说明:**
| 参数 | 默认值 | 说明 |
|------|--------|------|
| symbol | "全部股票" | 股票池 |

**symbol 可选值:**
| 值 | 说明 |
|----|------|
| "全部股票" | 全部股票 |
| "沪深A股" | 沪深A股 |
| "沪市A股" | 沪市A股 |
| "科创板" | 科创板 |
| "深市A股" | 深市A股 |
| "创业板" | 创业板 |
| "沪市B股" | 沪市B股 |
| "深市B股" | 深市B股 |

**返回字段:**
| 字段 | 说明 |
|------|------|
| 序号 | 序号 |
| 代码 | 股票代码 |
| 名称 | 股票名称 |
| 最新价 | 最新价 |
| 今日排行榜-主力净占比 | 主力净占比(%) |
| 今日排行榜-今日排名 | 今日排名 |
| 今日排行榜-今日涨跌 | 今日涨跌(%) |
| 5日排行榜-主力净占比 | 5日主力净占比(%) |
| 5日排行榜-5日排名 | 5日排名 |
| 5日排行榜-5日涨跌 | 5日涨跌(%) |
| 10日排行榜-主力净占比 | 10日主力净占比(%) |
| 10日排行榜-10日排名 | 10日排名 |
| 10日排行榜-10日涨跌 | 10日涨跌(%) |
| 所属板块 | 所属板块 |

---

### 3.3 大盘资金流向 `stock_market_fund_flow`

获取上证和深证的整体资金流向数据。

**调用方式:**
```python
import akshare as ak

df = ak.stock_market_fund_flow()

# 取最新数据
latest = df.iloc[-1]
print(f"主力净流入: {latest['主力净流入-净额']}")
print(f"主力净占比: {latest['主力净流入-净占比']}")
```

**返回字段:**
| 字段 | 说明 |
|------|------|
| 日期 | 交易日期 |
| 上证-收盘价 | 上证指数收盘价 |
| 上证-涨跌幅 | 上证指数涨跌幅(%) |
| 深证-收盘价 | 深证成指收盘价 |
| 深证-涨跌幅 | 深证成指涨跌幅(%) |
| 主力净流入-净额 | 主力净流入(万元) |
| 主力净流入-净占比 | 主力净占比(%) |
| 超大单净流入-净额 | 超大单净流入(万元) |
| 超大单净流入-净占比 | 超大单净占比(%) |
| 大单净流入-净额 | 大单净流入(万元) |
| 大单净流入-净占比 | 大单净占比(%) |
| 中单净流入-净额 | 中单净流入(万元) |
| 中单净流入-净占比 | 中单净占比(%) |
| 小单净流入-净额 | 小单净流入(万元) |
| 小单净流入-净占比 | 小单净占比(%) |

**注意事项:**
- 数据包含最近一段时间的日线数据
- 单位为万元

---

### 3.4 板块资金流排名 `stock_sector_fund_flow_rank`

获取行业/概念/地域板块的资金流排名。

**调用方式:**
```python
import akshare as ak

# 今日行业资金流排名前10
df = ak.stock_sector_fund_flow_rank(
    indicator="今日", 
    sector_type="行业资金流"
)
top10 = df.head(10)

# 5日行业资金流排名
df_5d = ak.stock_sector_fund_flow_rank(
    indicator="5日", 
    sector_type="行业资金流"
)

# 概念资金流排名
df_concept = ak.stock_sector_fund_flow_rank(
    indicator="今日", 
    sector_type="概念资金流"
)
```

**参数说明:**
| 参数 | 默认值 | 说明 |
|------|--------|------|
| indicator | "今日" | 时间范围 |
| sector_type | "行业资金流" | 板块类型 |

**indicator 可选值:**
- `"今日"` - 当日数据
- `"5日"` - 近5日数据
- `"10日"` - 近10日数据

**sector_type 可选值:**
- `"行业资金流"` - 行业板块
- `"概念资金流"` - 概念板块
- `"地域资金流"` - 地域板块

**返回字段 (indicator="今日" 时):**
| 字段 | 说明 |
|------|------|
| 名称 | 板块名称 |
| 今日涨跌幅 | 板块涨跌幅(%) |
| 今日主力净流入-净额 | 主力净流入(万元) |
| 今日主力净流入-净占比 | 主力净占比(%) |
| 今日超大单净流入-净额 | 超大单净流入(万元) |
| 今日超大单净流入-净占比 | 超大单净占比(%) |
| 今日大单净流入-净额 | 大单净流入(万元) |
| 今日大单净流入-净占比 | 大单净占比(%) |
| 今日中单净流入-净额 | 中单净流入(万元) |
| 今日中单净流入-净占比 | 中单净占比(%) |
| 今日小单净流入-净额 | 小单净流入(万元) |
| 今日小单净流入-净占比 | 小单净占比(%) |
| 今日主力净流入最大股 | 主力净流入最大股 |
| 今日主力净流入最大股代码 | 主力净流入最大股代码 |
| 是否净流入 | 是否净流入 |

---

## 4. 板块热度

### 4.1 行业板块实时行情 `stock_board_industry_spot_em`

获取行业板块的实时行情数据。

**调用方式:**
```python
import akshare as ak

# 获取小金属板块行情
df = ak.stock_board_industry_spot_em(symbol="小金属")

# 获取所有行业板块名称列表
industry_list = ak.stock_board_industry_name_em()
```

**返回字段:**
| 字段 | 说明 |
|------|------|
| 最新 | 最新价 |
| 最高 | 最高价 |
| 最低 | 最低价 |
| 开盘 | 开盘价 |
| 成交量 | 成交量(手) |
| 成交额 | 成交额(元) |
| 涨跌幅 | 涨跌幅(%) |
| 振幅 | 振幅(%) |
| 换手率 | 换手率(%) |
| 涨跌额 | 涨跌额 |

---

### 4.2 行业板块名称列表 `stock_board_industry_name_em`

获取所有行业板块名称和代码。

**调用方式:**
```python
import akshare as ak

df = ak.stock_board_industry_name_em()
print(df.head(20))
```

**返回字段:**
| 字段 | 说明 |
|------|------|
| 板块代码 | 板块代码 |
| 板块名称 | 板块名称 |

---

### 4.3 板块异动详情 `stock_board_change_em`

获取当日板块异动详情，包括涨幅居前和跌幅居前的板块。

**调用方式:**
```python
import akshare as ak

df = ak.stock_board_change_em()

# 涨幅前10
up = df.nlargest(10, '涨跌幅')

# 跌幅前10
down = df.nsmallest(10, '涨跌幅')
```

**返回字段:**
| 字段 | 说明 |
|------|------|
| 板块名称 | 板块名称 |
| 涨跌幅 | 涨跌幅(%) |
| 主力净流入 | 主力净流入(万元) |
| 板块异动总次数 | 板块异动次数 |
| 板块异动最频繁个股及所属类型-股票代码 | 异动股代码 |
| 板块异动最频繁个股及所属类型-股票名称 | 异动股名称 |
| 板块异动最频繁个股及所属类型-买卖方向 | 买卖方向 |

---

### 4.4 概念板块实时行情 `stock_board_concept_spot_em`

获取概念板块的实时行情。

```python
import akshare as ak

# 概念板块实时行情
df = ak.stock_board_concept_spot_em()

# 涨幅前10概念板块
top10 = df.nlargest(10, '涨跌幅')
```

---

## 5. 情绪指标

### 5.1 融资融券汇总 `stock_margin_sse`

获取上海证券交易所的融资融券汇总数据。

**调用方式:**
```python
import akshare as ak
from datetime import datetime, timedelta

# 获取近30日融资融券数据
end_date = datetime.now().strftime("%Y%m%d")
start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

df = ak.stock_margin_sse(start_date=start_date, end_date=end_date)

# 最新数据
latest = df.iloc[-1]
print(f"融资余额: {latest['融资余额']}")
print(f"融资融券余额: {latest['融资融券余额']}")
```

**参数说明:**
| 参数 | 默认值 | 说明 |
|------|--------|------|
| start_date | "20010106" | 开始日期，格式YYYYMMDD |
| end_date | 当前日期 | 结束日期，格式YYYYMMDD |

**返回字段:**
| 字段 | 说明 |
|------|------|
| 信用交易日期 | 交易日期 |
| 融资余额 | 融资余额(元) |
| 融资买入额 | 融资买入额(元) |
| 融券余量 | 融券余量(股) |
| 融券余量金额 | 融券余量金额(元) |
| 融券卖出量 | 融券卖出量(股) |
| 融资融券余额 | 融资融券余额(元) |

**注意事项:**
- 数据来源为上海证券交易所
- 深圳融资融券数据使用 `stock_margin_szse`

---

### 5.2 融资融券汇总(深市) `stock_margin_szse`

获取深圳证券交易所的融资融券数据。

```python
import akshare as ak

df = ak.stock_margin_szse(start_date="20240101", end_date="20241011")
```

---

### 5.3 股票账户统计 `stock_account_statistics_em`

获取新增投资者数量、期末投资者账户数等数据。

**调用方式:**
```python
import akshare as ak

df = ak.stock_account_statistics_em()

# 最新数据
latest = df.iloc[-1]
print(f"新增投资者: {latest['新增投资者-数量']}")
print(f"期末投资者总量: {latest['期末投资者-总量']}")
```

**返回字段:**
| 字段 | 说明 |
|------|------|
| 数据日期 | 统计日期 |
| 新增投资者-数量 | 新增投资者数量(人) |
| 新增投资者-环比 | 新增投资者环比(%) |
| 新增投资者-同比 | 新增投资者同比(%) |
| 期末投资者-总量 | 期末投资者总量(户) |
| 期末投资者-A股账户 | A股账户数(户) |
| 期末投资者-B股账户 | B股账户数(户) |
| 沪深总市值 | 沪深总市值(元) |
| 沪深户均市值 | 户均市值(元) |
| 上证指数-收盘 | 上证指数收盘价 |
| 上证指数-涨跌幅 | 上证指数涨跌幅(%) |

---

### 5.4 市场整体换手率

通过 `stock_zh_a_spot_em` 计算市场整体换手率。

```python
import akshare as ak

df = ak.stock_zh_a_spot_em()

# 加权平均换手率
avg_turnover = (df['换手率'] * df['流通市值']).sum() / df['流通市值'].sum()
print(f"市场加权换手率: {avg_turnover:.2f}%")

# 中位数换手率
median_turnover = df['换手率'].median()
print(f"换手率中位数: {median_turnover:.2f}%")
```

---

## 6. 调用示例

### 6.1 晨间预警数据采集脚本

```python
#!/usr/bin/env python3
"""
A股情绪晨间预警 - 数据采集脚本
"""
import akshare as ak
import pandas as pd
from datetime import datetime

def get_market_sentiment():
    """采集市场情绪指标"""
    result = {}
    today = datetime.now().strftime("%Y%m%d")
    
    # 1. 市场概况 - 指数行情
    print("📊 获取指数行情...")
    index_df = ak.stock_zh_index_spot_em(symbol="沪深重要指数")
    # 筛选主要指数
    major_indices = ['上证指数', '深证成指', '创业板指', '科创50', '北证50']
    for idx in major_indices:
        row = index_df[index_df['名称'] == idx]
        if not row.empty:
            result[idx] = {
                '最新价': row['最新价'].values[0],
                '涨跌幅': row['涨跌幅'].values[0]
            }
    
    # 2. 涨跌统计
    print("📈 获取涨跌统计...")
    # 涨停数
    zt_df = ak.stock_zt_pool_em(date=today)
    result['涨停数'] = len(zt_df)
    
    # 跌停数
    dt_df = ak.stock_zt_pool_dtgc_em(date=today)
    result['跌停数'] = len(dt_df)
    
    # 涨跌家数
    a_spot = ak.stock_zh_a_spot_em()
    result['上涨家数'] = len(a_spot[a_spot['涨跌幅'] > 0])
    result['下跌家数'] = len(a_spot[a_spot['涨跌幅'] < 0])
    result['平盘家数'] = len(a_spot[a_spot['涨跌幅'] == 0])
    
    # 3. 资金流向
    print("💰 获取资金流向...")
    # 北向资金
    hsgt_df = ak.stock_hsgt_hist_em(symbol="北向资金")
    latest_hsgt = hsgt_df.iloc[-1]
    result['北向资金'] = {
        '当日净买额': latest_hsgt['当日成交净买额'],
        '持股市值': latest_hsgt['持股市值']
    }
    
    # 主力资金
    fund_flow = ak.stock_market_fund_flow()
    latest_fund = fund_flow.iloc[-1]
    result['主力资金'] = {
        '净流入': latest_fund['主力净流入-净额'],
        '净占比': latest_fund['主力净流入-净占比']
    }
    
    # 4. 板块热度
    print("🔥 获取板块热度...")
    # 行业资金流
    sector_df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
    result['资金流入前10板块'] = sector_df.head(10)[['名称', '今日主力净流入-净额']].to_dict('records')
    
    # 5. 情绪指标
    print("🎯 获取情绪指标...")
    # 融资融券
    margin_df = ak.stock_margin_sse(start_date="20240101", end_date=today)
    latest_margin = margin_df.iloc[-1]
    result['两融余额'] = latest_margin['融资融券余额']
    result['融资余额'] = latest_margin['融资余额']
    
    return result

if __name__ == "__main__":
    data = get_market_sentiment()
    print("\n=== 情绪晨间预警数据 ===")
    for k, v in data.items():
        print(f"{k}: {v}")
```

---

### 6.2 注意事项

1. **数据时效性**: 大部分API返回的是交易日当天或历史数据，非交易时段可能获取不到当日数据

2. **API限流**: 东方财富网对API调用有频率限制，批量采集时注意添加延时:
   ```python
   import time
   time.sleep(1)  # 每次请求间隔1秒
   ```

3. **网络问题**: 如果遇到网络错误，建议添加重试机制:
   ```python
   from functools import wraps
   
   def retry(max_retries=3):
       def decorator(func):
           @wraps(func)
           def wrapper(*args, **kwargs):
               for i in range(max_retries):
                   try:
                       return func(*args, **kwargs)
                   except Exception as e:
                       if i == max_retries - 1:
                           raise e
                       time.sleep(2)
           return wrapper
       return decorator
   ```

4. **数据清洗**: 返回的数据可能包含空值或异常值，建议进行清洗:
   ```python
   df = df.dropna()  # 删除空值
   df = df[df['涨跌幅'] != '-']  # 过滤无效数据
   ```

5. **交易日判断**: 可使用 `pandas.bdate_range` 或 `akshare` 其他工具判断是否为交易日

---

## 附录: API速查表

| 需求 | API | 关键字段 |
|------|-----|----------|
| 上证指数行情 | `stock_zh_index_daily(symbol="sh000001")` | close, change_pct |
| 深证成指行情 | `stock_zh_index_daily(symbol="sz399001")` | close, change_pct |
| 创业板指行情 | `stock_zh_index_daily(symbol="sz399006")` | close, change_pct |
| 涨停数 | `stock_zt_pool_em(date=today)` | len(df) |
| 跌停数 | `stock_zt_pool_dtgc_em(date=today)` | len(df) |
| 上涨/下跌家数 | `stock_zh_a_spot_em()` | 涨跌幅 |
| 北向资金 | `stock_hsgt_hist_em(symbol="北向资金")` | 当日成交净买额 |
| 主力资金 | `stock_market_fund_flow()` | 主力净流入-净额 |
| 行业资金流 | `stock_sector_fund_flow_rank(indicator="今日")` | 名称, 今日主力净流入-净额 |
| 融资融券 | `stock_margin_sse()` | 融资余额, 融资融券余额 |
| 投资者数量 | `stock_account_statistics_em()` | 新增投资者-数量 |
