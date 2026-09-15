# How ADCS Eliminates API Hallucinations: Aspose.Cells

> Cell values, styling, pivot tables — the API surface is huge. AI assistants guess wrong without documentation access.

## The Problem

Aspose.Cells for .NET has a rich API with specific patterns for cell access, styling, and data manipulation. AI assistants commonly generate code using intuitive-but-wrong property names that don't match the actual API.

## Real Example: Excel Read/Write with Formatting

We asked an AI assistant to build a .NET console app that reads Excel data, applies formatting, creates formulas, and adds conditional formatting.

---

### Hallucination #1: Setting Cell Values

The most common Aspose.Cells hallucination — using direct property assignment instead of the actual method:

```csharp
// WITHOUT MCP — does not compile
worksheet.Cells["A1"].Value = "Product Name";
worksheet.Cells["B1"].Value = 29.99;
worksheet.Cells["C1"].Value = DateTime.Now;
```

```csharp
// WITH MCP — correct method call
worksheet.Cells["A1"].PutValue("Product Name");
worksheet.Cells["B1"].PutValue(29.99);
worksheet.Cells["C1"].PutValue(DateTime.Now);
```

`cell.Value` is a read-only accessor in some contexts. The correct write method is `PutValue()`, which handles type detection and formatting automatically. ADCS returned this from the `Cell` symbol documentation.

---

### Hallucination #2: Styling Pattern

AI models often generate a simplified styling API that doesn't exist:

```csharp
// WITHOUT MCP — wrong styling approach
worksheet.Cells["A1"].Font.Bold = true;
worksheet.Cells["A1"].Font.Size = 14;
worksheet.Cells["A1"].BackgroundColor = Color.LightBlue;
worksheet.Cells["A1"].Borders.LineStyle = CellBorderType.Thin;
```

The Cells API uses a **get-modify-set pattern** for styles — you can't modify cell formatting directly:

```csharp
// WITH MCP — correct get/modify/set pattern
Style style = worksheet.Cells["A1"].GetStyle();
style.Font.IsBold = true;
style.Font.Size = 14;
style.ForegroundColor = Color.LightBlue;
style.Pattern = BackgroundType.Solid;
style.Borders[BorderType.BottomBorder].LineStyle = CellBorderType.Thin;
style.Borders[BorderType.TopBorder].LineStyle = CellBorderType.Thin;
worksheet.Cells["A1"].SetStyle(style);
```

This is a critical pattern — virtually every styling operation requires `GetStyle()` / `SetStyle()`. Without MCP, the model has no way to know this.

---

### Hallucination #3: Conditional Formatting

```csharp
// WITHOUT MCP — fabricated API
var rule = worksheet.ConditionalFormattings.AddRule(
    ConditionalFormattingType.CellValue,
    "B2:B100",
    OperatorType.GreaterThan,
    10000
);
rule.Style.Font.Color = Color.Green;
```

```csharp
// WITH MCP — correct multi-step pattern
int index = worksheet.ConditionalFormattings.Add();
FormatConditionCollection fcs = worksheet.ConditionalFormattings[index];
CellArea area = CellArea.CreateCellArea("B2", "B100");
fcs.AddArea(area);

int condIndex = fcs.AddCondition(
    FormatConditionType.CellValue,
    OperatorType.GreaterThan,
    "10000",
    ""
);
FormatCondition fc = fcs[condIndex];
fc.Style.Font.Color = Color.Green;
```

The real API requires creating a `FormatConditionCollection`, adding a `CellArea`, then adding conditions to it. There is no `AddRule()` method.

---

### Hallucination #4: Opening Existing Workbooks

```csharp
// WITHOUT MCP — wrong method
Workbook workbook = new Workbook();
workbook.Open("data.xlsx");      // Open() doesn't exist
```

```csharp
// WITH MCP — constructor-based loading
Workbook workbook = new Workbook("data.xlsx");   // pass path to constructor
```

---

### Hallucination #5: Cell Merging

```csharp
// WITHOUT MCP — wrong parameter semantics
worksheet.Cells.Merge(0, 0, 0, 3);   // (row1, col1, row2, col2)? No.
```

```csharp
// WITH MCP — correct: (firstRow, firstColumn, totalRows, totalColumns)
worksheet.Cells.Merge(0, 0, 1, 4);   // merge 1 row, 4 columns starting at A1
```

The parameters are counts, not coordinates. `Merge(0, 0, 0, 3)` would merge zero rows, which is meaningless.

---

## Scorecard

| Dimension | Without MCP | With MCP | Delta |
|:--|--:|--:|--:|
| API Correctness | 3/10 | 9/10 | **+6** |
| Compilability | 2/10 | 9/10 | **+7** |
| Hallucinations | 6 | 0 | **-6** |
| Code Quality | 7/10 | 8/10 | +1 |
| **Overall** | **3.8/10** | **8.8/10** | **+5.0** |

## How ADCS MCP Helped

Key tool calls:
1. **`get_symbol_doc("Cell.PutValue")`** — returned the correct value-setting method
2. **`query_docs("cell styling format")`** — explained the GetStyle/SetStyle pattern
3. **`get_symbol_doc("ConditionalFormattings")`** — showed the multi-step conditional formatting workflow

Without these lookups, every styling operation, value assignment, and conditional format would fail to compile.
