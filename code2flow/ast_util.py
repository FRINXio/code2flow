import ast
import contextlib
import os

from code2flow.model import Call, Function, Group, GroupType, OwnerConst, djoin


def make_file_group(file_ast: ast.Module, filename: str) -> Group:
    """Generate a file group with groups and functions.

    Args:
        file_ast (ast.Module): AST of a Python file.
        filename: Name of Python file.

    Returns:
        Group: File group.
    """

    subgroup_trees, function_trees, body_trees = separate_namespaces(file_ast)
    file_group = Group(
        token=os.path.split(filename)[-1].rsplit(".py", 1)[0],
        group_type=GroupType.file,
        import_tokens=file_import_tokens(filename),
        line_number=0,
        parent=None,
    )
    for function_tree in function_trees:
        new_function = make_function(function_tree, parent=file_group)
        if new_function is not None:
            file_group.add_function(new_function)

    for subgroup_tree in subgroup_trees:
        file_group.add_subgroup(make_class_group(subgroup_tree, parent=file_group))

    return file_group


def make_class_group(function_tree: ast.ClassDef, parent: Group):
    """Given an AST for the subgroup (a class), generate that subgroup and all
    the functions internal to the group."""
    subgroup_trees, function_trees, body_trees = separate_namespaces(function_tree)
    token = function_tree.name
    class_group = Group(
        token=function_tree.name,
        group_type=GroupType.cls,
        import_tokens=[djoin(parent.token, token)],
        line_number=function_tree.lineno,
        parent=parent,
    )

    for function_tree in function_trees:
        new_function = make_function(function_tree, parent=class_group)
        if new_function is not None:
            class_group.add_function(new_function)
    return class_group


def separate_namespaces(
    ast_tree: ast.Module | ast.stmt,
) -> (list[ast.stmt], list[ast.stmt], list[ast.stmt]):
    """Recursively separate AST into lists of ASTs for the groups, functions
    and bodies.

    Args:
        ast_tree (ast.Module | ast.stmt): AST tree.

    Returns:
        list[ast.stmt], list[ast.stmt], list[ast.stmt]: Tuple containing list of statements for
            groups, functions and bodies.
    """
    groups = []
    functions = []
    body = []
    for element in ast_tree.body:
        if type(element) in (ast.FunctionDef, ast.AsyncFunctionDef):
            functions.append(element)
        elif type(element) is ast.ClassDef:
            groups.append(element)
        elif getattr(element, "body", None):
            tup = separate_namespaces(element)
            groups += tup[0]
            functions += tup[1]
            body += tup[2]
        else:
            body.append(element)
    return groups, functions, body


def get_call_from_func_element(
    func: ast.Attribute | ast.Name | ast.Subscript | ast.Call,
) -> Call | None:
    """Given a python ast that represents a function call, clear and create
    generic Call object."""
    if type(func) is ast.Attribute:
        call_from = []
        val = func.value
        while True:
            if isinstance(val, ast.Name):
                with contextlib.suppress(AttributeError):
                    call_from.append(getattr(val, "attr", val.id))
            if isinstance(val, ast.Call):
                with contextlib.suppress(AttributeError):
                    call_from.append(getattr(val, "attr", val.func.id))
            val = getattr(val, "value", None)
            if not val:
                break
        if call_from:
            call_from = djoin(*reversed(call_from))
        else:
            call_from = OwnerConst.unknown_var
        return Call(token=func.attr, line_number=func.lineno, call_from=call_from)
    if type(func) is ast.Name:
        return Call(token=func.id, line_number=func.lineno)
    if type(func) in (ast.Subscript, ast.Call):
        return None


def make_calls(lines: list[ast.stmt]) -> list[Call]:
    """Given a list of lines, find all calls in this list.

    Args:
        lines (list[ast.stmt]): List of lines.

    Returns:
        list[Call]: List of calls in given list.
    """

    calls = []
    for expr in lines:
        for element in ast.walk(expr):
            if not isinstance(element, ast.Call):
                continue
            call = get_call_from_func_element(element.func)
            if call:
                calls.append(call)
    return calls


def get_ast(filename: str) -> ast.Module:
    """Get the entire AST for this file.

    Args:
        filename (str): Name of file.

    Returns:
        ast.Module: AST for file.
    """
    try:
        with open(filename) as f:
            raw = f.read()
    except ValueError:
        with open(filename, encoding="UTF-8") as f:
            raw = f.read()
    return ast.parse(raw)


def _find_task_function_name(element: ast.Call, element_func: ast.Attribute):
    """Get single "register" call from inside "start" function and extract the
    name of the task according to whether it is a new-style (xxx.register(cc))
    or old-style task (cc.register(...)).

    Args:
        element (ast.Call): Single "register" call from inside "start" function.

    Returns:
        str: Task name. In case of new-style tasks it's a class name (e.g. ClearUniconfigUrlCache)
        and in case of old-style tasks it's a function name (e.g. write_structured_data).
    """
    result_name = None
    if element_func.attr == "register":
        # Tasks written in "new-style"
        # E.g: xxx.register(cc)
        if len(element.args) == 1:
            arg_id = getattr(element.args[0], "id", None)
            if arg_id == "cc" or arg_id == "conductor":
                # Class name is added in this case
                result_name = getattr(element_func.value, "id", None)
        # Tasks written in "old-style"
        # E.g: cc.register(task_name, task_data, executor, ...)
        else:
            result_name = getattr(element.args[2], "id", None)
        return result_name


def add_tasks_to_group(function_definition: ast.FunctionDef | ast.stmt, parent: Group):
    """Get full function definition ("start" function), iterate it and get all
    task names from its body. Task names are added to parent (name of file /
    Class) list of tasks.

    Args:
        function_definition (ast.FunctionDef | ast.stmt): Function definition of "start" function.
        parent (Group): Name of file (old-style tasks) or name of class (new-style tasks).
    """
    for expr in function_definition.body:
        for element in ast.walk(expr):
            if not (isinstance(element, ast.Call) and isinstance(element.func, ast.Attribute)):
                continue
            task_name = _find_task_function_name(element, element.func)
            parent.tasks.append(task_name)


def make_function(function_definition: ast.FunctionDef | ast.stmt, parent: Group) -> Function:
    """Given an AST of all the lines, create the function along with the calls
    internal to it.

    Args:
        function_definition (ast.FunctionDef | ast.stmt): AST.
        parent: Group object.

    Returns:
        Function: Function object.
    """

    token = function_definition.name

    if token == "start":
        add_tasks_to_group(function_definition, parent)
    is_constructor = parent.group_type == GroupType.cls and token in ["__init__", "__new__"]
    import_tokens = []
    if parent.group_type == GroupType.file:
        import_tokens = [djoin(parent.token, token)]

    return Function(
        token=token,
        calls=make_calls(function_definition.body),
        parent=parent,
        arguments=[a.arg for a in function_definition.args.args],
        import_tokens=import_tokens,
        line_number=function_definition.lineno,
        is_constructor=is_constructor,
    )


def file_import_tokens(filename: str) -> list[str]:
    """Return the token(s) we would use if importing this file from another."""
    return [os.path.split(filename)[-1].rsplit(".py", 1)[0]]


def find_links(function_a: Function, all_functions: list[Function]):
    """Iterate through the calls on function_a to find everything the function
    links to.

    Args:
        function_a: Function object.
        all_functions: List of all functions.

    Returns:
        List of tuples of nodes and calls that were ambiguous.
    """

    links = []
    for call in function_a.calls:
        lfc = find_link_for_call(call, function_a, all_functions)
        assert not isinstance(lfc, Group)
        links.append(lfc)
    return list(filter(None, links))


def find_link_for_call(call: Call, function_a: Function, all_functions: list[Function]):
    """Given a call that happened on a function (function_a), return the
    function that the call links to and the call itself if >1 node matched."""

    possible_functions = []
    if call.is_attr():
        for function in all_functions:
            if function.parent.group_type == GroupType.cls:
                if call.token == function.token and call.call_from == function.parent.token:
                    possible_functions.append(function)
            else:
                if (
                    call.token == function.token
                    and function.parent != function_a.get_group()
                    and call.call_from == function.parent.token
                ):
                    possible_functions.append(function)
    else:
        for function in all_functions:
            if (
                call.token == function.token
                and isinstance(function.parent, Group)
                and function.parent.group_type == GroupType.file
            ):
                possible_functions.append(function)
            elif call.token == function.parent.token and function.is_constructor:
                possible_functions.append(function)

    if len(possible_functions) == 1:
        return possible_functions[0], None
    return (None, call) if len(possible_functions) > 1 else (None, None)
