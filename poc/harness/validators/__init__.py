"""Validator registry: app_name -> validator class."""

from .a1_validator import A1Validator
from .a2_validator import A2Validator
from .a3_validator import A3Validator
from .a4_validator import A4Validator
from .a5_validator import A5Validator
from .a6_validator import A6Validator

VALIDATOR_REGISTRY: dict[str, type] = {
    "a1_simple_script": A1Validator,
    "a2_dependencies": A2Validator,
    "a3_modular": A3Validator,
    "a4_server": A4Validator,
    "a5_configurable": A5Validator,
    "a6_problematic": A6Validator,
}


def get_validator(app_name: str):
    """Return a validator instance for the given app name."""
    cls = VALIDATOR_REGISTRY.get(app_name)
    if cls is None:
        raise ValueError(
            f"No validator for app '{app_name}'. Available: {list(VALIDATOR_REGISTRY)}"
        )
    return cls()
