"""
LangSmith 集成
实现追踪、监控和评估
"""

import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from contextlib import contextmanager
import json
import uuid

# 尝试导入 LangSmith
try:
    from langsmith import Client
    from langsmith.run_trees import RunTree
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    print("[Tracing] LangSmith 未安装，使用本地追踪")

from config.settings import settings


class TracingManager:
    """
    追踪管理器
    集成 LangSmith 进行运行追踪
    支持本地持久化存储
    """

    def __init__(self, max_local_runs: int = 1000, persist_path: str = None):
        self.client = None
        self.local_runs: List[Dict] = []
        self.enabled = False
        self.max_local_runs = max_local_runs
        self.persist_path = persist_path or os.path.join(
            os.path.dirname(__file__), '..', 'data', 'tracing_runs.json'
        )

        # 加载历史数据
        self._load_runs()

        if LANGSMITH_AVAILABLE:
            try:
                api_key = settings.langchain_api_key or os.getenv("LANGCHAIN_API_KEY")
                if api_key:
                    self.client = Client(api_key=api_key)
                    self.enabled = True
                    print("[Tracing] LangSmith 已连接")
                else:
                    print("[Tracing] 未配置 LangSmith API Key")
            except Exception as e:
                print(f"[Tracing] LangSmith 连接失败: {e}")

    def _load_runs(self):
        """从磁盘加载历史追踪数据"""
        if os.path.exists(self.persist_path):
            try:
                with open(self.persist_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.local_runs = data.get('runs', [])
                print(f"[Tracing] 已加载 {len(self.local_runs)} 条历史追踪记录")
            except Exception as e:
                print(f"[Tracing] 加载历史数据失败: {e}")
                self.local_runs = []
        else:
            self.local_runs = []

    def _save_runs(self):
        """保存追踪数据到磁盘"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)

            data = {
                'runs': self.local_runs,
                'saved_at': datetime.now().isoformat(),
                'total_count': len(self.local_runs)
            }

            with open(self.persist_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Tracing] 保存追踪数据失败: {e}")

    def _persist_if_needed(self):
        """根据条件触发持久化"""
        # 每10次新增记录保存一次
        if len(self.local_runs) % 10 == 0:
            self._save_runs()

    def create_run(
        self,
        name: str,
        run_type: str = "chain",
        inputs: Dict[str, Any] = None,
        parent_run_id: str = None
    ) -> str:
        """
        创建新的追踪运行
        """
        run_id = str(uuid.uuid4())

        run_data = {
            "id": run_id,
            "name": name,
            "run_type": run_type,
            "inputs": inputs or {},
            "outputs": {},
            "error": None,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "parent_run_id": parent_run_id,
            "child_runs": []
        }

        self.local_runs.append(run_data)

        # 限制本地存储大小
        if len(self.local_runs) > self.max_local_runs:
            self.local_runs = self.local_runs[-self.max_local_runs:]

        # 触发持久化
        self._persist_if_needed()

        if self.enabled and self.client:
            try:
                self.client.create_run(
                    name=name,
                    run_type=run_type,
                    inputs=inputs or {},
                    id=run_id,
                    parent_run_id=parent_run_id
                )
            except Exception as e:
                print(f"[Tracing] LangSmith 创建运行失败: {e}")

        return run_id

    def end_run(
        self,
        run_id: str,
        outputs: Dict[str, Any] = None,
        error: str = None
    ):
        """
        结束追踪运行
        """
        # 更新本地记录
        for run in self.local_runs:
            if run["id"] == run_id:
                run["outputs"] = outputs or {}
                run["error"] = error
                run["end_time"] = datetime.now().isoformat()
                break

        # 触发持久化
        self._persist_if_needed()

        if self.enabled and self.client:
            try:
                self.client.update_run(
                    run_id=run_id,
                    outputs=outputs or {},
                    error=error,
                    end_time=datetime.now()
                )
            except Exception as e:
                print(f"[Tracing] LangSmith 更新运行失败: {e}")

    @contextmanager
    def trace(self, name: str, run_type: str = "chain", inputs: Dict = None):
        """
        上下文管理器形式的追踪

        用法:
        with tracer.trace("my_operation", inputs={"query": "test"}) as run_id:
            result = do_something()
            tracer.record_output(run_id, {"result": result})
        """
        run_id = self.create_run(name, run_type, inputs)
        try:
            yield run_id
        except Exception as e:
            self.end_run(run_id, error=str(e))
            raise
        else:
            self.end_run(run_id)

    def record_feedback(
        self,
        run_id: str,
        key: str,
        score: float,
        comment: str = None
    ):
        """
        记录反馈评分
        """
        if self.enabled and self.client:
            try:
                self.client.create_feedback(
                    run_id=run_id,
                    key=key,
                    score=score,
                    comment=comment
                )
            except Exception as e:
                print(f"[Tracing] 记录反馈失败: {e}")

    def get_run_stats(self) -> Dict[str, Any]:
        """获取运行统计"""
        total = len(self.local_runs)
        completed = sum(1 for r in self.local_runs if r["end_time"])
        errors = sum(1 for r in self.local_runs if r["error"])

        # 按类型分组
        by_type = {}
        for run in self.local_runs:
            run_type = run.get("run_type", "unknown")
            by_type[run_type] = by_type.get(run_type, 0) + 1

        return {
            "total_runs": total,
            "completed": completed,
            "errors": errors,
            "success_rate": (completed - errors) / completed if completed > 0 else 0,
            "by_type": by_type,
            "langsmith_connected": self.enabled
        }


# 全局追踪管理器
tracer = TracingManager()
