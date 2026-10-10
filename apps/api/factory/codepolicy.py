"""Static policy for builder-written tool code. Standard library only: the sandbox image copies this file.

This policy is defence in depth and a review aid. It is NOT the security boundary. The boundary is the
sandbox container: no network, no secrets, no host disk, resource limits, and capability calls that the
worker performs on the code's behalf. Assume a determined author can defeat any in-language restriction.
"""

import ast
import hashlib

MAX_CODE_CHARS = 20_000
MAX_NODES = 6_000

# Curated names per module. The runner exposes only these, never the real module object, so a tool cannot
# walk from an allowed module to `sys` or `os` through a module attribute.
SAFE_MODULES = {
    "json": ("loads", "dumps"),
    "re": (
        "compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split", "escape",
        "IGNORECASE", "MULTILINE", "DOTALL", "VERBOSE", "ASCII", "I", "M", "S", "X", "A",
    ),
    "math": (
        "ceil", "floor", "trunc", "sqrt", "pow", "log", "log10", "log2", "exp", "fabs", "fsum", "gcd", "isfinite",
        "isnan", "isinf", "isclose", "copysign", "fmod", "modf", "hypot", "pi", "e", "inf", "nan", "prod", "comb",
    ),
    "decimal": (
        "Decimal", "InvalidOperation", "ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_HALF_DOWN", "ROUND_CEILING",
        "ROUND_FLOOR", "ROUND_DOWN", "ROUND_UP",
    ),
    "fractions": ("Fraction",),
    "datetime": ("date", "datetime", "time", "timedelta", "timezone"),
    "statistics": ("mean", "fmean", "median", "pstdev", "stdev", "pvariance", "variance"),
    "itertools": (
        "chain", "groupby", "islice", "accumulate", "zip_longest", "product", "permutations", "combinations",
        "repeat", "count", "takewhile", "dropwhile", "starmap", "pairwise",
    ),
    "functools": ("reduce", "partial"),
    "collections": ("Counter", "defaultdict", "OrderedDict", "deque"),
    "string": ("ascii_letters", "ascii_lowercase", "ascii_uppercase", "digits", "punctuation", "whitespace"),
    "unicodedata": ("normalize", "category"),
    "operator": ("itemgetter", "add", "sub", "mul", "truediv", "floordiv", "mod", "neg", "eq", "ne", "lt", "le", "gt", "ge"),
}  # fmt: skip

SAFE_BUILTINS = (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "frozenset", "int",
    "isinstance", "iter", "len", "list", "map", "max", "min", "next", "range", "repr", "reversed", "round",
    "set", "slice", "sorted", "str", "sum", "tuple", "zip", "True", "False", "None",
    "Exception", "ValueError", "KeyError", "TypeError", "IndexError", "ZeroDivisionError", "ArithmeticError",
    "LookupError", "StopIteration", "AssertionError", "OverflowError",
)  # fmt: skip

# Attribute names that reach interpreter internals without a leading underscore.
FORBIDDEN_ATTRIBUTES = {
    "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "cr_await", "ag_frame", "ag_code",
    "f_back", "f_builtins", "f_code", "f_globals", "f_locals", "f_trace", "tb_frame", "tb_next",
    "co_consts", "co_code", "co_names", "format", "format_map", "mro", "with_traceback",
}  # fmt: skip

FORBIDDEN_NODES = (
    ast.ClassDef, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith, ast.Await, ast.Global, ast.Nonlocal,
    ast.With, ast.Yield, ast.YieldFrom, ast.Delete,
)  # fmt: skip


class CodePolicyError(ValueError):
    """Tool code breaks the static policy. The message is safe to show to the author."""


def code_hash(code):
    return hashlib.sha256(code.encode()).hexdigest()


def check(code):
    """Parse and validate tool code. Returns the AST so the runner can compile exactly what was checked."""
    if not isinstance(code, str) or not code.strip():
        raise CodePolicyError("Tool code is empty")
    if len(code) > MAX_CODE_CHARS:
        raise CodePolicyError(f"Tool code exceeds {MAX_CODE_CHARS} characters")
    try:
        tree = ast.parse(code, mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        raise CodePolicyError(f"Tool code does not parse: {type(error).__name__}") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise CodePolicyError("Tool code is too complex")
    for node in nodes:
        if isinstance(node, FORBIDDEN_NODES):
            raise CodePolicyError(f"{type(node).__name__} is not allowed in tool code")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in SAFE_MODULES:
                    raise CodePolicyError(f"Import of {alias.name} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in SAFE_MODULES:
                raise CodePolicyError(f"Import from {node.module} is not allowed")
            for alias in node.names:
                if alias.name not in SAFE_MODULES[node.module]:
                    raise CodePolicyError(f"{node.module}.{alias.name} is not available to tool code")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in FORBIDDEN_ATTRIBUTES:
                raise CodePolicyError(f"Attribute {node.attr} is not allowed")
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                raise CodePolicyError(f"Name {node.id} is not allowed")
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            raise CodePolicyError("A bare except is not allowed; name the exception")
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list:
                raise CodePolicyError("Decorators are not allowed in tool code")
            if node.name.startswith("__"):
                raise CodePolicyError(f"Function name {node.name} is not allowed")
        elif isinstance(node, ast.arg) and node.arg.startswith("__"):
            raise CodePolicyError(f"Argument {node.arg} is not allowed")
        elif isinstance(node, ast.keyword) and node.arg and node.arg.startswith("__"):
            raise CodePolicyError(f"Keyword {node.arg} is not allowed")
    entry = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run"]
    if len(entry) != 1:
        raise CodePolicyError("Tool code must define exactly one top-level function run(input, call)")
    arguments = entry[0].args
    names = [argument.arg for argument in arguments.args]
    if names != ["input", "call"] or arguments.vararg or arguments.kwarg or arguments.kwonlyargs or arguments.defaults:
        raise CodePolicyError("The entry point must be run(input, call)")
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.Expr)):
            raise CodePolicyError("Only imports, constants and functions are allowed at module level")
        if isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
            raise CodePolicyError("Module-level statements may not run code")
    return tree
