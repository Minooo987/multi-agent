"""
Validation Module - 结果验证与修正系统
"""

from .result_validator import (
    ResultValidator,
    ResultFixer,
    ValidationResult,
    ValidationIssue,
    ValidationSeverity,
    validate_and_fix_result,
    generate_key_findings_from_stats
)

__all__ = [
    "ResultValidator",
    "ResultFixer",
    "ValidationResult",
    "ValidationIssue",
    "ValidationSeverity",
    "validate_and_fix_result",
    "generate_key_findings_from_stats"
]
