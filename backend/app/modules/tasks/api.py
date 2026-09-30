"""Exported service interface — the only allowed synchronous cross-module entry into ``tasks``
(other modules import THIS, never internals). Cross-module reaction is preferred via events
(``task.completed`` is the seam the future points-ledger slice subscribes to)."""

from app.modules.tasks.service import (
    activate_on_item_checked,
    complete_instance,
    count_open_tasks,
    create_armed_task,
    create_instance,
    create_personal_task,
    create_template,
    delete_template,
    get_instance,
    get_template,
    instance_status,
    list_instances,
    list_templates,
    reassign_instance,
    release_assignments_of,
    update_template,
)

__all__ = [
    "activate_on_item_checked",
    "complete_instance",
    "count_open_tasks",
    "create_armed_task",
    "create_instance",
    "create_personal_task",
    "create_template",
    "delete_template",
    "get_instance",
    "get_template",
    "instance_status",
    "list_instances",
    "list_templates",
    "reassign_instance",
    "release_assignments_of",
    "update_template",
]
