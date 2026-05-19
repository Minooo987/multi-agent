"""
Key Findings Generator - 统一的关键发现生成器
支持 LLM 驱动的灵活发现生成 + 规则化降级
"""

import json
import asyncio
from typing import Any, Dict, List, Optional, TypedDict
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings


class DataSummary(TypedDict, total=False):
    """统一的数据摘要格式"""
    domain: str  # "passenger" | "operation"
    query_type: str  # "aggregated" | "grouped"
    statistics: Dict[str, Any]
    group_by: Optional[str]
    record_count: int
    top_data: Optional[List[Dict[str, Any]]]
    task_description: str


@dataclass
class GenerationConfig:
    """生成配置"""
    max_findings: int = 7
    timeout: float = 30.0
    temperature: float = 0.3
    max_tokens: int = 2048


class KeyFindingsGenerator:
    """
    统一的关键发现生成器

    职责：
    1. 接收统一格式的 DataSummary
    2. 使用 LLM 生成结构化、灵活的关键发现
    3. LLM 失败时自动降级到规则化生成
    """

    def __init__(self, config: GenerationConfig = None):
        self.config = config or GenerationConfig()
        self.llm = ChatOpenAI(
            model=settings.model_name,
            openai_api_base=settings.model_base_url,
            openai_api_key=settings.model_api_key,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            streaming=False  # 关键发现不需要流式，减少延迟
        )

    async def generate(
        self,
        data_summary: DataSummary,
        task_description: str = ""
    ) -> List[str]:
        """
        生成关键发现（主入口）

        流程：
        1. 构建精简 Prompt（预填充统计，不计算）
        2. LLM 生成（15秒超时）
        3. 解析 JSON 数组
        4. 失败/超时则降级到规则化生成

        Args:
            data_summary: 统一格式的数据摘要
            task_description: 原始任务描述（可选）

        Returns:
            关键发现字符串列表（永不返回空）
        """
        # 提取必要字段
        domain = data_summary.get("domain", "")
        query_type = data_summary.get("query_type", "aggregated")
        statistics = data_summary.get("statistics", {})
        group_by = data_summary.get("group_by")
        record_count = data_summary.get("record_count", 0)
        top_data = data_summary.get("top_data")
        task = task_description or data_summary.get("task_description", "")

        # 构建 Prompt（精简高效）
        prompt = self._build_prompt(
            domain=domain,
            query_type=query_type,
            statistics=statistics,
            group_by=group_by,
            record_count=record_count,
            top_data=top_data,
            task_description=task,
            max_findings=self.config.max_findings
        )

        try:
            print(f"[KeyFindingsGenerator] 调用 LLM 生成关键发现...")
            response = await asyncio.wait_for(
                self.llm.ainvoke([
                    SystemMessage(content="你是数据分析师，擅长从数据中提取洞察。根据提供的数据直接输出发现，不要做额外计算。请用中文输出。"),
                    HumanMessage(content=prompt)
                ]),
                timeout=self.config.timeout
            )
            content = response.content.strip()

            # 解析 JSON 数组
            findings = self._parse_json_array(content)
            if findings:
                # 如果 LLM 返回不足 5 条，用规则补充
                if len(findings) < 5:
                    fallback = self.generate_fallback(domain, statistics, query_type, group_by, top_data)
                    # 去重后补充
                    existing_set = set(findings)
                    for f in fallback:
                        if f not in existing_set and len(findings) < self.config.max_findings:
                            findings.append(f)
                print(f"[KeyFindingsGenerator] LLM 生成 {len(findings)} 条关键发现")
                return findings[:self.config.max_findings]

            print(f"[KeyFindingsGenerator] LLM 输出解析为空，降级到规则生成")

        except asyncio.TimeoutError:
            print(f"[KeyFindingsGenerator] LLM 生成超时({self.config.timeout}s)，降级到规则生成")
        except Exception as e:
            print(f"[KeyFindingsGenerator] LLM 生成失败: {e}，降级到规则生成")

        # 统一降级
        return self.generate_fallback(domain, statistics, query_type, group_by, top_data)

    def _build_prompt(
        self,
        domain: str,
        query_type: str,
        statistics: Dict[str, Any],
        group_by: Optional[str],
        record_count: int,
        top_data: Optional[List[Dict]],
        task_description: str,
        max_findings: int
    ) -> str:
        """构建精简高效的 Prompt"""

        # 统计信息文本（预格式化，LLM 无需计算）
        stats_text = json.dumps(statistics, ensure_ascii=False, indent=2)

        # 排名数据文本
        top_text = ""
        if top_data and group_by:
            top_text = f"\n## 排名数据（按 {group_by}）\n"
            for i, item in enumerate(top_data[:5], 1):
                name = item.get(group_by, "未知")
                # 查找数值字段（非分组字段）
                value_keys = [k for k in item.keys() if k != group_by]
                if value_keys:
                    val_key = value_keys[0]
                    val = item.get(val_key, 0)
                    top_text += f"{i}. {name}: {val}\n"

        # 发现类型引导（不强制，供 LLM 参考）
        finding_types = """## 发现类型参考（根据数据特点选择，不强制全部）
- 趋势描述：数据整体规模、水平
- 异常识别：最高/最低、偏离均值的情况
- 排名对比：Top 表现的具体差距
- 效率评估：利用率、完成率等指标的评价
- 改进建议：基于数据的可操作建议"""

        return f"""根据以下数据生成 5-{max_findings} 条关键发现（严格不少于5条）。

## 任务
{task_description[:150] if task_description else "数据分析"}

## 数据类型
{ "分组明细" if query_type == "grouped" else "聚合概览" }{' | 分组列: ' + group_by if group_by else ''}

## 核心统计（已预计算）
{stats_text}
{finding_types}
{top_text}
## 要求
1. 基于已提供的统计数据，直接提炼洞察（不要重新计算）
2. 优先选择数据中最突出的特点生成发现
3. 长度灵活，但总共不超过 {max_findings} 条
4. 输出格式为 JSON 数组: ["发现1", "发现2", ...]
5. 不要输出任何解释或 markdown 格式

请直接输出 JSON 数组:"""

    def _parse_json_array(self, content: str) -> Optional[List[str]]:
        """从 LLM 响应中解析 JSON 数组"""
        # 查找方括号包裹的数组
        start = content.find('[')
        end = content.rfind(']')
        if start >= 0 and end > start:
            try:
                json_str = content[start:end+1]
                findings = json.loads(json_str)
                if isinstance(findings, list) and findings:
                    # 过滤空字符串
                    return [str(f).strip() for f in findings if str(f).strip()]
            except json.JSONDecodeError:
                pass
        return None

    def generate_fallback(
        self,
        domain: str,
        statistics: Dict[str, Any],
        query_type: str = "aggregated",
        group_by: Optional[str] = None,
        top_data: Optional[List[Dict]] = None
    ) -> List[str]:
        """
        规则化降级生成（LLM 失败时使用）

        逻辑：
        - passenger 领域：关注里程、利用率、车辆数
        - operation 领域：关注订单数、完成率、乘客数
        - grouped 类型：关注排名、分布
        """
        findings = []

        if domain == "passenger":
            findings = self._generate_passenger_fallback(statistics, query_type, group_by, top_data)
        elif domain == "operation":
            findings = self._generate_operation_fallback(statistics, query_type, group_by, top_data)
        else:
            # 通用降级
            if statistics:
                findings.append(f"数据统计完成，核心指标: {json.dumps(statistics, ensure_ascii=False)[:100]}")
            else:
                findings.append("数据查询完成")

        return findings if findings else ["数据查询完成，但未提取到有效统计信息"]

    def _generate_passenger_fallback(
        self,
        statistics: Dict[str, Any],
        query_type: str,
        group_by: Optional[str],
        top_data: Optional[List[Dict]]
    ) -> List[str]:
        """Passenger 领域降级生成（目标 5-7 条）"""
        findings = []

        total = statistics.get("total_mileage_km", 0)
        carry = statistics.get("carry_mileage_km", 0)
        rate = statistics.get("mileage_utilization_rate", 0)
        empty = statistics.get("empty_mileage_km", 0) or (total - carry if total > 0 else 0)
        buses = statistics.get("unique_buses", 0)
        days = statistics.get("unique_days", 0)
        record_count = statistics.get("record_count", 0)

        # 分组维度中文映射
        from schema.column_registry import ColumnRegistry
        group_name_map = {
            "DRIVER_NAME": ColumnRegistry.get_label("DRIVER_NAME"),
            "DRIVER_ID": ColumnRegistry.get_label("DRIVER_ID"),
            "BUS_NO": ColumnRegistry.get_label("BUS_NO"),
            "BUS_ID": ColumnRegistry.get_label("BUS_ID"),
            "ROUTE_NAME": ColumnRegistry.get_label("ROUTE_NAME"),
            "REGION_NAME": ColumnRegistry.get_label("REGION_NAME"),
            "STATION_NAME": ColumnRegistry.get_label("STATION_NAME"),
            "STATUS_NAME": ColumnRegistry.get_label("STATUS_NAME"),
        }

        avg_daily = statistics.get("avg_daily_mileage_km", 0)
        avg_per_bus = statistics.get("avg_per_bus_mileage_km", 0)

        # 分组查询时，avg_daily 实际上可能是每车的日均里程（LLM 列名差异）
        # 如果是分组查询且 avg_daily > 0 但 avg_per_bus == 0，用 avg_daily 作为每车指标
        effective_avg_per_bus = avg_per_bus if avg_per_bus > 0 else (avg_daily if query_type == "grouped" and avg_daily > 0 else 0)

        if query_type == "grouped" and group_by and top_data:
            # 分组查询：聚焦排名和分布
            group_display = group_name_map.get(group_by, group_by)

            # 1. 整体概况
            if effective_avg_per_bus > 0:
                findings.append(
                    f"共 {record_count or len(top_data)} 个{group_display}，平均里程 {effective_avg_per_bus:.2f} km"
                    + (f"，总里程 {total:.2f} km" if total > 0 else "")
                )
            elif total > 0:
                findings.append(
                    f"共 {record_count or len(top_data)} 个{group_display}，总里程 {total:.2f} km"
                )

            # 2-3. 排名数据
            if len(top_data) >= 1:
                top = top_data[0]
                val_keys = [k for k in top.keys() if k != group_by]
                if val_keys:
                    val_key = val_keys[0]
                    name = top.get(group_by, "未知")
                    val = float(top.get(val_key, 0) or 0)
                    findings.append(f"{group_display}里程最高为 {name}，达到 {val:.2f} km")

                    if len(top_data) >= 2:
                        second = top_data[1]
                        second_val = float(second.get(val_key, 0) or 0)
                        second_name = second.get(group_by, "未知")
                        if val > 0 and second_val > 0:
                            diff_pct = (val - second_val) / val * 100
                            findings.append(f"头名 {name} 与第二名 {second_name} 差距为 {diff_pct:.1f}%")

            # 4. 效率评估
            if rate > 0:
                if rate >= 60:
                    findings.append(f"里程利用率 {rate:.1f}%，运营效率良好")
                elif rate >= 40:
                    findings.append(f"里程利用率 {rate:.1f}%，中等水平，有提升空间")
                else:
                    findings.append(f"里程利用率偏低（{rate:.1f}%），空驶占比高，存在优化空间")

            # 5. 改进建议
            if effective_avg_per_bus > 0:
                findings.append(f"建议关注里程偏低的{group_display}，分析原因并优化运营策略")
            if empty > 0 and rate < 50:
                findings.append(f"空驶里程 {empty:.1f} km 占比较大，建议优化派单策略降低空驶率")

        elif avg_daily > 0:
            findings.append(
                f"统计期间日均里程平均 {avg_daily:.2f} km/天"
                + (f"，覆盖 {days} 天" if days > 0 else "")
                + (f"，涉及 {buses} 辆车" if buses > 0 else "")
            )
        elif total > 0:
            avg_mileage_per_bus = total / buses if buses > 0 else 0
            avg_mileage_per_day = total / days if days > 0 else 0

            # 1. 运营规模概览
            findings.append(
                f"统计期间共 {buses} 辆车参与运营，覆盖 {days} 天，累计总里程 {total:.2f} km"
            )

            # 2. 日均和单车平均
            findings.append(
                f"日均运营里程 {avg_mileage_per_day:.1f} km/天，单车平均 {avg_mileage_per_bus:.1f} km/辆"
            )

            # 3. 里程结构分析
            if carry > 0:
                empty_rate = 100 - rate if rate > 0 else 0
                findings.append(
                    f"载客里程 {carry:.2f} km（占比{rate:.1f}%），空驶里程 {empty:.2f} km（占比{empty_rate:.1f}%）"
                )

            # 4. 效率评估
            if rate >= 60:
                findings.append(f"里程利用率 {rate:.1f}%，运营效率优秀，载客占比高")
            elif rate >= 40:
                findings.append(f"里程利用率 {rate:.1f}%，运营效率中等，建议优化线路调度减少空驶")
            else:
                findings.append(f"里程利用率偏低（{rate:.1f}%），空驶占比高，存在显著优化空间")

            # 5. 改进建议
            if rate < 50 and empty > 0:
                findings.append(f"空驶里程 {empty:.1f} km 占比较大，建议通过优化派单策略和线路规划降低空驶率")
            elif rate >= 50:
                findings.append("建议持续监控里程利用率趋势，结合订单密度优化车辆部署")

            # 6-7. 排名数据（分组查询时）
            if query_type == "grouped" and top_data and group_by:
                group_display = group_name_map.get(group_by, group_by)
                if len(top_data) >= 1:
                    top = top_data[0]
                    val_keys = [k for k in top.keys() if k != group_by]
                    mileage_keys = [k for k in val_keys if 'MILEAGE' in k.upper()]
                    val_key = mileage_keys[0] if mileage_keys else (val_keys[0] if val_keys else None)
                    if val_key:
                        name = top.get(group_by, "未知")
                        val = float(top.get(val_key, 0) or 0)
                        if 'AVG' in val_key.upper() or 'DAILY' in val_key.upper():
                            findings.append(f"{group_display}日均里程最高为 {name}，达到 {val:.2f} km/天")
                        else:
                            findings.append(f"{group_display}总里程最高为 {name}，达到 {val:.2f} km")

                        if len(top_data) >= 2:
                            second = top_data[1]
                            second_val = float(second.get(val_key, 0) or 0)
                            second_name = second.get(group_by, "未知")
                            if val > 0 and second_val > 0:
                                diff_pct = (val - second_val) / val * 100
                                findings.append(f"头名 {name} 与第二名 {second_name} 差距为 {diff_pct:.1f}%")

        return findings

    def _generate_operation_fallback(
        self,
        statistics: Dict[str, Any],
        query_type: str,
        group_by: Optional[str],
        top_data: Optional[List[Dict]]
    ) -> List[str]:
        """Operation 领域降级生成（目标 5-7 条）"""
        findings = []

        total = statistics.get("total_orders", 0)
        completed = statistics.get("completed_orders", 0)
        cancelled = statistics.get("cancelled_orders", 0)
        rate = statistics.get("completion_rate", 0)
        passengers = statistics.get("total_passengers", 0)
        avg_passengers = statistics.get("avg_passengers_per_order", 0)

        if total > 0:
            # 1. 订单规模
            findings.append(f"总订单数 {int(total)} 单，完成 {int(completed)} 单，取消 {int(cancelled)} 单")

            # 2. 完成率评估
            if rate >= 95:
                findings.append(f"订单完成率 {rate:.1f}%，服务质量优秀")
            elif rate >= 80:
                findings.append(f"订单完成率 {rate:.1f}%，服务质量良好")
            elif rate >= 60:
                findings.append(f"订单完成率 {rate:.1f}%，服务质量一般，建议关注取消原因")
            else:
                findings.append(f"订单完成率 {rate:.1f}% 偏低，取消率高达 {100-rate:.1f}%，需紧急排查")

            # 3. 取消分析
            if cancelled > 0 and total > 0:
                cancel_rate = cancelled / total * 100
                findings.append(f"取消订单 {int(cancelled)} 单，取消率 {cancel_rate:.1f}%，建议分析取消原因优化服务")

            # 4. 客流分析
            if passengers > 0:
                findings.append(f"服务乘客总数 {int(passengers)} 人，平均每单 {avg_passengers:.2f} 人")

            # 5. 效率总结
            if rate >= 80:
                findings.append("整体运营效率良好，建议保持现有调度策略并持续监控")
            elif rate >= 60:
                findings.append("运营效率有提升空间，建议优化派单策略和车辆调度")
            else:
                findings.append("运营效率偏低，建议重点排查取消原因并优化调度流程")

            # 6-7. 排名数据
            if query_type == "grouped" and top_data and group_by:
                if len(top_data) >= 1:
                    top = top_data[0]
                    name = top.get(group_by, "未知")
                    val_keys = [k for k in top.keys() if k != group_by]
                    if val_keys:
                        val = top.get(val_keys[0], 0)
                        findings.append(f"按 {group_by} 分组，表现最佳为 {name}（{val}）")
                if len(top_data) >= 2:
                    bottom = top_data[-1]
                    bottom_name = bottom.get(group_by, "未知")
                    bottom_val_keys = [k for k in bottom.keys() if k != group_by]
                    if bottom_val_keys:
                        findings.append(f"表现最低为 {bottom_name}（{bottom.get(bottom_val_keys[0], 0)}），建议关注")

        return findings


# 全局实例（供便捷使用）
_default_generator = None


def get_default_generator() -> KeyFindingsGenerator:
    """获取默认生成器实例"""
    global _default_generator
    if _default_generator is None:
        _default_generator = KeyFindingsGenerator()
    return _default_generator


async def generate_key_findings(
    data_summary: DataSummary,
    task_description: str = ""
) -> List[str]:
    """
    便捷函数：生成关键发现

    Args:
        data_summary: 统一格式的数据摘要
        task_description: 原始任务描述

    Returns:
        关键发现字符串列表
    """
    generator = get_default_generator()
    return await generator.generate(data_summary, task_description)


def generate_key_findings_sync(
    data_summary: DataSummary,
    task_description: str = ""
) -> List[str]:
    """
    同步便捷函数（用于非异步上下文降级）

    注意：此函数只使用规则化降级，不调用 LLM
    """
    generator = get_default_generator()
    domain = data_summary.get("domain", "")
    statistics = data_summary.get("statistics", {})
    query_type = data_summary.get("query_type", "aggregated")
    group_by = data_summary.get("group_by")
    top_data = data_summary.get("top_data")

    return generator.generate_fallback(domain, statistics, query_type, group_by, top_data)
