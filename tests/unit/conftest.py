"""
Isolated conftest for unit tests — prevents the top-level conftest from loading
internal.core packages that require optional dependencies (pydantic_settings).
"""
# No imports from internal.core here; each test imports only what it needs.
