from enum import Enum


class WorkflowState(str, Enum):

    IDLE = "idle"                  # 空闲
    RUNNING = "running"            # 执行中
    WAITING_INPUT = "waiting_input"  # 等待用户补参数
    SUCCESS = "success"            # 成功
    FAILED = "failed"              # 失败