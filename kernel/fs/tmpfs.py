"""
kernel.fs.tmpfs — In-memory filesystem.

First filesystem mounted at /. Used for /dev, /tmp, /proc.
All data lives in Python dicts + bytearrays; survives only until power-off.
"""


from dataclasses import dataclass, field
from kernel.fs.vfs import FSNode, Filesystem, Stat, InodeType


class TmpfsNode:
    def __init__(self, inode_type: InodeType, mode: int = 0o644) -> None:
        self.inode_type = inode_type
        self.mode       = mode
        self._data:     bytearray = bytearray()
        self._children: dict[str, "TmpfsNode"] = {}

    async def stat(self) -> Stat:
        return Stat(
            inode_type=self.inode_type,
            size=len(self._data),
            mode=self.mode,
            nlink=1 + len(self._children) if self.inode_type == InodeType.DIR else 1,
        )

    async def read(self, offset: int, n: int) -> bytes:
        if self.inode_type != InodeType.FILE:
            raise IsADirectoryError
        return bytes(self._data[offset:offset + n])

    async def write(self, offset: int, data: bytes) -> int:
        if self.inode_type != InodeType.FILE:
            raise IsADirectoryError
        end = offset + len(data)
        if end > len(self._data):
            self._data.extend(b'\x00' * (end - len(self._data)))
        self._data[offset:end] = data
        return len(data)

    async def truncate(self, size: int = 0) -> None:
        if self.inode_type != InodeType.FILE:
            raise IsADirectoryError
        self._data = self._data[:size]

    async def readdir(self) -> list[str]:
        if self.inode_type != InodeType.DIR:
            raise NotADirectoryError
        return ['.', '..'] + list(self._children.keys())

    async def lookup(self, name: str) -> "TmpfsNode":
        if name in ('.', ''):
            return self
        if name not in self._children:
            raise FileNotFoundError(name)
        return self._children[name]

    async def create(self, name: str, inode_type: InodeType) -> "TmpfsNode":
        if self.inode_type != InodeType.DIR:
            raise NotADirectoryError
        node = TmpfsNode(inode_type)
        self._children[name] = node
        return node

    async def unlink(self, name: str) -> None:
        if name not in self._children:
            raise FileNotFoundError(name)
        del self._children[name]


class TmpFS:
    def __init__(self) -> None:
        self._root = TmpfsNode(InodeType.DIR, mode=0o755)

    def root(self) -> TmpfsNode:
        return self._root

    def seed(self, tree: dict) -> None:
        """Convenience: populate from a dict tree (nested dicts = dirs, bytes = files)."""
        self._seed_node(self._root, tree)

    def _seed_node(self, node: TmpfsNode, tree: dict) -> None:
        for name, val in tree.items():
            if isinstance(val, dict):
                child = TmpfsNode(InodeType.DIR, mode=0o755)
                node._children[name] = child
                self._seed_node(child, val)
            elif isinstance(val, (bytes, bytearray)):
                child = TmpfsNode(InodeType.FILE)
                child._data = bytearray(val)
                node._children[name] = child
            elif isinstance(val, str):
                child = TmpfsNode(InodeType.FILE)
                child._data = bytearray(val.encode())
                node._children[name] = child
