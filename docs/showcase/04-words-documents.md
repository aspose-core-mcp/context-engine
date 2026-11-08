# How ADCS Eliminates API Hallucinations: Aspose.Words

> Mail merge, find/replace, document assembly — Word automation has deep API patterns that AI assistants get wrong without documentation.

## The Problem

Aspose.Words uses a DOM-based model with `DocumentBuilder` for content creation, a specific mail merge system, and unique find/replace patterns. AI models frequently mix up class names, invent methods, or use patterns from Microsoft Office Interop.

## Real Example: Mail Merge with Regions & Find/Replace

We asked an AI assistant to build a document generator using mail merge with regions, find/replace with regex, and header/footer insertion.

---

### Hallucination #1: Wrong Builder Class Name

```csharp
// WITHOUT MCP — class doesn't exist
DocBuilder builder = new DocBuilder(doc);
builder.AddText("Hello World");
builder.AddParagraph();
```

```csharp
// WITH MCP — correct class and method names
DocumentBuilder builder = new DocumentBuilder(doc);
builder.Write("Hello World");
builder.InsertParagraph();
```

The class is `DocumentBuilder`, not `DocBuilder`. Methods are `Write()` and `InsertParagraph()`, not `AddText()` and `AddParagraph()`.

---

### Hallucination #2: Mail Merge Execution

This is a critical business feature — mail merge with regions for repeating data:

```csharp
// WITHOUT MCP — fabricated method
doc.MailMerge.ExecuteWithTable(dataTable);

// or even worse:
doc.MailMerge.Execute(dataTable);    // wrong overload for regions
```

```csharp
// WITH MCP — correct method for regions
// The DataTable.TableName MUST match the region name in the template
DataTable orderItems = new DataTable("OrderItems");   // matches <<TableStart:OrderItems>>
orderItems.Columns.Add("ProductName", typeof(string));
orderItems.Columns.Add("Quantity", typeof(int));
orderItems.Columns.Add("Price", typeof(decimal));

orderItems.Rows.Add("Widget A", 5, 29.99m);
orderItems.Rows.Add("Widget B", 2, 49.99m);

doc.MailMerge.ExecuteWithRegions(orderItems);
```

`ExecuteWithTable()` doesn't exist. For repeating data regions, you must use `ExecuteWithRegions()` with a `DataTable` whose `TableName` matches the merge region in the template. The MCP tool returned this exact pattern from the mail merge documentation.

---

### Hallucination #3: Find/Replace with Regex

```csharp
// WITHOUT MCP — wrong API surface
doc.Find("old text").ReplaceWith("new text");

// or
doc.Content.Replace("old", "new");    // Content doesn't exist this way
```

```csharp
// WITH MCP — correct Range.Replace with options
FindReplaceOptions options = new FindReplaceOptions();
options.MatchCase = true;
options.FindWholeWordsOnly = false;

// Simple replace
doc.Range.Replace("old text", "new text", options);

// Regex replace
doc.Range.Replace(
    new Regex(@"\b\d{4}-\d{2}-\d{2}\b"),    // date pattern
    "<<DATE>>",
    options
);
```

Find/replace lives on `doc.Range.Replace()`, requires `FindReplaceOptions`, and supports both string and `Regex` patterns. There is no `doc.Find()` or `doc.Content.Replace()`.

---

### Hallucination #4: Headers and Footers

```csharp
// WITHOUT MCP — wrong approach
doc.Header.Text = "Company Report";
doc.Footer.Text = "Page " + pageNum;

// or
doc.AddHeader("Company Report");
```

```csharp
// WITH MCP — correct builder-based approach
DocumentBuilder builder = new DocumentBuilder(doc);

// Move to the header
builder.MoveToHeaderFooter(HeaderFooterType.HeaderPrimary);
builder.ParagraphFormat.Alignment = ParagraphAlignment.Center;
builder.Write("Company Report");

// Move to the footer
builder.MoveToHeaderFooter(HeaderFooterType.FooterPrimary);
builder.ParagraphFormat.Alignment = ParagraphAlignment.Right;
builder.InsertField("PAGE");
builder.Write(" of ");
builder.InsertField("NUMPAGES");

// Return to document body
builder.MoveToDocumentEnd();
```

Headers and footers are accessed by **moving the builder** to the header/footer area, not by direct property access. Page numbers use `InsertField("PAGE")` — Word fields, not hardcoded text.

---

### Hallucination #5: Table Styling

```csharp
// WITHOUT MCP — non-existent properties
Table table = builder.CreateTable(3, 4);     // no such method
table.Style = "Grid Table 4 - Accent 1";    // string-based styling doesn't work
```

```csharp
// WITH MCP — correct cell-by-cell table building
builder.StartTable();

// Header row
builder.InsertCell();
builder.CellFormat.Shading.BackgroundPatternColor = Color.DarkBlue;
builder.Font.Color = Color.White;
builder.Font.Bold = true;
builder.Write("Product");

builder.InsertCell();
builder.Write("Quantity");

builder.InsertCell();
builder.Write("Price");
builder.EndRow();

// Data rows...
builder.InsertCell();
builder.CellFormat.Shading.BackgroundPatternColor = Color.White;
builder.Font.Color = Color.Black;
builder.Font.Bold = false;
builder.Write("Widget A");
// ...

builder.EndTable();

// Apply built-in style
Table table = (Table)doc.GetChild(NodeType.Table, 0, true);
table.StyleIdentifier = StyleIdentifier.MediumShading1Accent1;
```

Tables are built cell-by-cell with `InsertCell()` / `EndRow()` / `EndTable()`. Styling uses `StyleIdentifier` enum, not string names.

---

## Scorecard

| Dimension | Without MCP | With MCP | Delta |
|:--|--:|--:|--:|
| API Correctness | 3/10 | 9/10 | **+6** |
| Compilability | 2/10 | 10/10 | **+8** |
| Hallucinations | 6 | 0 | **-6** |
| Code Quality | 7/10 | 8/10 | +1 |
| **Overall** | **3.5/10** | **8.7/10** | **+5.2** |

## How ADCS MCP Helped

Key tool calls:
1. **`get_symbol_doc("DocumentBuilder")`** — correct class name, `Write()` / `InsertParagraph()` methods
2. **`query_docs("mail merge regions DataTable")`** — exact `ExecuteWithRegions` pattern with `TableName` requirement
3. **`get_symbol_doc("Range.Replace")`** — showed both string and Regex overloads
4. **`query_docs("headers footers page numbers")`** — `MoveToHeaderFooter` + `InsertField("PAGE")` pattern

The mail merge region pattern (where `DataTable.TableName` must match the template region) is especially critical — without this knowledge, the generated code silently produces empty documents.
