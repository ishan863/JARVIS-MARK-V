import json
from pathlib import Path

import polars as pl


def data_pipeline(parameters: dict, player=None, **kwargs) -> str:
    action = parameters.get("action", "load").strip().lower()
    source = parameters.get("source", "").strip()
    output = parameters.get("output", "").strip()
    steps = parameters.get("steps", "")
    schema_desc = parameters.get("schema_desc", "")
    instruction = parameters.get("instruction", "").strip()

    try:
        if action == "load":
            return _load_data(source)
        elif action == "clean":
            return _clean_data(source, steps)
        elif action == "transform":
            return _transform_data(source, instruction, output)
        elif action == "validate":
            return _validate_data(source, schema_desc)
        elif action == "analyze":
            return _analyze_data(source)
        elif action == "convert":
            format_to = parameters.get("format", "csv").strip().lower()
            return _convert_data(source, output or source, format_to)
        elif action == "describe":
            return _describe_columns(source)
        else:
            return f"Unknown action: {action}. Use: load, clean, transform, validate, analyze, convert, describe"
    except Exception as e:
        return f"Data pipeline failed: {e}"


def _load_df(source: str) -> pl.DataFrame:
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pl.read_csv(source, infer_schema_length=10000)
    elif suffix in (".xlsx", ".xls"):
        try:
            return pl.read_excel(source, sheet_id=0)
        except Exception:
            import pandas as pd
            return pl.from_pandas(pd.read_excel(source, sheet_name=0))
    elif suffix == ".json":
        return pl.read_json(source)
    elif suffix == ".parquet":
        return pl.read_parquet(source)
    elif suffix == ".tsv":
        return pl.read_csv(source, separator="\t", infer_schema_length=10000)
    else:
        raise ValueError(f"Unsupported format: {suffix}")


def _load_data(source: str) -> str:
    df = _load_df(source)
    preview = df.head(10).to_pandas().to_string()
    dtypes = {str(c): str(df[c].dtype) for c in df.columns}
    return (
        f"Loaded {source}\n"
        f"Shape: {df.shape[0]} rows x {df.shape[1]} columns\n"
        f"Columns: {', '.join(df.columns)}\n"
        f"Dtypes: {dtypes}\n"
        f"\nPreview:\n{preview}"
    )


def _clean_data(source: str, steps: str) -> str:
    df = _load_df(source)

    result = df.unique()
    total_null = int(result.null_count().sum_horizontal().sum())
    result = result.drop_nulls()

    return (
        f"Cleaned {source}\n"
        f"Original: {df.shape[0]} rows, {df.shape[1]} cols\n"
        f"After de-dup: {result.shape[0]} rows\n"
        f"Removed {df.shape[0] - result.shape[0]} total rows"
    )


def _transform_data(source: str, instruction: str, output: str) -> str:
    if not instruction:
        return "No transformation instruction provided."

    df = _load_df(source)
    context = {
        "columns": list(df.columns),
        "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        "shape": list(df.shape),
        "sample": df.head(3).to_pandas().to_dict(orient="records"),
    }

    from core.model_router import router

    prompt = f"""Given a DataFrame with:
Columns: {context['columns']}
Dtypes: {context['dtypes']}
Shape: {context['shape']}

Write Python code using polars (import polars as pl) to transform it:
{instruction}

The variable `df` contains the loaded DataFrame.
Return ONLY the Python code to produce the result. No markdown."""

    try:
        code = router.smart_route(prompt, task_type="code_gen").strip()
        import re
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        local_vars = {"df": df, "pl": pl}
        exec(code, {"pl": pl, "pd": __import__("pandas")}, local_vars)
        result = local_vars.get("result", local_vars.get("df", df))

        if output:
            if isinstance(result, pl.DataFrame):
                if output.endswith(".csv"):
                    result.write_csv(output)
                elif output.endswith(".xlsx"):
                    result.write_excel(output)
                elif output.endswith(".parquet"):
                    result.write_parquet(output)
                else:
                    result.write_csv(output)
            return f"Transformed result saved: {output} ({result.shape[0]} rows)"
        else:
            preview = result.head(10).to_pandas().to_string() if hasattr(result, "head") else str(result)[:1000]
            return f"Transformation result:\n{preview}"

    except Exception as e:
        return f"AI transformation failed: {e}"


def _validate_data(source: str, schema_desc: str) -> str:
    df = _load_df(source)

    if not schema_desc:
        nulls = df.null_count()
        total_nulls = nulls.sum_horizontal().sum()
        stats = df.describe()
        return (
            f"Basic validation of {source}:\n"
            f"Rows: {df.shape[0]}, Columns: {df.shape[1]}\n"
            f"Total null values: {total_nulls}\n"
            f"Unique values per column:\n"
            + "\n".join(f"  {c}: {df[c].n_unique()}" for c in df.columns[:20])
        )

    try:
        import pandera as pa
        from pandera.typing import DataFrame

        schema = pa.DataFrameSchema({
            col: pa.Column(pa.String) for col in df.columns
        })
        try:
            schema.validate(df, lazy=True)
            return f"Validation passed for {source} ({df.shape[0]} rows)"
        except pa.errors.SchemaErrors as e:
            return f"Validation errors:\n{e}"
    except ImportError:
        return f"pandera not installed. Skipping schema validation."


def _analyze_data(source: str) -> str:
    df = _load_df(source)
    description = df.describe()
    nulls = df.null_count()
    sample = df.head(5)
    return (
        f"Analysis of {source}:\n"
        f"Shape: {df.shape[0]} rows x {df.shape[1]} columns\n"
        f"Columns: {', '.join(df.columns)}\n"
        f"Null counts:\n{nulls.to_pandas().to_string()}\n"
        f"Stats:\n{description.to_pandas().to_string()}\n"
        f"Sample:\n{sample.to_pandas().to_string()}"
    )


def _convert_data(source: str, output: str, format_to: str) -> str:
    df = _load_df(source)
    out_path = Path(output)

    if format_to == "csv":
        out = out_path.with_suffix(".csv")
        df.write_csv(str(out))
    elif format_to == "parquet":
        out = out_path.with_suffix(".parquet")
        df.write_parquet(str(out))
    elif format_to == "json":
        out = out_path.with_suffix(".json")
        df.write_json(str(out))
    elif format_to == "xlsx":
        out = out_path.with_suffix(".xlsx")
        try:
            df.write_excel(str(out))
        except Exception:
            df.write_csv(str(out.with_suffix(".csv")))
            return f"Excel not available, saved as CSV: {out.with_suffix('.csv')}"
    else:
        return f"Unsupported target format: {format_to}"

    return f"Converted {source} → {out} ({df.shape[0]} rows)"


def _describe_columns(source: str) -> str:
    df = _load_df(source)
    lines = []
    for col in df.columns:
        dtype = df[col].dtype
        unique = df[col].n_unique()
        nulls = df[col].null_count()
        sample_vals = df[col].drop_nulls().head(3).to_list()
        lines.append(
            f"  {col} ({dtype}): {unique} unique, {nulls} nulls, "
            f"e.g. {sample_vals[:3]}"
        )
    return f"Column details for {source}:\n" + "\n".join(lines)
