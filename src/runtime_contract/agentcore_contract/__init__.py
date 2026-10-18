"""Pure connection data shared by runtime publishers and terminal clients."""

from .connection import (
    ConnectionSpec,
    UserError,
    decode_cdk_outputs,
    decode_descriptor,
    encode_descriptor,
    plain_text,
    validate_command,
)

__all__ = [
    "ConnectionSpec",
    "UserError",
    "decode_descriptor",
    "decode_cdk_outputs",
    "encode_descriptor",
    "plain_text",
    "validate_command",
]
__version__ = "0.1.0"
