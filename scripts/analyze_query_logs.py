"""
查询日志分析脚本
每周运行一次，分析失败模式并生成改进建议
"""

import json
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timedelta


def analyze_logs(log_dir: str = "logs/queries"):
    """分析查询日志"""
    log_dir = Path(log_dir)

    # 读取最近7天的日志
    all_logs = []
    for file_path in log_dir.glob("*.jsonl"):
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                log = json.loads(line)
                log_time = datetime.fromisoformat(log["timestamp"])
                if log_time > datetime.now() - timedelta(days=7):
                    all_logs.append(log)

    print(f"分析 {len(all_logs)} 条查询日志（最近7天）")

    # 统计失败模式
    failure_logs = [l for l in all_logs if not l["success"] or l.get("user_feedback")]
    print(f"失败/反馈: {len(failure_logs)} 条")

    # 按模板统计成功率
    template_stats = defaultdict(lambda: {"total": 0, "success": 0})
    for log in all_logs:
        template = log.get("template_used") or "llm_freeform"
        template_stats[template]["total"] += 1
        if log["success"]:
            template_stats[template]["success"] += 1

    print("\n模板成功率:")
    for template, stats in sorted(template_stats.items(), key=lambda x: x[1]["total"], reverse=True):
        rate = stats["success"] / stats["total"] * 100
        print(f"  {template}: {rate:.1f}% ({stats['success']}/{stats['total']})")

    # 生成改进建议
    suggestions = []

    # 1. 如果 LLM 自由生成的失败率高，增加模板覆盖
    llm_stats = template_stats.get("llm_freeform", {"total": 0, "success": 0})
    if llm_stats["total"] > 10 and llm_stats["success"] / llm_stats["total"] < 0.8:
        suggestions.append("LLM 自由生成成功率低于80%，建议增加模板覆盖")

    # 2. 分析用户反馈关键词
    feedback_keywords = Counter()
    for log in all_logs:
        feedback = log.get("user_feedback", "")
        if "不对" in feedback or "错误" in feedback:
            # 提取关键词
            if "平均" in feedback:
                feedback_keywords["avg_semantic_error"] += 1
            if "日期" in feedback:
                feedback_keywords["date_error"] += 1

    if feedback_keywords:
        print("\n用户反馈问题分布:")
        for keyword, count in feedback_keywords.most_common():
            print(f"  {keyword}: {count}")

    # 输出报告
    report = {
        "analysis_date": datetime.now().isoformat(),
        "period_days": 7,
        "total_queries": len(all_logs),
        "failure_count": len(failure_logs),
        "template_stats": dict(template_stats),
        "feedback_keywords": dict(feedback_keywords),
        "suggestions": suggestions
    }

    # 保存报告
    report_path = Path("logs/reports") / f"query_analysis_{datetime.now().strftime('%Y%m%d')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n报告已保存: {report_path}")
    return report


if __name__ == "__main__":
    analyze_logs()
