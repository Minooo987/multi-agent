"""
监控和指标收集
"""

import time
from functools import wraps
from typing import Callable, Dict, Any
from dataclasses import dataclass, field
from collections import defaultdict

from utils import logger


@dataclass
class Metric:
    """指标数据"""
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """指标收集器"""

    def __init__(self):
        self.metrics: Dict[str, list] = defaultdict(list)
        self.counters: Dict[str, int] = defaultdict(int)
        self.gauges: Dict[str, float] = {}

    def record(self, name: str, value: float, labels: Dict[str, str] = None):
        """记录指标"""
        metric = Metric(name=name, value=value, labels=labels or {})
        self.metrics[name].append(metric)

        # 限制存储数量
        if len(self.metrics[name]) > 1000:
            self.metrics[name] = self.metrics[name][-500:]

    def increment(self, name: str, value: int = 1):
        """增加计数器"""
        self.counters[name] += value

    def gauge(self, name: str, value: float):
        """设置仪表盘值"""
        self.gauges[name] = value

    def get_summary(self) -> Dict[str, Any]:
        """获取指标摘要"""
        summary = {
            "counters": dict(self.counters),
            "gauges": self.gauges,
            "metrics": {}
        }

        for name, metrics in self.metrics.items():
            if metrics:
                values = [m.value for m in metrics]
                summary["metrics"][name] = {
                    "count": len(values),
                    "avg": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "latest": values[-1]
                }

        return summary

    def reset(self):
        """重置所有指标"""
        self.metrics.clear()
        self.counters.clear()
        self.gauges.clear()


# 全局收集器
metrics = MetricsCollector()


def timed(metric_name: str = None):
    """
    函数执行时间装饰器

    Usage:
        @timed("my_function_duration")
        async def my_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        name = metric_name or f"{func.__module__}.{func.__name__}"

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                metrics.increment(f"{name}.success")
                return result
            except Exception as e:
                metrics.increment(f"{name}.error")
                raise
            finally:
                duration = time.time() - start
                metrics.record(name, duration)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                metrics.increment(f"{name}.success")
                return result
            except Exception as e:
                metrics.increment(f"{name}.error")
                raise
            finally:
                duration = time.time() - start
                metrics.record(name, duration)

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


def track_errors(metric_name: str = None):
    """
    错误跟踪装饰器

    Usage:
        @track_errors("my_function")
        async def my_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        name = metric_name or f"{func.__module__}.{func.__name__}"

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                metrics.increment(f"{name}.error")
                logger.error(f"Error in {name}: {e}")
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                metrics.increment(f"{name}.error")
                logger.error(f"Error in {name}: {e}")
                raise

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


# 导入 asyncio 用于类型检查
import asyncio
