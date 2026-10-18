"""Helpers that reproduce JavaScript number rules.

Express coerces request fields with ``Number()`` and renders money with
``toLocaleString("en-IN")``. The write routes need the same rules so the
validation branches and error messages stay identical.

JavaScript has a single number type and ``JSON.stringify(5.0) === "5"``, so
whole values are returned as ``int`` here to keep Python's JSON output the
same as Node's.
"""

import math


def js_number(value):
    """Reproduce ``Number(value)`` for JSON input (str, number, bool, null)."""
    if value is None:
        number = 0.0
    elif isinstance(value, bool):
        number = 1.0 if value else 0.0
    elif isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if text == "":
            number = 0.0
        else:
            try:
                number = float(text)
            except ValueError:
                number = float("nan")
    else:
        number = float("nan")

    if math.isfinite(number) and number.is_integer():
        return int(number)
    return number


def js_number_or_zero(value):
    """Reproduce ``Number(value) || 0`` (NaN and 0 both become 0)."""
    number = js_number(value)
    return 0 if is_falsy_number(number) else number


def is_falsy_number(value):
    """JavaScript truthiness for a Number: 0 and NaN are falsy."""
    if value == 0:
        return True
    return isinstance(value, float) and math.isnan(value)


def is_whole_number(value):
    """Reproduce ``Number.isInteger`` for a coerced number (Infinity is not)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value) and value.is_integer()


def number_text(value):
    """Render a number the way ``String(value)`` does: 5.0 -> "5"."""
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if value.is_integer():
            return str(int(value))
    return str(value)


def format_inr(value):
    """Reproduce ``Number.prototype.toLocaleString("en-IN")``.

    Indian grouping (last three digits, then pairs) with 0-3 fraction digits.
    """
    text = f"{round(value, 3):.3f}".rstrip("0").rstrip(".")
    sign = ""
    if text.startswith("-"):
        sign, text = "-", text[1:]
    integer, _, fraction = text.partition(".")
    if len(integer) > 3:
        head, tail = integer[:-3], integer[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        integer = ",".join(groups + [tail])
    return sign + integer + ("." + fraction if fraction else "")
