"""Calculator — safe math expression evaluation."""
import math
import re


def _safe_eval(expr: str) -> str:
    allowed = {
        "abs": abs, "round": round, "int": int, "float": float,
        "min": min, "max": max, "sum": sum,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "asin": math.asin, "acos": math.acos, "atan": math.atan,
        "log": math.log, "log10": math.log10, "log2": math.log2,
        "sqrt": math.sqrt, "pow": pow,
        "pi": math.pi, "e": math.e, "tau": math.tau,
        "radians": math.radians, "degrees": math.degrees,
        "floor": math.floor, "ceil": math.ceil,
        "factorial": math.factorial,
    }
    allowed_names = {**allowed}

    clean = re.sub(r"[^0-9a-zA-Z_.,+\-*/()%^ \t]", "", expr)
    clean = clean.replace("^", "**")
    clean = clean.replace("x", "*")

    try:
        result = eval(clean, {"__builtins__": {}}, allowed_names)
        if isinstance(result, float):
            if result == int(result):
                return str(int(result))
            return f"{result:.6f}".rstrip("0").rstrip(".")
        return str(result)
    except ZeroDivisionError:
        return "Error: division by zero"
    except SyntaxError as e:
        return f"Error: invalid syntax ({e})"
    except Exception as e:
        return f"Error: {e}"


def calculator(parameters=None, player=None, **kwargs) -> str:
    params = parameters or {}
    expression = params.get("expression", "").strip()
    if not expression:
        return "No expression provided. Usage: calculator with expression='2 + 2'"

    result = _safe_eval(expression)
    return f"{expression} = {result}"
