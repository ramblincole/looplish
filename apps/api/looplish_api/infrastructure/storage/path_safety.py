from pathlib import Path


def ensure_within(root: Path, target: Path) -> Path:
    # resolve() 同时折叠 `..` 并解析现有符号链接，再比较真实父子关系。
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_target == resolved_root or resolved_root not in resolved_target.parents:
        raise ValueError("path escapes configured root")
    return resolved_target
