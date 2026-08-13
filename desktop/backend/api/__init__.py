from .assets import router as assets_router
from .modules import router as modules_router
from .projects import router as projects_router
from .tasks import router as tasks_router

__all__ = ["assets_router", "modules_router", "projects_router", "tasks_router"]
