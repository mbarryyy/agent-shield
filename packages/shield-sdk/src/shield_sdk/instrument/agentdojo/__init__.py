"""AgentDojo Shield elements (W2): ShieldGuard / ShieldedToolsExecutor /
ShieldRecorder + the shared ShieldElementConfig and the build factory.

Code-verified against the pinned AgentDojo rev 18b501a:
``tool_execution.py`` (:75-96 skip-and-synthesize precedent, :103 money-line,
:130-132/:154-155 ToolsExecutionLoop), ``base_pipeline_element.py``,
``functions_runtime.py`` (FunctionCall.args is a MutableMapping),
``types.py`` (ChatToolResultMessage).
"""

from .elements import (
    ShieldedToolsExecutor,
    ShieldElementConfig,
    ShieldGuard,
    ShieldRecorder,
    build_shield_elements,
)

__all__ = [
    "ShieldElementConfig",
    "ShieldGuard",
    "ShieldRecorder",
    "ShieldedToolsExecutor",
    "build_shield_elements",
]
