import argparse
import ast
import json
import logging
import os
from collections import defaultdict

from code2flow import ast_util
from model import CallConnection
from model import Function
from model import Group

logger = logging.getLogger()

def get_source_files(paths: list[str]) -> list[str]:
    """Filter and return only Python source files from given list of files or
    directories.

    Args:
        paths (list[str]): List of paths (files or directories).

    Returns:
        list[str]: List of Python files in specified paths.
    """
    logger.info("Searching for Python source files...")
    source_files = []
    for path in paths:
        if os.path.isfile(path):
            source_files.append(path)
            continue
        for root, _, files in os.walk(path):
            source_files.extend(os.path.join(root, file) for file in files)

    python_source_files = [file for file in source_files if file.endswith(".py")]
    logger.info("Found %d Python source files in given paths.", len(python_source_files))
    for source_file in python_source_files:
        logger.info("File: %s", source_file)

    if not python_source_files:
        logger.warning("There are no Python files to process in given paths.")

    return python_source_files


def get_asts(source_files: list[str], skip_parse_errors: bool = False) -> list[(str, ast.Module)]:
    """Take a list of Python source files and parse AST for each source file.

    Args:
        source_files (list[str]): List of Python source files.
        skip_parse_errors (bool, optional): If an AST parser fails to parse a file, skip it.
            Default is False.

    Returns:
        list[(str, ast.Module)]: List of tuples which contain source filename and its AST
            (for each file).
    """
    asts = []
    logger.info("Reading/parsing AST for each Python file.")
    for source_file in source_files:
        try:
            asts.append((source_file, ast_util.get_ast(source_file)))
        except Exception as e:
            if skip_parse_errors:
                logger.warning(f"Could not parse {source_file}. Skipping it.")
            else:
                raise e
    return asts


def find_groups_and_functions(asts: list[(str, ast.Module)]) -> list[Group]:
    """Find "groups" (modules and classes) and functions in given ASTs.

    Args:
        asts list[(str, ast.Module)]: List of tuples which contain source
            filename and its AST (for each file).

    Returns:
        list[Group]: List of Groups.
    """
    logger.info("Finding groups and functions in ASTs...")
    file_groups = []
    for source_file, file_ast in asts:
        file_group = ast_util.make_file_group(file_ast, source_file)
        file_groups.append(file_group)
    return file_groups


def _create_call_connection(function_1: Function, function_2: Function) -> CallConnection:
    """Create a connection between two functions.

    Args:
        function_1: First function in call connection.
        function_2: Second function in call connection.

    Returns:
        CallConnection: New CallConnection between two functions.
    """
    return CallConnection(function_1, function_2)


def find_all_connections(groups: list[Group]) -> list[CallConnection]:
    """Find all connections between functions.

    Args:
        groups (list[Group]): List of Groups.

    Returns:
        list[CallConnection]: List of CallConnections.
    """
    logger.info("Finding all connections between functions...")
    all_functions = ast_util.flatten([g.get_all_functions() for g in groups])
    connections = []
    for function_a in list(all_functions):
        links = ast_util.find_links(function_a, all_functions)
        connections.extend(
            _create_call_connection(function_a, function_b) for function_b, _ in links if function_b
        )
    return connections


def find_direct_tasks_calls(function_calls: list[CallConnection]) -> dict[str, defaultdict]:
    """Find direct (task_1 -> task_2) tasks calls.

    Args:
        function_calls (list[CallConnection]): List of all functions calls connections.

    Returns:
        dict[str, defaultdict]: Dictionary which contains direct
            calls between tasks for each Python file.

        E.g.
            {
              "direct_calls": {
                "vlan_worker": [
                  "vlan_worker::allocate_l3_vlan_from_region ->
                   vlan_worker::allocate_vlan_from_region"
                ],
              }
            }
    """
    logger.info("Finding direct tasks calls...")
    result = {"direct_calls": defaultdict(list[str])}
    for call in function_calls:
        parent_filename = call.function_1.get_parent_filename()
        if call.function_1.is_task() and call.function_2.is_task():
            if str(call) not in result["direct_calls"][parent_filename]:
                result["direct_calls"][parent_filename].append(str(call))
    return result


def _find_connection(call: CallConnection, filtered_connections: list[CallConnection]):
    """Find possible connection.

    Algorithm: If there is a connection between function_x1 -> function_x2
    and function_y1 -> function_y2 AND there is a connection between
    function_x2 -> function_y1, there is possible connection function_x1 ->
    function_y2.

    Args:
        call (CallConnection): Connection between two functions.
        filtered_connections (list[CallConnection]): Connections in which one function is a task.

    Returns:
        (str, Function, Function): Tuple which contains parent group and functions
            which will be used to create a connection.
    """
    if call.function_1.is_task():
        for other_call in filtered_connections:
            if call.function_2 is other_call.function_1:
                parent_filename = call.function_1.get_parent_filename()
                return parent_filename, call.function_1, other_call.function_2

    if call.function_2.is_task():
        for other_call in filtered_connections:
            if call.function_1 is other_call.function_2:
                parent_filename = other_call.function_1.get_parent_filename()
                return parent_filename, other_call.function_1, call.function_2
    return None


def find_possible_tasks_calls(function_calls: list[CallConnection]) -> dict[str, defaultdict]:
    """Find possible tasks calls.

    E.g.: If task_1 -> function_x and function_x -> task_2, then there is
    a connection task_1 -> task_2.

    Args:
        function_calls (list[CallConnection]): List of all functions calls connections.

    Returns:
        dict[str, defaultdict]: Dictionary which contains possible
            calls between tasks (for each Python file).

        E.g:
            {
              "possible_calls": {
                "pe_worker": [
                  "pe_worker::purge_evpn -> uniconfig_worker::delete_structured_data"
                ]
              }
            }
    """
    logger.info("Finding possible tasks calls...")
    filtered_connections = []
    possible_calls = {"possible_calls": defaultdict(list[str])}

    # filter function calls connections in which one function is a task
    for call in function_calls:
        if call.function_1.is_task() and call.function_2.is_task():
            continue  # since we already have it  (find_direct_calls)
        if call.function_1.is_task() or call.function_2.is_task():
            filtered_connections.append(call)

    for call in filtered_connections:
        possible_connection = _find_connection(call, filtered_connections)
        if possible_connection is not None:
            parent_file, function_1, function_2 = possible_connection
            new_connection = _create_call_connection(function_1, function_2)
            if str(new_connection) not in possible_calls["possible_calls"][parent_file]:
                possible_calls["possible_calls"][parent_file].append(str(new_connection))

    return possible_calls


def tasks_calls_finder(paths: list[str], skip_parse_errors: bool = False) -> dict[str, defaultdict]:
    """Find a tasks which call each other.

    Args:
        paths (list[str]): List of paths (path can be file or directory).
        skip_parse_errors (bool, optional): If an AST parser fails to parse a file,
            skip it. Default is False.

    Returns:
        dict[str, defaultdict]: Dictionary of direct and possible function calls.

        E.g.:
            {
              "direct_calls": {
                "vlan_worker": [
                  "vlan_worker::allocate_l3_vlan_from_region ->
                   vlan_worker::allocate_vlan_from_region"
                ],

              },
              "possible_calls": {
                "pe_worker": [
                  "pe_worker::purge_evpn -> uniconfig_worker::delete_structured_data"
                ]
              }
            }
    """
    logger.info("Checking paths: %s", paths)
    # Get Python files from paths
    python_source_files = get_source_files(paths)
    # Get AST for each Python file
    ast_trees = get_asts(python_source_files, skip_parse_errors)
    # Get file groups (files and classes) and functions
    file_groups = find_groups_and_functions(ast_trees)
    # Get all connections between functions calls
    calls_connections = find_all_connections(file_groups)
    # Get direct tasks calls
    direct_calls = dict(find_direct_tasks_calls(calls_connections))
    # Get possible tasks calls
    possible_calls = dict(find_possible_tasks_calls(calls_connections))

    return direct_calls | possible_calls


def main():
    parser = argparse.ArgumentParser(
        prog="Tasks calls finder", description="Tool to find tasks which call other tasks."
    )
    parser.add_argument("paths", help="Files or directories to search in.", nargs="+")
    parser.add_argument("--quiet", "-q", help="Supress INFO logging.", action="store_true")
    parser.add_argument(
        "--skip-parse-errors",
        help="Skip files that the language parser fails on.",
        action="store_true",
    )

    args = parser.parse_args()
    logging_level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(
        level=logging_level,
        format="[%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()],
    )

    calls_between_tasks = tasks_calls_finder(args.paths)
    logger.info("Script finished!\n")
    return json.dumps(calls_between_tasks)


if __name__ == "__main__":
    print(main())
