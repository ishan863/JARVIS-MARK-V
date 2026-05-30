from pathlib import Path


def excel_report(parameters: dict, player=None, **kwargs) -> str:
    action = parameters.get("action", "create").strip().lower()
    output_path = parameters.get("output_path", "").strip()
    data_source = parameters.get("data_source", "").strip()
    sheet_name = parameters.get("sheet_name", "Report")
    title = parameters.get("title", "")

    if not output_path:
        output_path = str(Path.home() / "Desktop" / "report.xlsx")

    try:
        if action == "create":
            return _create_report(parameters, output_path)
        elif action == "pivot":
            return _create_pivot(parameters, output_path)
        elif action == "chart":
            return _add_chart(parameters, output_path)
        elif action == "formula":
            return _evaluate_formula(parameters)
        elif action == "live":
            return _live_excel(parameters)
        else:
            return f"Unknown action: {action}. Use: create, pivot, chart, formula, live"
    except Exception as e:
        return f"Excel report failed: {e}"


def _create_report(params: dict, output_path: str) -> str:
    sheet_name = params.get("sheet_name", "Report")
    title = params.get("title", "Report")
    headers = params.get("headers", [])
    rows = params.get("rows", [])
    auto_filter = params.get("auto_filter", True)
    column_widths = params.get("column_widths", None)
    conditional_format = params.get("conditional_format", None)

    import xlsxwriter

    workbook = xlsxwriter.Workbook(output_path)

    title_fmt = workbook.add_format({"bold": True, "font_size": 16, "font_color": "#1a1a1a"})
    header_fmt = workbook.add_format({
        "bold": True, "bg_color": "#4472C4", "font_color": "white",
        "border": 1, "text_wrap": True, "valign": "vcenter", "align": "center",
    })
    cell_fmt = workbook.add_format({"border": 1, "valign": "vcenter"})
    money_fmt = workbook.add_format({"border": 1, "num_format": "$#,##0.00", "valign": "vcenter"})
    pct_fmt = workbook.add_format({"border": 1, "num_format": "0.00%", "valign": "vcenter"})

    ws = workbook.add_worksheet(sheet_name)

    if title:
        ws.merge_range(0, 0, 0, max(len(headers) - 1, 0), title, title_fmt)
        ws.set_row(0, 30)
        start_row = 2
    else:
        start_row = 0

    if column_widths:
        for i, w in enumerate(column_widths):
            ws.set_column(i, i, w)
    else:
        ws.set_column(0, max(len(headers) - 1, 0), 18)

    if headers:
        for col, h in enumerate(headers):
            ws.write(start_row, col, h, header_fmt)
        start_row += 1

    for r, row_data in enumerate(rows):
        for c, val in enumerate(row_data):
            fmt = money_fmt if isinstance(val, float) else cell_fmt
            ws.write(start_row + r, c, val, fmt)

    data_end_row = start_row + len(rows) - 1 if rows else start_row - 1

    if auto_filter and headers:
        ws.autofilter(start_row - 1, 0, data_end_row, len(headers) - 1)

    if conditional_format and headers:
        ws.conditional_format(
            start_row, 0, data_end_row, len(headers) - 1,
            {"type": "data_bar", "bar_color": "#4472C4"}
        )

    workbook.close()
    return f"Excel report created: {output_path} ({len(rows)} rows)"


def _create_pivot(params: dict, output_path: str) -> str:
    import pandas as pd
    import xlsxwriter

    data_source = params.get("data_source", "")
    sheet_name = params.get("sheet_name", "Report")
    pivot_sheet = params.get("pivot_sheet", "Pivot")
    index = params.get("index", [])
    columns = params.get("columns", [])
    values = params.get("values", [])
    aggfunc = params.get("aggfunc", "sum")
    chart_type = params.get("chart_type", "")

    if not data_source or not Path(data_source).exists():
        return f"Data source not found: {data_source}"

    if data_source.endswith(".csv"):
        df = pd.read_csv(data_source)
    elif data_source.endswith((".xlsx", ".xls")):
        df = pd.read_excel(data_source, sheet_name=0)
    else:
        return f"Unsupported format: {data_source}"

    writer = pd.ExcelWriter(output_path, engine="xlsxwriter")

    df.to_excel(writer, sheet_name=sheet_name, index=False)
    ws = writer.sheets[sheet_name]
    ws.autofilter(0, 0, len(df), len(df.columns) - 1)

    if index and values:
        pivot = pd.pivot_table(
            df,
            index=index,
            columns=columns if columns else None,
            values=values,
            aggfunc=aggfunc,
            fill_value=0,
        )
        pivot.to_excel(writer, sheet_name=pivot_sheet)

        if chart_type:
            chart_types = {
                "bar": "column",
                "line": "line",
                "pie": "pie",
                "area": "area",
                "doughnut": "doughnut",
            }
            ct = chart_types.get(chart_type, "column")
            chart = writer.book.add_chart({"type": ct})
            chart.add_series({
                "name": values[0] if isinstance(values, list) else values,
                "categories": [pivot_sheet, 1, 0, len(pivot), 0],
                "values": [pivot_sheet, 1, 1, len(pivot), 1],
            })
            chart.set_title({"name": f"{values} by {index}"})
            writer.sheets[pivot_sheet].insert_chart("E2", chart)

    writer.close()
    return f"Pivot report created: {output_path} ({len(df)} rows, pivot: {index} x {values})"


def _add_chart(params: dict, output_path: str) -> str:
    import xlsxwriter

    sheet = params.get("sheet", "Sheet1")
    chart_type = params.get("chart_type", "column")
    title = params.get("title", "Chart")
    categories_range = params.get("categories", "")
    values_range = params.get("values", "")

    chart_types = {
        "bar": "bar", "column": "column", "line": "line",
        "pie": "pie", "area": "area", "scatter": "scatter",
        "doughnut": "doughnut", "radar": "radar",
    }
    ct = chart_types.get(chart_type, "column")

    workbook = xlsxwriter.Workbook(output_path)
    ws = workbook.add_worksheet(sheet)
    chart = workbook.add_chart({"type": ct})
    chart.add_series({
        "name": title,
        "categories": categories_range,
        "values": values_range,
    })
    chart.set_title({"name": title})
    ws.insert_chart("B2", chart)
    workbook.close()
    return f"Chart added to: {output_path}"


def _evaluate_formula(params: dict) -> str:
    expression = params.get("expression", "").strip()
    context = params.get("context", "").strip()

    if not expression:
        return "No formula expression provided."

    try:
        from formulas import excel
        func = excel.Formula(expression)
        result = func()
        return f"Formula result: {result}"
    except Exception as e:
        return f"Formula evaluation failed: {e}"


def _live_excel(params: dict) -> str:
    action = params.get("action", "read").strip().lower()
    file_path = params.get("file_path", "").strip()
    sheet = params.get("sheet", "Sheet1")
    cell = params.get("cell", "A1")
    value = params.get("value", "")

    if not file_path or not Path(file_path).exists():
        return f"File not found: {file_path}"

    try:
        import xlwings as xw
        app = xw.App(visible=False)
        wb = app.books.open(file_path)
        ws = wb.sheets[sheet]

        if action == "read":
            result = str(ws.range(cell).value)
            wb.close()
            app.quit()
            return f"{cell} = {result}"

        elif action == "write":
            ws.range(cell).value = value
            wb.save()
            wb.close()
            app.quit()
            return f"Written {value} to {cell}"

        elif action == "formula":
            ws.range(cell).formula = value
            wb.save()
            wb.close()
            app.quit()
            return f"Formula set in {cell}: {value}"

        elif action == "read_table":
            data = ws.used_range.value
            wb.close()
            app.quit()
            if isinstance(data, list):
                return f"Read {len(data)} rows x {len(data[0]) if data else 0} cols"
            return f"Read cell: {data}"

        wb.close()
        app.quit()
        return f"Unknown live Excel action: {action}"

    except Exception as e:
        return f"Live Excel failed: {e}. xlwings requires Excel installed."
