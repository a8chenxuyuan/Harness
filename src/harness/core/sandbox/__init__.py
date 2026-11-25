"""sandbox —— Phase 20 沙箱隔离。

实现：
    - Sandbox（协议）：run_cmd / teardown
    - ProcessSandbox（默认实现）：subprocess + 资源配额 + 路径白名单 + 独立临时目录
    - DockerSandbox（可选）：container 内执行；未装 docker 库 → graceful 降级

铁律：越界路径 / 超时 / 超额全部拦截，主进程不受影响。
"""

from .base import Sandbox, SandboxPolicy
from .process import ProcessSandbox

__all__ = ["Sandbox", "SandboxPolicy", "ProcessSandbox"]
