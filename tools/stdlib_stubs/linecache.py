"""Minimal linecache stub for bare-metal PythonOS."""

cache = {}


def clearcache():
    cache.clear()


def getline(filename, lineno, module_globals=None):
    lines = getlines(filename, module_globals)
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1]
    return ''


def getlines(filename, module_globals=None):
    if filename in cache:
        return cache[filename]
    return []


def checkcache(filename=None):
    pass


def lazycache(filename, module_globals):
    pass


def updatecache(filename, module_globals=None):
    return []
