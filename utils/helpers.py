"""
工具函数
"""

import re
import json
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta


def sanitize_sql(sql: str) -> str:
    """
    清理 SQL 语句，防止注入

    Args:
        sql: 原始 SQL

    Returns:
        清理后的 SQL
    """
    # 只允许 SELECT 语句
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith('SELECT'):
        raise ValueError("只允许 SELECT 查询")

    # 移除危险字符
    dangerous = [';', '--', '/*', '*/', 'DROP', 'DELETE', 'INSERT', 'UPDATE']
    for d in dangerous:
        if d in sql_upper and d not in ['SELECT']:
            raise ValueError(f"检测到危险操作: {d}")

    return sql


def parse_date_range(text: str) -> tuple:
    """
    从文本解析日期范围

    Args:
        text: 包含日期描述的文本

    Returns:
        (开始日期, 结束日期) 的 ISO 格式字符串元组
    """
    today = datetime.now()

    if '昨天' in text:
        end = today - timedelta(days=1)
        start = end
    elif '今天' in text or '今日' in text:
        end = today
        start = end
    elif '本周' in text or '最近7天' in text:
        end = today
        start = today - timedelta(days=7)
    elif '上周' in text:
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
    elif '本月' in text:
        end = today
        start = today.replace(day=1)
    elif '上月' in text:
        first_day = today.replace(day=1)
        end = first_day - timedelta(days=1)
        start = end.replace(day=1)
    else:
        # 默认最近7天
        end = today
        start = today - timedelta(days=7)

    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


def extract_line_numbers(text: str) -> List[str]:
    """
    从文本提取线路号

    Args:
        text: 用户查询文本

    Returns:
        线路号列表
    """
    # 匹配模式：101路、101线路、线路101、LINENO 101 等
    patterns = [
        r'(\d+)[路线路]',
        r'[路线路](\d+)',
        r'LINENO\s*(\d+)',
        r'LINE\s*(\d+)',
    ]

    lines = set()
    for pattern in patterns:
        matches = re.findall(pattern, text.upper())
        lines.update(matches)

    return list(lines)


def format_number(num: float, precision: int = 2) -> str:
    """
    格式化数字显示

    Args:
        num: 数字
        precision: 小数精度

    Returns:
        格式化后的字符串
    """
    if num is None:
        return "N/A"

    if abs(num) >= 100000000:
        return f"{num/100000000:.{precision}f}亿"
    elif abs(num) >= 10000:
        return f"{num/10000:.{precision}f}万"
    else:
        return f"{num:.{precision}f}"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    截断文本

    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 后缀

    Returns:
        截断后的文本
    """
    if not text or len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def safe_json_loads(text: str, default: Any = None) -> Any:
    """
    安全地解析 JSON

    Args:
        text: JSON 字符串
        default: 解析失败时的默认值

    Returns:
        解析结果或默认值
    """
    if not text:
        return default

    try:
        # 尝试直接解析
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 部分
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass

    try:
        start = text.find('[')
        end = text.rfind(']') + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass

    return default


def calculate_growth_rate(current: float, previous: float) -> float:
    """
    计算增长率

    Args:
        current: 当前值
        previous: 上期值

    Returns:
        增长率百分比
    """
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round((current - previous) / previous * 100, 2)


def merge_dicts(base: Dict, update: Dict) -> Dict:
    """
    递归合并字典

    Args:
        base: 基础字典
        update: 更新字典

    Returns:
        合并后的字典
    """
    result = base.copy()

    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value

    return result


def generate_id() -> str:
    """
    生成唯一 ID

    Returns:
        唯一标识符
    """
    import uuid
    return str(uuid.uuid4())


def chunk_list(items: List, chunk_size: int) -> List[List]:
    """
    将列表分块

    Args:
        items: 原始列表
        chunk_size: 块大小

    Returns:
        分块后的列表
    """
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
