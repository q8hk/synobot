from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Iterable


class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


@dataclass(frozen=True)
class AuthorizationPolicy:
    """Resolve a Telegram user to the least-privileged configured role."""

    administrators: FrozenSet[int]
    operators: FrozenSet[int] = frozenset()
    viewers: FrozenSet[int] = frozenset()
    allow_group_chats: bool = False

    @classmethod
    def create(
        cls,
        administrators: Iterable[int],
        operators: Iterable[int] = (),
        viewers: Iterable[int] = (),
        allow_group_chats: bool = False,
    ) -> "AuthorizationPolicy":
        return cls(
            administrators=frozenset(administrators),
            operators=frozenset(operators),
            viewers=frozenset(viewers),
            allow_group_chats=allow_group_chats,
        )

    def role_for(self, user_id: int, chat_type: str = "private") -> Role:
        if chat_type != "private" and not self.allow_group_chats:
            raise PermissionError("group chats are disabled")
        if user_id in self.administrators:
            return Role.ADMIN
        if user_id in self.operators:
            return Role.OPERATOR
        if user_id in self.viewers:
            return Role.VIEWER
        raise PermissionError("Telegram user is not authorized")

    def require(self, user_id: int, minimum: Role, chat_type: str = "private") -> Role:
        role = self.role_for(user_id, chat_type)
        rank = {Role.VIEWER: 1, Role.OPERATOR: 2, Role.ADMIN: 3}
        if rank[role] < rank[minimum]:
            raise PermissionError("Telegram user lacks the required role")
        return role
