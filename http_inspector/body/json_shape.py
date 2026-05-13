from __future__ import annotations


def infer_shape(value, depth: int = 0, max_depth: int = 3) -> str:
    if isinstance(value, dict):
        if depth >= max_depth:
            return "{...}"
        if not value:
            return "{}"
        parts = []
        for k, v in list(value.items())[:10]:
            parts.append(f"{k}: {infer_shape(v, depth + 1, max_depth)}")
        if len(value) > 10:
            parts.append(f"... +{len(value) - 10} more")
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, list):
        if not value:
            return "array[]"
        elem = infer_shape(value[0], depth + 1, max_depth)
        return f"array[{len(value)}] → {elem}"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return "any"


def extract_json_summary(
    data,
    max_array_items: int = 5,
    max_depth: int = 3,
) -> tuple[str, list | None, int | None]:
    """
    Returns (shape_str, sample_records_or_None, total_array_len_or_None).
    sample_records is set when the top-level value is an array.
    """
    shape = infer_shape(data, max_depth=max_depth)
    if isinstance(data, list):
        sample = data[:max_array_items]
        return shape, sample, len(data)
    # Object that wraps a list (common API pattern: {"items": [...], "total": N})
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, list) and len(val) > 0:
                sample = val[:max_array_items]
                return shape, sample, len(val)
    return shape, None, None
