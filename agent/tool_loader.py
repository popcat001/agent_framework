"""
tool_loader.py - Discovers and loads tools from Python files in tools/ directory.

Tools are discovered from .py files that define a __tools__ list.
Each function named in __tools__ is converted to a Claude tool schema
using the convert_to_claude_tool function pattern.
"""

import importlib.util
import inspect
import sys
import types
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Union


class ToolCollisionError(Exception):
    """Raised when two tool dirs define a function with the same name.

    Defined as its own class so the broad ``except Exception`` blocks inside
    ``ToolLoader._load_module`` (which mask single-tool conversion errors)
    can re-raise it without swallowing the failure. Tool collisions are
    fatal: they indicate a configuration mistake the user must fix.
    """


def convert_to_claude_tool(func: Callable) -> Dict[str, Any]:
    """Convert Python function to Claude tool schema.

    Args:
        func: Python function with type hints and docstring

    Returns:
        Dict with Claude tool schema (name, description, input_schema)
    """
    sig = inspect.signature(func)
    doc = inspect.getdoc(func) or ""

    actual_params = set(sig.parameters.keys()) - {'self', 'cls'}

    # Parse docstring for parameter descriptions
    param_descriptions = {}
    if "Args:" in doc:
        args_section = doc.split("Args:")[1]
        for end_marker in ["Returns:", "Raises:"]:
            if end_marker in args_section:
                args_section = args_section.split(end_marker)[0]

        lines = args_section.split("\n")
        current_param = None
        current_desc_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if ":" in stripped:
                potential_param = stripped.split(":")[0].strip()
                if potential_param in actual_params:
                    if current_param:
                        param_descriptions[current_param] = " ".join(current_desc_lines)
                    current_param = potential_param
                    current_desc_lines = [stripped.split(":", 1)[1].strip()]
                    continue

            if current_param:
                current_desc_lines.append(stripped)

        if current_param:
            param_descriptions[current_param] = " ".join(current_desc_lines)

    # Build input schema
    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ['self', 'cls']:
            continue

        param_type = "string"
        items_schema = None

        if param.annotation != inspect.Parameter.empty:
            ann = param.annotation

            # Unwrap Optional[X] / Union[..., List[...], ...] — pick the first
            # list-bearing branch if any, otherwise the first non-NoneType branch.
            # Handles both typing.Union (e.g. Optional[X]) and PEP 604 X | Y.
            origin = getattr(ann, '__origin__', None)
            if origin is Union or isinstance(ann, getattr(types, 'UnionType', ())):
                non_none = [a for a in ann.__args__ if a is not type(None)]
                list_branch = next(
                    (a for a in non_none if getattr(a, '__origin__', None) is list),
                    None,
                )
                ann = list_branch or (non_none[0] if non_none else ann)

            if ann in [int, float]:
                param_type = "number"
            elif ann == bool:
                param_type = "boolean"
            elif ann == list:
                # bare `list` annotation (no item type info)
                param_type = "array"
            elif ann == dict:
                # bare `dict` annotation (no key/value type info)
                param_type = "object"
            elif hasattr(ann, '__origin__'):
                if ann.__origin__ == list:
                    param_type = "array"
                    if hasattr(ann, '__args__') and ann.__args__:
                        item_type = ann.__args__[0]
                        if item_type == str:
                            items_schema = {"type": "string"}
                        elif item_type in [int, float]:
                            items_schema = {"type": "number"}
                        elif item_type == bool:
                            items_schema = {"type": "boolean"}
                elif ann.__origin__ == dict:
                    param_type = "object"

        prop = {
            "type": param_type,
            "description": param_descriptions.get(param_name, f"Parameter {param_name}")
        }
        if items_schema:
            prop["items"] = items_schema
        if param_type == "object":
            # Let Claude send arbitrary key/value pairs. Without this, some Claude
            # models serialize object-typed args as JSON strings, which breaks handlers.
            prop["additionalProperties"] = True

        properties[param_name] = prop

        if param.default == inspect.Parameter.empty:
            required.append(param_name)

    description = doc.split("\n\n")[0].strip() if doc else f"Function {func.__name__}"

    return {
        "name": func.__name__,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required
        }
    }


class ToolLoader:
    """Discovers and loads tools from Python files in a tools directory.

    Tool files should define a __tools__ list containing function names to export.
    Example:
        __tools__ = ['my_function', 'another_function']
    """

    def __init__(self, tools_dir: Path | Iterable[Path]):
        if isinstance(tools_dir, (str, Path)):
            self.tools_dirs: List[Path] = [Path(tools_dir)]
        else:
            self.tools_dirs = [Path(d) for d in tools_dir]
        self.schemas: List[Dict[str, Any]] = []
        self.handlers: Dict[str, Callable] = {}
        self._load_all()

    def _load_all(self):
        """Discover and load all tools from each tools directory."""
        for d in self.tools_dirs:
            if not d.exists():
                print(f"[ToolLoader] Tools directory not found: {d}")
                continue
            py_files = [
                f for f in d.glob("*.py")
                if f.name != "__init__.py"
            ]
            for py_file in py_files:
                self._load_module(py_file, d)

    def _load_module(self, py_file: Path, tools_dir: Path):
        """Load tools from a single Python file."""
        module_name = f"tools.{py_file.stem}"

        try:
            # Add tools directory to path for imports
            tools_dir_str = str(tools_dir)
            if tools_dir_str not in sys.path:
                sys.path.insert(0, tools_dir_str)

            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                print(f"[ToolLoader] Could not load spec for {py_file}")
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Check for __tools__ list
            tools_list = getattr(module, "__tools__", None)
            if tools_list is None:
                print(f"[ToolLoader] No __tools__ list in {py_file.name}, skipping")
                return

            # Load each function in __tools__
            for func_name in tools_list:
                func = getattr(module, func_name, None)
                if func is None:
                    print(f"[ToolLoader] Function '{func_name}' not found in {py_file.name}")
                    continue
                if not callable(func):
                    print(f"[ToolLoader] '{func_name}' in {py_file.name} is not callable")
                    continue

                # Collision check is *outside* the conversion try below so a
                # duplicate tool-name across tool dirs aborts startup. The
                # conversion try only catches schema-generation errors for a
                # single function, which we treat as non-fatal.
                if func_name in self.handlers:
                    raise ToolCollisionError(
                        f"Tool name collision: '{func_name}' defined in "
                        f"multiple tool dirs. Each tool name must be unique."
                    )
                try:
                    schema = convert_to_claude_tool(func)
                    self.schemas.append(schema)
                    self.handlers[func_name] = func
                    print(f"[ToolLoader] Loaded tool: {func_name}")
                except Exception as e:
                    print(f"[ToolLoader] Error converting {func_name}: {e}")

        except ToolCollisionError:
            # Configuration mistake — surface and abort startup rather than
            # silently dropping one of the duplicates.
            raise
        except Exception as e:
            print(f"[ToolLoader] Error loading {py_file.name}: {e}")

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Return list of Claude tool schemas."""
        return self.schemas

    def get_handlers(self) -> Dict[str, Callable]:
        """Return dict mapping tool names to callables."""
        return self.handlers
