"""
配置验证
"""

import sys
from config.settings import settings
from tools.mcp_oracle import oracle_mcp
from utils import logger


def validate_config():
    """验证配置"""
    errors = []
    warnings = []

    # 检查 Oracle 配置
    if not settings.oracle_user or settings.oracle_user == 'your_username':
        errors.append("ORACLE_USER 未配置")

    if not settings.oracle_password or settings.oracle_password == 'your_password':
        errors.append("ORACLE_PASSWORD 未配置")

    if not settings.oracle_host:
        errors.append("ORACLE_HOST 未配置")

    # 检查模型配置
    if not settings.model_api_key or settings.model_api_key == 'your_dashscope_api_key':
        errors.append("MODEL_API_KEY 未配置")

    if not settings.model_base_url:
        errors.append("MODEL_BASE_URL 未配置")

    # 打印结果
    if errors:
        logger.error("配置验证失败:")
        for error in errors:
            logger.error(f"  ❌ {error}")
        return False

    if warnings:
        logger.warning("配置警告:")
        for warning in warnings:
            logger.warning(f"  ⚠️ {warning}")

    logger.info("✅ 配置验证通过")
    return True


async def test_connections():
    """测试连接"""
    logger.info("测试 Oracle 连接...")

    try:
        result = await oracle_mcp.test_connection()
        if result.get('success'):
            logger.info(f"✅ Oracle 连接成功: {result.get('database_version', 'Unknown')}")
            return True
        else:
            logger.error(f"❌ Oracle 连接失败: {result.get('error')}")
            return False
    except Exception as e:
        logger.error(f"❌ Oracle 连接异常: {e}")
        return False


if __name__ == "__main__":
    if not validate_config():
        sys.exit(1)

    import asyncio
    success = asyncio.run(test_connections())
    sys.exit(0 if success else 1)
