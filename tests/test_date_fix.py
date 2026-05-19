"""
TDD 测试：日期范围解析修复
Bug: "2026年3月10日-2026年3月15日" 格式无法被正则匹配，导致日期条件返回 "1=1"

RED phase: 这些测试断言正确行为，当前代码应该 FAIL
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from datetime import datetime, timedelta


def extract_date_condition_passenger(query: str) -> str:
    """PassengerProcessorAgent._extract_date_condition — 修复后逻辑"""
    # 格式1: 无年份
    pattern = r'(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
    match = re.search(pattern, query)
    if match:
        month1, day1, month2, day2 = match.groups()
        month2_val = (month2.rstrip('月') if month2 else None) or month1
        year = datetime.now().year
        start_dt = datetime(year, int(month1), int(day1))
        end_dt = datetime(year, int(month2_val), int(day2)) + timedelta(days=1)
        start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        return f"JS_DATE >= {start} AND JS_DATE < {end}"

    # 格式2: 单年份
    pattern2 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
    match2 = re.search(pattern2, query)
    if match2:
        year, month1, day1, month2, day2 = match2.groups()
        month2_val = (month2.rstrip('月') if month2 else None) or month1
        start_dt = datetime(int(year), int(month1), int(day1))
        end_dt = datetime(int(year), int(month2_val), int(day2)) + timedelta(days=1)
        start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        return f"JS_DATE >= {start} AND JS_DATE < {end}"

    # 格式3: 双年份
    pattern3 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{4})年(\d{1,2})月(\d{1,2})日'
    match3 = re.search(pattern3, query)
    if match3:
        y1, m1, d1, y2, m2, d2 = match3.groups()
        start_dt = datetime(int(y1), int(m1), int(d1))
        end_dt = datetime(int(y2), int(m2), int(d2)) + timedelta(days=1)
        start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        return f"JS_DATE >= {start} AND JS_DATE < {end}"

    return "1=1"


def extract_date_condition_operation(query: str) -> str:
    """OperationSchedulerAgent._extract_date_condition — 修复后逻辑"""
    pattern = r'(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
    match = re.search(pattern, query)
    if match:
        month1, day1, month2, day2 = match.groups()
        month2_val = (month2.rstrip('月') if month2 else None) or month1
        year = datetime.now().year
        start_dt = datetime(year, int(month1), int(day1))
        end_dt = datetime(year, int(month2_val), int(day2)) + timedelta(days=1)
        start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        return f"CREATE_DATE >= {start} AND CREATE_DATE < {end}"

    pattern2 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
    match2 = re.search(pattern2, query)
    if match2:
        year, month1, day1, month2, day2 = match2.groups()
        month2_val = (month2.rstrip('月') if month2 else None) or month1
        start_dt = datetime(int(year), int(month1), int(day1))
        end_dt = datetime(int(year), int(month2_val), int(day2)) + timedelta(days=1)
        start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        return f"CREATE_DATE >= {start} AND CREATE_DATE < {end}"

    pattern3 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{4})年(\d{1,2})月(\d{1,2})日'
    match3 = re.search(pattern3, query)
    if match3:
        y1, m1, d1, y2, m2, d2 = match3.groups()
        start_dt = datetime(int(y1), int(m1), int(d1))
        end_dt = datetime(int(y2), int(m2), int(d2)) + timedelta(days=1)
        start = f"TO_DATE('{start_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        end = f"TO_DATE('{end_dt.strftime('%Y-%m-%d')}', 'YYYY-MM-DD')"
        return f"CREATE_DATE >= {start} AND CREATE_DATE < {end}"

    return "1=1"


def extract_date_range_intent_parser(query: str):
    """IntentParser._extract_date_range — 修复后逻辑"""
    # 格式1: 无年份
    pattern = r'(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
    match = re.search(pattern, query)
    if match:
        month1, day1, month2, day2 = match.groups()
        month2_val = (month2.rstrip('月') if month2 else None) or month1
        year = datetime.now().year
        end_date = datetime(year, int(month2_val), int(day2)) + timedelta(days=1)
        return {
            "start": f"{year}-{int(month1):02d}-{int(day1):02d}",
            "end": end_date.strftime("%Y-%m-%d")
        }

    # 格式2: 单年份
    pattern2 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{1,2}月)?(\d{1,2})日'
    match2 = re.search(pattern2, query)
    if match2:
        year, month1, day1, month2, day2 = match2.groups()
        month2_val = (month2.rstrip('月') if month2 else None) or month1
        end_date = datetime(int(year), int(month2_val), int(day2)) + timedelta(days=1)
        return {
            "start": f"{year}-{int(month1):02d}-{int(day1):02d}",
            "end": end_date.strftime("%Y-%m-%d")
        }

    # 格式3: 双年份
    pattern3 = r'(\d{4})年(\d{1,2})月(\d{1,2})日?[\-~到至](\d{4})年(\d{1,2})月(\d{1,2})日'
    match3 = re.search(pattern3, query)
    if match3:
        y1, m1, d1, y2, m2, d2 = match3.groups()
        end_date = datetime(int(y2), int(m2), int(d2)) + timedelta(days=1)
        return {
            "start": f"{y1}-{int(m1):02d}-{int(d1):02d}",
            "end": end_date.strftime("%Y-%m-%d")
        }

    return None


# ============================================================
# RED tests — 断言正确行为，当前代码应 FAIL
# ============================================================

def test_double_year_passenger():
    """双年份格式: PassengerProcessor 应提取正确日期"""
    query = "2026年3月10日-2026年3月15日期间，每个司机接单的订单情况"
    result = extract_date_condition_passenger(query)
    assert "2026-03-10" in result, f"缺少开始日期: {result}"
    assert "2026-03-16" in result, f"缺少结束日期(应+1天): {result}"
    assert "1=1" not in result, f"日期条件丢失，返回了 1=1: {result}"


def test_double_year_operation():
    """双年份格式: OperationScheduler 应提取正确日期"""
    query = "2026年3月10日-2026年3月15日期间，每个司机接单的订单情况"
    result = extract_date_condition_operation(query)
    assert "2026-03-10" in result, f"缺少开始日期: {result}"
    assert "2026-03-16" in result, f"缺少结束日期(应+1天): {result}"
    assert "1=1" not in result, f"日期条件丢失，返回了 1=1: {result}"


def test_double_year_intent_parser():
    """双年份格式: IntentParser 应提取正确日期范围"""
    query = "2026年3月10日-2026年3月15日期间的数据"
    result = extract_date_range_intent_parser(query)
    assert result is not None, f"返回了 None，日期未解析"
    assert result["start"] == "2026-03-10", f"开始日期错误: {result}"
    assert result["end"] == "2026-03-16", f"结束日期错误(应+1天): {result}"


def test_month_end_overflow():
    """月末日期不应产生无效日期（如 3月32日）"""
    query = "3月1日-3月31日"
    result = extract_date_condition_passenger(query)
    assert "03-32" not in result, f"产生无效日期 03-32: {result}"
    assert "04-01" in result, f"3月31日+1 应为4月1日: {result}"


def test_no_year_still_works():
    """无年份格式不受影响"""
    query = "3月10日-3月15日的数据"
    result = extract_date_condition_passenger(query)
    assert "1=1" not in result, f"无年份格式应匹配: {result}"


def test_single_year_still_works():
    """单年份格式不受影响"""
    query = "2026年3月10日-15日的数据"
    result = extract_date_condition_passenger(query)
    assert "1=1" not in result, f"单年份格式应匹配: {result}"
    assert "2026-03-10" in result


if __name__ == "__main__":
    tests = [
        test_double_year_passenger,
        test_double_year_operation,
        test_double_year_intent_parser,
        test_month_end_overflow,
        test_no_year_still_works,
        test_single_year_still_works,
    ]
    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS: {test_fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {test_fn.__name__} -> {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {test_fn.__name__} -> {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    if failed > 0:
        print("RED confirmed - now fix the source code!")
