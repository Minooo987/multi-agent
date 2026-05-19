"""
HTTP API 客户端示例
"""

import requests
import time
from typing import Optional, Dict, Any


class AgentTeamsAPI:
    """
    Agent Teams HTTP API 客户端

    Usage:
        api = AgentTeamsAPI("http://localhost:8000")
        result = api.analyze("分析昨天客流")
    """

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()

    def analyze(
        self,
        query: str,
        thread_id: Optional[str] = None,
        require_human_review: bool = False
    ) -> Dict[str, Any]:
        """
        同步分析（等待结果）

        Args:
            query: 分析查询
            thread_id: 可选的会话ID
            require_human_review: 是否需要人工审核

        Returns:
            分析结果
        """
        response = self.session.post(
            f"{self.base_url}/api/v1/analyze",
            json={
                "query": query,
                "thread_id": thread_id,
                "require_human_review": require_human_review
            }
        )
        response.raise_for_status()
        return response.json()

    def analyze_async(
        self,
        query: str,
        thread_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        异步分析（立即返回）

        Args:
            query: 分析查询
            thread_id: 可选的会话ID

        Returns:
            包含 thread_id 的响应
        """
        response = self.session.post(
            f"{self.base_url}/api/v1/analyze/async",
            json={
                "query": query,
                "thread_id": thread_id
            }
        )
        response.raise_for_status()
        return response.json()

    def get_status(self, thread_id: str) -> Dict[str, Any]:
        """
        获取任务状态

        Args:
            thread_id: 会话ID

        Returns:
            状态信息
        """
        response = self.session.get(
            f"{self.base_url}/api/v1/status/{thread_id}"
        )
        response.raise_for_status()
        return response.json()

    def get_results(self, thread_id: str) -> Dict[str, Any]:
        """
        获取分析结果

        Args:
            thread_id: 会话ID

        Returns:
            完整结果
        """
        response = self.session.get(
            f"{self.base_url}/api/v1/results/{thread_id}"
        )
        response.raise_for_status()
        return response.json()

    def submit_feedback(self, thread_id: str, feedback: str) -> Dict[str, Any]:
        """
        提交人工反馈

        Args:
            thread_id: 会话ID
            feedback: 反馈内容

        Returns:
            更新后的结果
        """
        response = self.session.post(
            f"{self.base_url}/api/v1/feedback",
            json={
                "thread_id": thread_id,
                "feedback": feedback
            }
        )
        response.raise_for_status()
        return response.json()

    def wait_for_completion(
        self,
        thread_id: str,
        timeout: int = 300,
        poll_interval: int = 2
    ) -> Dict[str, Any]:
        """
        等待任务完成

        Args:
            thread_id: 会话ID
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）

        Returns:
            最终结果
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = self.get_status(thread_id)

            if status.get('status') in ['completed', 'error']:
                return self.get_results(thread_id)

            if status.get('requires_human_review'):
                print(f"任务 {thread_id} 需要人工审核")
                return status

            time.sleep(poll_interval)

        raise TimeoutError(f"等待任务 {thread_id} 超时")

    def db_status(self) -> Dict[str, Any]:
        """获取数据库状态"""
        response = self.session.get(f"{self.base_url}/api/v1/db/status")
        response.raise_for_status()
        return response.json()

    def list_tables(self, schema: Optional[str] = None) -> Dict[str, Any]:
        """获取表列表"""
        params = {"schema": schema} if schema else {}
        response = self.session.get(
            f"{self.base_url}/api/v1/db/tables",
            params=params
        )
        response.raise_for_status()
        return response.json()

    def describe_table(self, table_name: str) -> Dict[str, Any]:
        """获取表结构"""
        response = self.session.get(
            f"{self.base_url}/api/v1/db/tables/{table_name}"
        )
        response.raise_for_status()
        return response.json()


def demo():
    """演示用法"""
    api = AgentTeamsAPI()

    print("=" * 50)
    print("Agent Teams API 客户端演示")
    print("=" * 50)

    # 检查数据库状态
    print("\n1. 检查数据库状态")
    db_status = api.db_status()
    print(f"   数据库连接: {'✅' if db_status.get('connected') else '❌'}")

    # 同步分析
    print("\n2. 执行同步分析")
    result = api.analyze("分析昨天各线路的客流情况")
    print(f"   状态: {result.get('status')}")
    print(f"   报告预览: {result.get('result', {}).get('final_report', 'N/A')[:100]}...")

    # 异步分析
    print("\n3. 执行异步分析")
    async_result = api.analyze_async("统计本周收入最高的5条线路")
    thread_id = async_result.get('thread_id')
    print(f"   任务ID: {thread_id}")

    # 等待完成
    print("\n4. 等待任务完成")
    final_result = api.wait_for_completion(thread_id, timeout=60)
    print(f"   最终状态: {final_result.get('status')}")

    # 获取表列表
    print("\n5. 获取数据库表列表")
    tables = api.list_tables()
    if tables.get('success'):
        table_names = [t.get('TABLE_NAME') for t in tables.get('rows', [])[:5]]
        print(f"   表列表: {table_names}")

    print("\n✅ 演示完成")


if __name__ == "__main__":
    demo()
