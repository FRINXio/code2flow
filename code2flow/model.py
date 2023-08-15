from enum import StrEnum


def flatten(list_of_lists: list[list[any]]) -> list[any]:
    """Return a list from a list of lists."""
    return [el for sublist in list_of_lists for el in sublist]


def djoin(*tup):
    """Convenience method to join strings with dots."""
    if len(tup) == 1 and isinstance(tup[0], list):
        return ".".join(tup[0])
    return ".".join(tup)


class OwnerConst(StrEnum):
    unknown_var = "UNKNOWN_VAR"
    unknown_module = "UNKNOWN_MODULE"


class GroupType(StrEnum):
    file = "FILE"
    cls = "CLASS"
    namespace = "NAMESPACE"


class Call:
    """Represent function call expression.

    It can be an attribute call like object.do_something() or a "naked"
    call like do_something().
    """

    def __init__(
        self, token: str, line_number: int | None = None, call_from: str | None = None
    ) -> None:
        self.token = token
        self.call_from = call_from
        self.line_number = line_number

    def __repr__(self) -> str:
        return f"<Call from={self.call_from} token={self.token}>"

    def to_string(self) -> str:
        """Return a representation of the call."""
        if self.call_from:
            return f"{self.call_from}.{self.token}()"
        return f"{self.token}()"

    def is_attr(self) -> bool:
        """Attribute calls are like `a.do_something()` rather than
        `do_something()`"""
        return self.call_from is not None


class Function:
    """Represent function within a module."""

    def __init__(
        self,
        token: str,
        calls: list[Call],
        parent,
        arguments: list[str] | None = None,
        import_tokens: list[str] | None = None,
        line_number: int | None = None,
        is_constructor: bool = False,
    ) -> None:
        self.token = token
        self.calls = calls
        self.parent = parent
        self.arguments = arguments or []
        self.import_tokens = import_tokens or []
        self.line_number = line_number
        self.is_constructor = is_constructor

    def __repr__(self) -> str:
        return f"<Function token={self.token} parent={self.parent}>"

    def get_function_name(self) -> str:
        """Return full function name (together with file name)."""
        return f"{self.get_first_group().get_filename()}::{self.get_token_with_ownership()}"

    def get_first_group(self):
        """Get the first group that contains this function."""
        parent = self.parent
        while not isinstance(parent, Group):
            parent = parent.parent
        return parent

    def get_group(self):
        """Get the group that this function is in."""
        parent = self.parent
        return parent

    def is_attr(self) -> bool:
        """Return whether this function is attached to something besides the
        file."""
        return (
            self.parent
            and isinstance(self.parent, Group)
            and self.parent.group_type in (GroupType.cls, GroupType.namespace)
        )

    def get_token_with_ownership(self) -> str:
        """Return token which includes what group this is a part of."""
        return djoin(self.parent.token, self.token) if self.is_attr() else self.token

    def is_task(self, all_tasks: set) -> bool:
        """Return whether this function is a task."""
        if self.parent.group_type == GroupType.cls and self.token not in [
            "execute",
            "provision",
            "reconcile",
            "purge",
        ]:
            return False
        return (self.token in all_tasks) or (self.parent.token in all_tasks)

    def is_special_task(self, all_tasks: set) -> bool:
        """Return whether this function is a "special" task.

        Special tasks are execute, provision, reconcile and purge.
        """
        if (
            self.token in ["execute", "provision", "reconcile", "purge"]
            and self.parent.group_type == GroupType.cls
        ):
            return self.parent.token in all_tasks

    def get_parent_filename(self):
        """Return parent filename."""
        if self.parent.group_type == GroupType.cls:
            return self.parent.parent.token
        else:
            return self.parent.token


class CallConnection:
    """Represent connection between two function calls."""

    def __init__(self, function_1: Function, function_2: Function) -> None:
        self.function_1 = function_1
        self.function_2 = function_2

    def __repr__(self) -> str:
        return f"{self.function_1.get_function_name()} -> {self.function_2.get_function_name()}"


class Group:
    """Represent namespaces (classes and modules/files)."""

    def __init__(self, token, group_type, import_tokens=None, line_number=None, parent=None):
        self.token = token
        self.line_number = line_number
        self.functions = []
        self.subgroups = []
        self.parent = parent
        self.group_type = group_type
        self.import_tokens = import_tokens or []
        self.tasks = []

    def __repr__(self) -> str:
        return f"<Group token={self.token} type={self.group_type}>"

    def get_filename(self) -> str:
        """Get file name of a group."""
        if self.group_type == GroupType.file:
            return self.token
        return self.parent.get_filename()

    def add_function(self, function: Function) -> None:
        """Add function to a group."""
        self.functions.append(function)

    def add_subgroup(self, sg):
        """Add subgroup to a group."""
        self.subgroups.append(sg)

    def get_all_groups(self):
        """Get list of groups that are part of this group + all subgroups."""
        ret = [self]
        for subgroup in self.subgroups:
            ret += subgroup.get_all_groups()
        return ret

    def get_all_functions(self) -> list[Function]:
        """Get list of functions that are part of this group + all
        subgroups."""
        ret = list(self.functions)
        for subgroup in self.subgroups:
            ret += subgroup.get_all_functions()
        return ret
