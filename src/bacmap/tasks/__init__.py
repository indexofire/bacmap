"""任务层（ADR-06/07）：封闭任务类型 · 状态机 · 门 · 审批。

对外入口：
- TaskType/TaskState/TaskStatus/Approval/TaskEngine —— spec
- 门框架与四道门注册表 —— gates
- DBOS 默认实现 —— bacmap.tasks.engine.dbos_engine.DbosTaskEngine
"""

from bacmap.tasks.spec import (
    APPROVALS_DDL,
    TASKS_DDL,
    Approval,
    TaskEngine,
    TaskId,
    TaskState,
    TaskStatus,
    TaskType,
)

__all__ = [
    "APPROVALS_DDL",
    "TASKS_DDL",
    "Approval",
    "TaskEngine",
    "TaskId",
    "TaskState",
    "TaskStatus",
    "TaskType",
]
