"""
TDD 测试：路由逻辑修复
Bug: "每个司机接单的订单情况" 同时包含 "司机" 和 "订单"，
     被路由到 PassengerProcessorAgent（查里程表）和 OperationSchedulerAgent（查订单表）。
     PassengerProcessor 没有订单数据，返回错误结果。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def match_analysis_type_CURRENT(query: str) -> tuple:
    """team_graph.py 中的路由逻辑 — 修复后"""
    dynamic_keywords = ['动态', 'DY_ORDER', '预约', '订单', '动态公交']
    is_dynamic = any(kw in query for kw in dynamic_keywords)

    if is_dynamic:
        explicit_mileage_keywords = ['里程', 'mileage', '工作时长', '行驶', '空驶', '载客里程']
        order_keywords = ['订单', 'order', '乘客数', '完成率', '取消', '预约', '客流', '人数', '客运', '接单', '派单']
        has_explicit_mileage = any(kw in query for kw in explicit_mileage_keywords)
        has_order = any(kw in query for kw in order_keywords)
        has_driver = '司机' in query
        if has_driver and has_explicit_mileage and not has_order:
            return True, False
        if has_explicit_mileage and not has_order:
            return True, False
        if has_order and not has_explicit_mileage:
            return False, True
        if has_explicit_mileage and has_order:
            return True, True
        return True, True

    passenger_keywords = ['刷卡', '上车', '下车', '里程', '行驶', '运营时长', '载客里程', '空驶']
    operation_keywords = ['营运', '班次', '车辆', '调度', '运营', '效率', '订单', '客流', '乘客', '人数', '完成率', '取消', '站点', '车站', '上车站点', '下车站点']
    has_passenger = any(kw in query for kw in passenger_keywords)
    has_operation = any(kw in query for kw in operation_keywords)
    if has_passenger and '里程' in query:
        return True, False
    if has_operation and any(kw in query for kw in ['客流', '订单', '站点', '车站', '取消', '完成率']):
        return False, True
    if not has_passenger and not has_operation:
        return True, True
    return has_passenger, has_operation


# ============================================================
# RED tests — 断言正确行为
# ============================================================

def test_order_query_with_driver_should_only_route_to_operation():
    """"每个司机接单的订单情况" 应只路由到 OperationScheduler"""
    query = "2026年3月10日-2026年3月15日期间，每个司机接单的订单情况"
    needs_p, needs_o = match_analysis_type_CURRENT(query)
    assert needs_p is False, f"订单查询不应路由到 PassengerProcessor: passenger={needs_p}"
    assert needs_o is True, f"订单查询应路由到 OperationScheduler: operation={needs_o}"


def test_driver_order_count_should_only_route_to_operation():
    """"每个司机的订单数量" 应只路由到 OperationScheduler"""
    query = "每个司机的订单数量"
    needs_p, needs_o = match_analysis_type_CURRENT(query)
    assert needs_p is False, f"订单查询不应路由到 PassengerProcessor: passenger={needs_p}"
    assert needs_o is True, f"订单查询应路由到 OperationScheduler: operation={needs_o}"


def test_driver_mileage_should_only_route_to_passenger():
    """"每个司机的行驶里程" 应只路由到 PassengerProcessor"""
    query = "每个司机的行驶里程"
    needs_p, needs_o = match_analysis_type_CURRENT(query)
    assert needs_p is True, f"里程查询应路由到 PassengerProcessor: passenger={needs_p}"
    assert needs_o is False, f"里程查询不应路由到 OperationScheduler: operation={needs_o}"


def test_order_overview_should_only_route_to_operation():
    """"订单概览统计" 应只路由到 OperationScheduler"""
    query = "订单概览统计"
    needs_p, needs_o = match_analysis_type_CURRENT(query)
    assert needs_p is False, f"订单查询不应路由到 PassengerProcessor: passenger={needs_p}"
    assert needs_o is True, f"订单查询应路由到 OperationScheduler: operation={needs_o}"


def test_driver_mileage_and_order_routes_to_both():
    """"每个司机的里程和订单" 同时涉及里程和订单，应路由到两个 Agent"""
    query = "每个司机的里程和订单情况"
    needs_p, needs_o = match_analysis_type_CURRENT(query)
    assert needs_p is True, f"含里程应路由到 PassengerProcessor: passenger={needs_p}"
    assert needs_o is True, f"含订单应路由到 OperationScheduler: operation={needs_o}"


if __name__ == "__main__":
    tests = [
        test_order_query_with_driver_should_only_route_to_operation,
        test_driver_order_count_should_only_route_to_operation,
        test_driver_mileage_should_only_route_to_passenger,
        test_order_overview_should_only_route_to_operation,
        test_driver_mileage_and_order_routes_to_both,
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
        print("RED confirmed - now fix the routing logic!")
