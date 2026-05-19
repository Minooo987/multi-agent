"""
Agent Teams 主入口
LangChain + LangGraph 后端服务启动
"""

import asyncio
import argparse
import sys

import uvicorn

from api.server import app
from tools.mcp_oracle import oracle_mcp
from config.settings import settings
from agents.base import MEMORY_AVAILABLE


# Import tracing system status
try:
    from monitoring.tracing import tracer, LANGSMITH_AVAILABLE
    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False
    LANGSMITH_AVAILABLE = False


async def test_oracle_connection():
    """测试 Oracle 数据库连接"""
    print("=" * 50)
    print("测试 Oracle 数据库连接...")
    print(f"主机: {settings.oracle_host}:{settings.oracle_port}")
    print(f"服务名: {settings.oracle_service_name}")
    print(f"用户: {settings.oracle_user}")

    try:
        result = await oracle_mcp.test_connection()

        if result.get('success'):
            print("\n[OK] 数据库连接成功!")
            print(f"版本: {result.get('database_version', 'Unknown')}")
            print(f"当前时间: {result.get('current_time')}")
            return True
        else:
            print(f"\n[FAIL] 连接失败: {result.get('error')}")
            return False

    except Exception as e:
        print(f"\n[ERROR] 连接异常: {e}")
        return False


async def test_agents():
    """测试 Agent 初始化"""
    print("=" * 50)
    print("测试 Agent 初始化...")

    try:
        from agents.task_manager import TaskManagerAgent
        from agents.passenger_processor import PassengerProcessorAgent
        from agents.operation_scheduler import OperationSchedulerAgent

        # 初始化 Agents
        task_manager = TaskManagerAgent()
        passenger_processor = PassengerProcessorAgent()
        operation_scheduler = OperationSchedulerAgent()

        print("\n[OK] Task Manager 初始化成功")
        print(f"   - 角色: {task_manager.role.value}")
        print(f"   - 可通信: {task_manager.can_talk_to}")
        print(f"   - 记忆增强: {'启用' if MEMORY_AVAILABLE else '禁用'}")
        print(f"   - 追踪监控: {'启用' if TRACING_AVAILABLE else '禁用'}")

        print("\n[OK] Passenger Processor 初始化成功")
        print(f"   - 角色: {passenger_processor.role.value}")
        print(f"   - MCP 工具: {'启用' if passenger_processor.use_mcp else '禁用'}")
        print(f"   - SQL自动修正: 已启用")
        print(f"   - 记忆增强: {'启用' if MEMORY_AVAILABLE else '禁用'}")
        print(f"   - 追踪监控: {'启用' if TRACING_AVAILABLE else '禁用'}")

        print("\n[OK] Operation Scheduler 初始化成功")
        print(f"   - 角色: {operation_scheduler.role.value}")
        print(f"   - MCP 工具: {'启用' if operation_scheduler.use_mcp else '禁用'}")
        print(f"   - SQL自动修正: 已启用")
        print(f"   - 记忆增强: {'启用' if MEMORY_AVAILABLE else '禁用'}")
        print(f"   - 追踪监控: {'启用' if TRACING_AVAILABLE else '禁用'}")

        # 清理
        task_manager.cleanup()
        passenger_processor.cleanup()
        operation_scheduler.cleanup()

        return True

    except Exception as e:
        print(f"\n[ERROR] Agent 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_tests():
    """运行测试"""
    print("\n" + "=" * 50)
    print("Agent Teams 测试")
    print("=" * 50 + "\n")

    results = []

    # 测试数据库连接
    db_ok = await test_oracle_connection()
    results.append(("Oracle 连接", db_ok))

    print()

    # 测试 Agent
    agents_ok = await test_agents()
    results.append(("Agent 初始化", agents_ok))

    print()

    # 测试 Message Bus
    print("=" * 50)
    print("测试 Message Bus...")
    try:
        from tools.message_bus import message_bus
        print("\n[OK] Message Bus 初始化成功")
        results.append(("Message Bus", True))
    except Exception as e:
        print(f"\n[FAIL] Message Bus 失败: {e}")
        results.append(("Message Bus", False))

    print()

    # 测试 LangGraph
    print("=" * 50)
    print("测试 LangGraph...")
    try:
        from graph.team_graph import team_graph
        print("\n[OK] LangGraph 初始化成功")
        print(f"   - 节点数: 8+")
        print(f"   - 支持人工中断: 是")
        results.append(("LangGraph", True))
    except Exception as e:
        print(f"\n[FAIL] LangGraph 失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("LangGraph", False))

    # 汇总结果
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    for name, ok in results:
        status = "[PASS]" if ok else "[FAIL]"
        print(f"{name}: {status}")

    all_passed = all(ok for _, ok in results)
    if all_passed:
        print("\n[OK] 所有测试通过！")
    else:
        print("\n[WARN] 部分测试失败，请检查配置")

    return all_passed


async def run_demo():
    """运行演示"""
    print("\n" + "=" * 50)
    print("Agent Teams 演示")
    print("=" * 50 + "\n")

    from graph.team_graph import team_graph

    # 演示查询
    queries = [
        "分析昨天各线路的客流情况",
        "计算101线路的班次间隔和车辆利用率",
        "统计本周收入最高的5条线路",
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n{'='*50}")
        print(f"演示 {i}/{len(queries)}: {query}")
        print('='*50)

        try:
            result = await team_graph.run(query)

            print(f"\n状态: {result.get('status')}")
            print(f"报告:\n{result.get('final_report', '无报告')[:500]}...")

        except Exception as e:
            print(f"错误: {e}")

        await asyncio.sleep(1)

    print("\n演示完成!")


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description="Agent Teams 服务")
    parser.add_argument(
        "command",
        choices=["serve", "test", "demo"],
        default="serve",
        nargs="?",
        help="命令: serve (启动服务), test (运行测试), demo (运行演示)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="服务主机")
    parser.add_argument("--port", type=int, default=8000, help="服务端口")
    parser.add_argument("--reload", action="store_true", help="启用热重载")

    args = parser.parse_args()

    if args.command == "test":
        # 运行测试
        success = asyncio.run(run_tests())
        sys.exit(0 if success else 1)

    elif args.command == "demo":
        # 运行演示
        asyncio.run(run_demo())

    else:
        # 启动服务
        print(f"\n{'='*50}")
        print("启动 Agent Teams API 服务")
        print(f"{'='*50}\n")
        print(f"模式: LLM 驱动 + SQL 自动修正")
        print(f"记忆增强: {'已启用' if MEMORY_AVAILABLE else '未启用'}")
        print(f"追踪监控: {'已启用 (LangSmith)' if TRACING_AVAILABLE and LANGSMITH_AVAILABLE else '本地模式' if TRACING_AVAILABLE else '未启用'}")
        print()
        print(f"API 文档: http://{args.host}:{args.port}/docs")
        print(f"健康检查: http://{args.host}:{args.port}/health")
        print(f"WebSocket: ws://{args.host}:{args.port}/ws/{{client_id}}")
        print()

        uvicorn.run(
            "api.server:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info"
        )


if __name__ == "__main__":
    main()
