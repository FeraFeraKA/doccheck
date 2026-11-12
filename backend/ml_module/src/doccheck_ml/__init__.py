"""Worker-callable identity processing; importing this package loads no model."""

from .api import DocumentInput, InputError, process_documents

__version__ = "0.1.0"
__all__ = ["DocumentInput", "InputError", "process_documents"]
