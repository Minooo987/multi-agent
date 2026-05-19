"""
FastAPI + WebSocket 服务
提供 REST API 和实时通信接口
"""

import json
import asyncio
import uuid
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from graph.team_graph import team_graph
from graph.state import TaskStatus
from tools.mcp_oracle import oracle_mcp
from memory.conversation_store import conversation_store


# FastAPI 应用
app = FastAPI(
    title="Agent Teams API",
    description="LangChain + LangGraph Agent Teams 后端服务",
    version="1.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== 数据模型 ==============

class AnalysisRequest(BaseModel):
    """分析请求"""
    query: str = Field(..., description="用户查询")
    thread_id: Optional[str] = Field(None, description="会话ID（用于保持上下文）")
    require_human_review: bool = Field(False, description="是否需要人工审核")


class AnalysisResponse(BaseModel):
    """分析响应"""
    thread_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    requires_human_review: bool = False
    data_discovery: Optional[Dict[str, Any]] = None
    sql_used: Optional[str] = None
    analysis_details: Optional[Dict[str, Any]] = None


class HumanFeedbackRequest(BaseModel):
    """人工反馈请求"""
    thread_id: str = Field(..., description="会话ID")
    feedback: str = Field(..., description="反馈内容（'approve' 或修改建议）")


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    thread_id: str
    status: str
    current_step: Optional[str] = None
    tasks: Optional[list] = None
    error: Optional[str] = None


# ============== WebSocket 管理 ==============

class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_message(self, client_id: str, message: Dict[str, Any]):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections.values():
            await connection.send_json(message)


manager = ConnectionManager()


# ============== REST API ==============

@app.post("/api/v1/analyze", response_model=AnalysisResponse)
async def create_analysis(request: AnalysisRequest):
    """
    创建新的分析任务

    - 启动 Agent Teams 工作流
    - 返回 thread_id 用于跟踪进度
    """
    try:
        thread_id = request.thread_id or str(uuid.uuid4())

        # 启动异步分析任务
        result = await team_graph.run(request.query, thread_id)

        # 检查是否需要人工审核
        requires_review = result.get('requires_human_review', False)

        # 从结果中提取数据发现和SQL信息
        passenger_result = result.get('results', {}).get('passenger', {})
        operation_result = result.get('results', {}).get('operation', {})

        # 合并数据发现信息
        data_discovery = {}
        sql_statements = []

        if passenger_result and 'data_discovery' in passenger_result:
            data_discovery['passenger'] = passenger_result['data_discovery']
        if passenger_result and 'sql_used' in passenger_result:
            sql_statements.append(passenger_result['sql_used'])

        if operation_result and 'data_discovery' in operation_result:
            data_discovery['operation'] = operation_result['data_discovery']
        if operation_result and 'sql_used' in operation_result:
            sql_statements.append(operation_result['sql_used'])

        return AnalysisResponse(
            thread_id=thread_id,
            status=result.get('status', 'unknown'),
            result={
                "final_report": result.get('final_report'),
                "results": result.get('results'),
                "tasks": [
                    {
                        "task_id": t.id,
                        "task_type": t.type,
                        "status": t.status.value,
                        "error": t.error
                    }
                    for t in result.get('tasks', [])
                ]
            },
            error=result.get('error'),
            requires_human_review=requires_review,
            data_discovery=data_discovery,
            sql_used="; ".join(sql_statements) if sql_statements else None,
            analysis_details={
                "passenger": passenger_result.get('analysis') if isinstance(passenger_result, dict) else None,
                "operation": operation_result.get('analysis') if isinstance(operation_result, dict) else None
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/analyze/async")
async def create_analysis_async(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks
):
    """
    异步创建分析任务

    - 立即返回 thread_id
    - 在后台执行分析
    - 通过 WebSocket 或 /status 获取进度
    """
    thread_id = request.thread_id or str(uuid.uuid4())

    # 后台任务
    async def run_analysis():
        try:
            result = await team_graph.run(request.query, thread_id)
            # 广播完成消息
            await manager.broadcast({
                "type": "analysis_completed",
                "thread_id": thread_id,
                "status": result.get('status'),
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            await manager.broadcast({
                "type": "analysis_failed",
                "thread_id": thread_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

    background_tasks.add_task(run_analysis)

    return {
        "thread_id": thread_id,
        "status": "started",
        "message": "分析任务已启动，通过 WebSocket 或 /status 获取进度"
    }


@app.get("/api/v1/status/{thread_id}", response_model=TaskStatusResponse)
async def get_analysis_status(thread_id: str):
    """获取分析任务状态"""
    try:
        state = team_graph.get_state(thread_id)

        if not state:
            raise HTTPException(status_code=404, detail="任务不存在")

        return TaskStatusResponse(
            thread_id=thread_id,
            status=state.get('status', 'unknown'),
            current_step=state.get('current_step'),
            tasks=[
                {
                    "task_id": t.id,
                    "task_type": t.type,
                    "status": t.status.value,
                    "error": t.error
                }
                for t in state.get('tasks', [])
            ] if state.get('tasks') else None,
            error=state.get('error')
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/feedback")
async def submit_human_feedback(request: HumanFeedbackRequest):
    """
    提交人工反馈

    - 在工作流中断后恢复执行
    - feedback: 'approve' 或修改建议
    """
    try:
        result = team_graph.resume_after_interrupt(
            request.thread_id,
            request.feedback
        )

        return {
            "thread_id": request.thread_id,
            "status": result.get('status'),
            "result": result.get('final_report'),
            "error": result.get('error')
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/results/{thread_id}")
async def get_analysis_results(thread_id: str):
    """获取分析结果"""
    try:
        state = team_graph.get_state(thread_id)

        if not state:
            raise HTTPException(status_code=404, detail="任务不存在")

        return {
            "thread_id": thread_id,
            "status": state.get('status'),
            "final_report": state.get('final_report'),
            "results": state.get('results'),
            "completed_at": state.get('completed_at')
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== 数据库管理 API ==============

@app.get("/api/v1/db/status")
async def get_db_status():
    """获取数据库连接状态"""
    try:
        result = await oracle_mcp.test_connection()
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/v1/db/tables")
async def get_db_tables(schema: Optional[str] = None):
    """获取数据库表列表"""
    try:
        result = await oracle_mcp.get_tables(schema)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/db/tables/{table_name}")
async def get_table_schema(table_name: str, schema: Optional[str] = None):
    """获取表结构"""
    try:
        result = await oracle_mcp.describe_table(table_name, schema)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/db/query")
async def execute_query(sql: str, max_rows: int = 100):
    """执行 SQL 查询"""
    try:
        # 安全检查：只允许 SELECT 语句
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith('SELECT'):
            raise HTTPException(
                status_code=400,
                detail="只允许执行 SELECT 查询"
            )

        result = await oracle_mcp.query(sql, max_rows=max_rows)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== WebSocket 端点 ==============

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket 实时通信

    - 接收分析请求
    - 推送进度更新
    - 支持人工审核交互
    """
    await manager.connect(websocket, client_id)

    try:
        while True:
            # 接收消息
            data = await websocket.receive_json()
            msg_type = data.get('type')

            if msg_type == 'analyze':
                # 开始分析
                query = data.get('query')
                # 每次查询都生成新的 thread_id，避免状态污染
                thread_id = str(uuid.uuid4())
                session_id = data.get('session_id') or client_id  # 使用 session_id 或 client_id

                # 获取对话上下文摘要（用于增强查询）
                context_summary = conversation_store.get_context_summary(session_id)
                current_turn = context_summary.get('total_turns', 0) + 1
                print(f"[Server] Session {session_id} context: {current_turn - 1} turns")

                await manager.send_message(client_id, {
                    "type": "started",
                    "thread_id": thread_id,
                    "session_id": session_id,
                    "message": "分析任务已启动"
                })

                try:
                    # 如果有多轮对话，添加上下文到查询
                    enhanced_query = query
                    if current_turn > 1:
                        # 获取上一轮的analysis配置
                        prev_turns = conversation_store.get_history(session_id, limit=2)
                        prev_analysis = {}
                        if len(prev_turns) >= 1:
                            prev_context = prev_turns[-1].context or {}
                            prev_analysis = prev_context.get('analysis_config', {})

                        # 检测指代词（如"该时间段内"），需要继承日期范围
                        coreferential_keywords = ['该时间段', '该时间', '这个时间段', '此时间段', '上述时间', '刚才', '之前', '上次']
                        needs_date_injection = any(kw in query for kw in coreferential_keywords)

                        date_range = prev_analysis.get('date_range', {})
                        if needs_date_injection and date_range.get('start') and date_range.get('end'):
                            # 把日期范围直接注入到查询中，替换指代词
                            start = date_range['start']
                            end = date_range['end']
                            # 简化日期显示（去掉年份如果和当前年相同）
                            from datetime import datetime
                            try:
                                start_dt = datetime.strptime(start, '%Y-%m-%d')
                                end_dt = datetime.strptime(end, '%Y-%m-%d')
                                current_year = datetime.now().year
                                if start_dt.year == current_year:
                                    start_display = f"{start_dt.month}月{start_dt.day}日"
                                else:
                                    start_display = start
                                if end_dt.year == current_year:
                                    end_display = f"{end_dt.month}月{end_dt.day}日"
                                else:
                                    end_display = end
                                date_str = f"{start_display}到{end_display}"
                            except:
                                date_str = f"{start}到{end}"

                            # 替换查询中的指代词为具体日期
                            enhanced_query = query
                            for kw in coreferential_keywords:
                                enhanced_query = enhanced_query.replace(kw, date_str)
                            print(f"[Server] 日期注入: '{query}' -> '{enhanced_query}'")

                        # 添加上下文信息（精简版，避免LLM超时）
                        enhanced_query = f"""{enhanced_query}

[对话上下文]
上一轮配置: {json.dumps(prev_analysis, ensure_ascii=False)}
"""
                        print(f"[Server] Enhanced query with context: {enhanced_query[:200]}...")

                    # 保存用户查询到对话历史（包含增强后的查询）
                    conversation_store.add_turn(
                        session_id=session_id,
                        user_message=enhanced_query,  # 保存增强后的查询
                        agent_response={"status": "processing"},
                        context={"thread_id": thread_id, "type": "user_query", "original_query": query}
                    )

                    result = await team_graph.run(enhanced_query, thread_id)

                    if result is None:
                        print("[Server] Error: team_graph.run() returned None")
                        await manager.send_message(client_id, {
                            "type": "error",
                            "thread_id": thread_id,
                            "session_id": session_id,
                            "error": "工作流返回空结果"
                        })
                        continue

                    # 处理 StateSnapshot 对象
                    if hasattr(result, 'values') and isinstance(result.values, dict):
                        result = result.values

                    print(f"[Server] Workflow result type: {type(result)}, keys: {result.keys() if isinstance(result, dict) else 'N/A'}")

                    # 打印完整的 results 结构
                    results = result.get('results', {})
                    print(f"[Server] Results keys: {list(results.keys())}")
                    for key, value in results.items():
                        print(f"[Server] Results[{key}] type: {type(value)}, keys: {value.keys() if isinstance(value, dict) else 'N/A'}")

                    # 直接从 results 构建返回
                    passenger_result = results.get('passenger', {})
                    operation_result = results.get('operation', {})

                    print(f"[Server] passenger_result type: {type(passenger_result)}, has error: {'error' in passenger_result if isinstance(passenger_result, dict) else 'N/A'}")
                    print(f"[Server] operation_result type: {type(operation_result)}, has error: {'error' in operation_result if isinstance(operation_result, dict) else 'N/A'}")

                    # 检查是否有错误
                    passenger_error = passenger_result.get('error') if isinstance(passenger_result, dict) else None
                    operation_error = operation_result.get('error') if isinstance(operation_result, dict) else None

                    if passenger_error:
                        print(f"[Server] passenger_processor 错误: {passenger_error}")
                    if operation_error:
                        print(f"[Server] operation_scheduler 错误: {operation_error}")

                    # 提取关键发现
                    findings = []
                    if passenger_result and 'key_findings' in passenger_result:
                        findings.extend(passenger_result['key_findings'])
                    if operation_result and 'key_findings' in operation_result:
                        findings.extend(operation_result['key_findings'])

                    # 如果有错误，添加错误信息到关键发现
                    if passenger_error:
                        findings.append(f"【里程分析错误】{passenger_error}")
                    if operation_error:
                        findings.append(f"【订单分析错误】{operation_error}")

                    # 提取统计数据
                    passenger_stats = passenger_result.get('statistics', {}) if isinstance(passenger_result, dict) else {}
                    operation_stats = operation_result.get('statistics', {}) if isinstance(operation_result, dict) else {}

                    final_report = {
                        "analysis_summary": "数据分析完成" if not (passenger_error or operation_error) else "数据分析部分失败",
                        "key_findings": findings,
                        "statistics": {
                            "passenger": passenger_stats,
                            "operation": operation_stats
                        },
                        "details": {
                            "passenger": passenger_result,
                            "operation": operation_result
                        },
                        "errors": {
                            "passenger": passenger_error,
                            "operation": operation_error
                        }
                    }

                    response_payload = {
                        "type": "completed",
                        "thread_id": thread_id,
                        "session_id": session_id,
                        "status": result.get('status'),
                        "result": {
                            "final_report": final_report,
                            "results": results
                        },
                        "requires_human_review": result.get('requires_human_review', False)
                    }

                    # 打印完整的响应数据
                    print(f"[Server] Full response payload: {json.dumps(response_payload, ensure_ascii=False, default=str)[:2000]}")

                    # 提取分析配置供下一轮使用
                    # 从结果中提取日期范围（如果有）
                    passenger_result = results.get('passenger', {})
                    operation_result = results.get('operation', {})
                    date_range = {}
                    if passenger_result.get('sql_used'):
                        # 尝试从SQL中提取日期
                        date_range = extract_date_range_from_sql(passenger_result.get('sql_used', ''))
                    if not date_range and operation_result.get('sql_used'):
                        date_range = extract_date_range_from_sql(operation_result.get('sql_used', ''))
                    if not date_range:
                        # Fallback: 从分析结果中获取日期范围
                        date_range = result.get('analysis', {}).get('date_range', {})

                    analysis_config = {
                        "needs_passenger": result.get('analysis', {}).get('needs_passenger', True),
                        "needs_operation": result.get('analysis', {}).get('needs_operation', True),
                        "inherited": result.get('analysis', {}).get('inferred_from_context', False),
                        "date_range": date_range,
                        "original_query": query  # 保存原始查询供参考
                    }

                    # 更新对话历史中的 agent 响应（而不是添加新记录）
                    conversation_store.update_last_turn(
                        session_id=session_id,
                        agent_response=response_payload,
                        context={
                            "thread_id": thread_id,
                            "type": "agent_response",
                            "analysis_type": "dynamic_bus",
                            "analysis_config": analysis_config  # 保存配置供下一轮继承
                        }
                    )

                    print(f"[Server] Sending response: {json.dumps(response_payload, ensure_ascii=False, default=str)[:500]}...")

                    await manager.send_message(client_id, response_payload)

                except Exception as e:
                    await manager.send_message(client_id, {
                        "type": "error",
                        "thread_id": thread_id,
                        "session_id": session_id,
                        "error": str(e)
                    })

            elif msg_type == 'feedback':
                # 提交人工反馈
                thread_id = data.get('thread_id')
                feedback = data.get('feedback')

                try:
                    result = team_graph.resume_after_interrupt(thread_id, feedback)

                    await manager.send_message(client_id, {
                        "type": "completed",
                        "thread_id": thread_id,
                        "status": result.get('status'),
                        "result": result.get('final_report')
                    })

                except Exception as e:
                    await manager.send_message(client_id, {
                        "type": "error",
                        "thread_id": thread_id,
                        "error": str(e)
                    })

            elif msg_type == 'history':
                # 获取对话历史
                session_id = data.get('session_id') or client_id
                limit = data.get('limit', 10)

                try:
                    history = conversation_store.get_history(session_id, limit=limit)
                    context_summary = conversation_store.get_context_summary(session_id)

                    await manager.send_message(client_id, {
                        "type": "history",
                        "session_id": session_id,
                        "history": [
                            {
                                "turn_id": turn.turn_id,
                                "user_message": turn.user_message,
                                "timestamp": turn.timestamp,
                                "context": turn.context
                            }
                            for turn in history
                        ],
                        "context_summary": context_summary
                    })

                except Exception as e:
                    await manager.send_message(client_id, {
                        "type": "error",
                        "error": f"获取历史失败: {str(e)}"
                    })

            elif msg_type == 'clear_history':
                # 清空对话历史
                session_id = data.get('session_id') or client_id

                try:
                    conversation_store.clear_session(session_id)
                    await manager.send_message(client_id, {
                        "type": "history_cleared",
                        "session_id": session_id,
                        "message": "对话历史已清空"
                    })

                except Exception as e:
                    await manager.send_message(client_id, {
                        "type": "error",
                        "error": f"清空历史失败: {str(e)}"
                    })

            elif msg_type == 'status':
                # 查询状态
                thread_id = data.get('thread_id')
                state = team_graph.get_state(thread_id)

                await manager.send_message(client_id, {
                    "type": "status",
                    "thread_id": thread_id,
                    "state": state
                })

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        print(f"[Server] WebSocket error for client {client_id}: {e}")
        manager.disconnect(client_id)
        # 不要抛出 HTTPException，WebSocket 中应该发送消息或静默断开
        try:
            await manager.send_message(client_id, {
                "type": "error",
                "error": f"服务器错误: {str(e)}"
            })
        except:
            pass  # 如果发送失败，静默处理


# ============== 动态公交查询 API ==============

@app.get("/api/v1/dynamic-bus/orders")
async def get_dynamic_bus_orders(
    start_date: str = None,
    end_date: str = None
):
    """
    查询动态公交订单统计

    参数:
    - start_date: 开始日期 (YYYY-MM-DD)
    - end_date: 结束日期 (YYYY-MM-DD)
    """
    try:
        from tools.mcp_oracle import oracle_mcp

        # 默认查询最近7天
        if not start_date:
            start_date = "SYSDATE - 7"
        else:
            start_date = f"TO_DATE('{start_date}', 'YYYY-MM-DD')"

        if not end_date:
            end_date = "SYSDATE"
        else:
            end_date = f"TO_DATE('{end_date}', 'YYYY-MM-DD')"

        sql = f"""
            SELECT
                COUNT(*) as total_orders,
                SUM(PASSENGER) as total_passengers,
                COUNT(CASE WHEN STATUS_NAME = '已完成' THEN 1 END) as completed_orders,
                COUNT(CASE WHEN STATUS_NAME = '已取消' THEN 1 END) as cancelled_orders,
                SUM(CASE WHEN STATUS_NAME = '已完成' THEN PAY_AMOUNT ELSE 0 END) as total_revenue
            FROM DY_ORDER_INFO
            WHERE CREATE_DATE >= {start_date}
              AND CREATE_DATE < {end_date}
        """

        result = await oracle_mcp.query(sql)

        if result.get("success"):
            row = result.get("rows", [{}])[0]
            return {
                "success": True,
                "period": f"{start_date} to {end_date}",
                "statistics": {
                    "total_orders": row.get("TOTAL_ORDERS", 0),
                    "completed_orders": row.get("COMPLETED_ORDERS", 0),
                    "cancelled_orders": row.get("CANCELLED_ORDERS", 0),
                    "total_passengers": row.get("TOTAL_PASSENGERS", 0),
                    "total_revenue": float(row.get("TOTAL_REVENUE", 0)),
                    "completion_rate": round(row.get("COMPLETED_ORDERS", 0) / row.get("TOTAL_ORDERS", 1) * 100, 2) if row.get("TOTAL_ORDERS", 0) > 0 else 0
                }
            }
        else:
            return {"success": False, "error": result.get("error")}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== 辅助函数 ==============

def extract_date_range_from_sql(sql: str) -> dict:
    """从SQL中提取日期范围（用户意图的实际日期，非SQL边界）。"""
    import re
    from datetime import datetime, timedelta

    date_range = {}

    if not sql:
        return date_range

    sql_upper = sql.upper()

    # 匹配 TO_DATE('2026-03-10', 'YYYY-MM-DD') 格式
    to_date_pattern = r"TO_DATE\('(\d{4}-\d{2}-\d{2})'\s*,\s*'YYYY-MM-DD'\)"
    dates = re.findall(to_date_pattern, sql)

    if len(dates) >= 2:
        start_date = dates[0]
        end_boundary = dates[1]  # SQL中的边界日期（可能已+1天）

        # 判断SQL使用的是 < 还是 <=
        # 查找第二个日期前面的比较运算符
        # 策略：在SQL中找到第二个TO_DATE出现的位置，向前查找最近的比较运算符
        end_pos = sql_upper.find(f"TO_DATE('{end_boundary}'".upper())
        before_end = sql_upper[max(0, end_pos - 20):end_pos] if end_pos > 0 else ""

        if '<=' in before_end or '≤' in before_end:
            # <= 表示边界日期是包含的，直接作为结束日期
            date_range['start'] = start_date
            date_range['end'] = end_boundary
        elif '<' in before_end:
            # < 表示边界日期不包含，减一天得到用户实际意图的结束日期
            try:
                dt = datetime.strptime(end_boundary, '%Y-%m-%d')
                actual_end = (dt - timedelta(days=1)).strftime('%Y-%m-%d')
                date_range['start'] = start_date
                date_range['end'] = actual_end
            except ValueError:
                date_range['start'] = start_date
                date_range['end'] = end_boundary
        else:
            # 无法判断，保守处理：如果start == end_boundary-1天，可能是<边界
            date_range['start'] = start_date
            date_range['end'] = end_boundary

    elif len(dates) == 1:
        date_range['start'] = dates[0]

    return date_range


# ============== 健康检查 ==============

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "service": "agent-teams-api",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Agent Teams API 服务运行中",
        "docs": "/docs",
        "health": "/health"
    }


# ============== 启动配置 ==============

def run_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """启动服务器"""
    import uvicorn
    uvicorn.run(
        "api.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )


if __name__ == "__main__":
    run_server()
