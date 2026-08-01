"""Argument binding — payload → command signature.

Rules (see design doc §3):
- Basic types: exact match via cattrs, no implicit cross-type conversion.
- dataclass / TypedDict / nested structures: structured unboxing via cattrs.
- Parameters annotated ``BridgeContext`` (any name): system-injected.
- strict=True (default): extra payload keys are rejected.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, get_type_hints

from cattrs import Converter
from cattrs.errors import ClassValidationError, StructureHandlerNotFoundError

from lumiview._scope import BridgeContext, BridgeError, Command

if TYPE_CHECKING:
    from lumiview._window import Window

INJECTED_TYPES = {BridgeContext}

_converter = Converter(forbid_extra_keys=True)


# cattrs structures basic types via their constructors (int("3") == 3),
# which would silently coerce — register exact-match hooks instead.
def _strict_scalar(value: Any, typ: type) -> Any:
    if type(value) is typ:
        return value
    raise StructureHandlerNotFoundError(repr(value), typ)


for _t in (str, int, float, bool):
    _converter.register_structure_hook(_t, _strict_scalar)


def bind_arguments(
    cmd: Command,
    payload: Any,
    window: "Window | None",
) -> dict[str, Any]:
    """Bind *payload* to *cmd*'s signature; returns kwargs for ``fn(**kw)``.

    Raises BridgeError("invalid_argument") on any binding failure.
    """
    if not isinstance(payload, dict):
        raise BridgeError(
            "invalid_argument", f"Payload must be an object, got {type(payload).__name__}"
        )

    try:
        hints = get_type_hints(cmd.fn)
    except (NameError, TypeError):
        hints = {}

    sig = inspect.signature(cmd.fn)
    bound: dict[str, Any] = {}
    has_regular_params = False

    for param in sig.parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue  # *args / **kwargs are not supported
        annotation = hints.get(param.name, param.annotation)

        if annotation in INJECTED_TYPES:
            bound[param.name] = BridgeContext(
                window=window,  # type: ignore[arg-type]
                payload=payload,
                command=cmd.full_name,
                scope=cmd.scope,
            )
            continue

        has_regular_params = True
        if param.name not in payload:
            if param.default is inspect.Parameter.empty:
                raise BridgeError(
                    "invalid_argument",
                    f"Missing required argument {param.name!r}",
                )
            continue  # use the Python default

        try:
            bound[param.name] = _converter.structure(
                payload[param.name], annotation
            )
        except (StructureHandlerNotFoundError, ClassValidationError) as exc:
            raise BridgeError(
                "invalid_argument",
                f"Invalid argument {param.name!r}: {exc}",
            ) from exc

    if cmd.strict and has_regular_params:
        injected_names = {
            p.name
            for p in sig.parameters.values()
            if hints.get(p.name, p.annotation) in INJECTED_TYPES
        }
        legal = set(sig.parameters) - injected_names
        extra = set(payload) - legal
        if extra:
            raise BridgeError(
                "invalid_argument",
                "Unexpected argument(s): " + ", ".join(sorted(extra)),
            )

    return bound
