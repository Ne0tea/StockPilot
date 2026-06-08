import re
from importlib.metadata import requires, version


def _parse_version(raw: str) -> tuple[int, ...]:
    parts = []
    for token in re.split(r"[.+-]", raw):
        if token.isdigit():
            parts.append(int(token))
        else:
            break
    return tuple(parts)


def _compare_versions(left: str, right: str) -> int:
    left_parts = _parse_version(left)
    right_parts = _parse_version(right)
    size = max(len(left_parts), len(right_parts))
    left_parts += (0,) * (size - len(left_parts))
    right_parts += (0,) * (size - len(right_parts))
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


def _extract_constraints(requirement_lines: list[str] | None, package_name: str) -> list[str]:
    if not requirement_lines:
        return []

    prefix = package_name.lower()
    for line in requirement_lines:
        candidate = line.split(";", 1)[0].strip()
        if not candidate.lower().startswith(prefix):
            continue
        suffix = candidate[len(package_name):].strip()
        return [item.strip() for item in suffix.split(",") if item.strip()]
    return []


def _matches_constraint(installed_version: str, constraint: str) -> bool:
    match = re.match(r"(<=|>=|==|!=|<|>)(.+)", constraint)
    if not match:
        return True

    operator, expected_version = match.groups()
    comparison = _compare_versions(installed_version, expected_version.strip())
    if operator == "<":
        return comparison < 0
    if operator == "<=":
        return comparison <= 0
    if operator == ">":
        return comparison > 0
    if operator == ">=":
        return comparison >= 0
    if operator == "==":
        return comparison == 0
    if operator == "!=":
        return comparison != 0
    return True


def assert_runtime_dependencies():
    fastapi_version = version("fastapi")
    starlette_version = version("starlette")
    constraints = _extract_constraints(requires("fastapi"), "starlette")
    if constraints and all(_matches_constraint(starlette_version, item) for item in constraints):
        return

    required_range = ",".join(constraints) or "the version required by fastapi"
    raise RuntimeError(
        "Incompatible FastAPI/Starlette installation detected: "
        f"fastapi {fastapi_version} requires starlette {required_range}, "
        f"but starlette {starlette_version} is installed. "
        "Run `pip install -r backend/requirements.txt` or install a compatible "
        "Starlette version before starting the backend."
    )
