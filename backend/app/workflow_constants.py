from __future__ import annotations

# 后台表单启动的确定性 Worker 不依赖大模型。这个值只用于兼容旧的
# workflow_sessions 记录，不能被当作 model_connections 的主键查询。
BACKGROUND_MODEL_CONNECTION_ID = "platform-background-worker"
BACKGROUND_MODEL_PROVIDER = "platform"
BACKGROUND_MODEL_NAME = "后台 Skill Worker"


def is_background_model_connection(connection_id: str | None) -> bool:
    return not connection_id or connection_id == BACKGROUND_MODEL_CONNECTION_ID
