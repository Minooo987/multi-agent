"""
查询日志记录器
记录每次查询的完整信息，用于后续分析改进
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class QueryLog:
    log_id: str
    session_id: str
    user_query: str
    generated_sql: str
    execution_time_ms: int
    result_row_count: int
    success: bool
    error_message: Optional[str]
    user_feedback: Optional[str]  # "正确" / "不对: ..."
    template_used: Optional[str]  # 使用的模板名
    llm_model: str
    timestamp: str


class QueryLogger:
    """查询日志记录器"""

    def __init__(self, log_dir: str = "logs/queries"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log(self, log: QueryLog):
        """记录查询日志"""
        file_path = self.log_dir / f"{log.session_id}.jsonl"
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(log), ensure_ascii=False) + "\n")

    def get_failure_patterns(self, days: int = 7) -> Dict[str, int]:
        """分析失败模式"""
        patterns = {}
        # 实现：读取日志，聚类分析用户反馈为"不对"的查询
        # 返回：{"avg_mileage_semantic_error": 15, "date_range_missing": 8, ...}
        return patterns

    def get_template_usage_stats(self) -> Dict[str, int]:
        """统计模板使用情况"""
        stats = {}
        # 实现：统计各模板使用次数和成功率
        return stats


# 全局实例
query_logger = QueryLogger()
