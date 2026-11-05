class ValidationError(ValueError):
    """Invalid plugin configuration or pipeline structure."""


class ExecutionError(RuntimeError):
    """An execution failure with the responsible node attached."""

    def __init__(self, node_id: str, plugin_id: str, cause: Exception, partial_result=None):
        self.node_id = node_id
        self.plugin_id = plugin_id
        self.partial_result = partial_result
        super().__init__(f"节点 {node_id} ({plugin_id}) 执行失败：{cause}")
