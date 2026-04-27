def iscoroutine(obj):
    """Return True if obj is a native coroutine object (created by async def)."""
    return hasattr(obj, 'cr_await')
