# How ADCS Eliminates API Hallucinations: Aspose.BarCode

> Barcode generation and recognition had a major API rewrite. AI models still generate the removed API.

## The Problem

Aspose.BarCode underwent a significant API change: the legacy `BarCodeBuilder` class was **removed** and replaced with `BarcodeGenerator`. AI models trained on older documentation consistently generate code using the removed API, producing compile errors on every line.

## Real Example: QR, Code128 & DataMatrix Generation + Recognition

We asked an AI assistant to build a barcode generator and reader supporting multiple formats.

---

### Hallucination #1: Removed Main Class

This is a complete API mismatch — the model uses a class that was removed entirely:

```csharp
// WITHOUT MCP — BarCodeBuilder was removed in v22+
BarCodeBuilder builder = new BarCodeBuilder();
builder.CodeText = "Hello World";
builder.SymbologyType = Symbology.QR;
builder.QRErrorLevel = QRErrorLevel.LevelH;
builder.Save("qr.png");
```

```csharp
// WITH MCP — correct current API
BarcodeGenerator gen = new BarcodeGenerator(EncodeTypes.QR, "Hello World");
gen.Parameters.Barcode.QR.QrErrorLevel = QRErrorLevel.LevelH;
gen.Parameters.Barcode.XDimension.Pixels = 8;
gen.Save("qr.png", BarCodeImageFormat.Png);
```

The entire approach is different: `BarcodeGenerator` takes the encode type and data in the constructor, and all parameters are accessed through the `Parameters` property tree.

---

### Hallucination #2: Parameter Access Pattern

Even when models get the class name right, they hallucinate the parameter access:

```csharp
// WITHOUT MCP — flat property access (doesn't exist)
gen.XDimension = 8;
gen.BarColor = Color.DarkBlue;
gen.BackColor = Color.White;
gen.Resolution = 300;
gen.Caption = "Product ID: 12345";
```

```csharp
// WITH MCP — nested Parameters tree
gen.Parameters.Barcode.XDimension.Pixels = 8;
gen.Parameters.Barcode.BarColor = Color.DarkBlue;
gen.Parameters.BackColor = Color.White;
gen.Parameters.Resolution = 300;
gen.Parameters.CaptionAbove.Text = "Product ID: 12345";
gen.Parameters.CaptionAbove.Visible = true;
gen.Parameters.Barcode.CodeTextParameters.Location = CodeLocation.Below;
```

Every parameter goes through the nested `Parameters` hierarchy. Caption has separate `CaptionAbove` and `CaptionBelow` objects. Code text display is controlled via `CodeTextParameters`.

---

### Hallucination #3: Multiple Barcode Formats

```csharp
// WITHOUT MCP — wrong enum names
var qr = new BarCodeBuilder("data", Symbology.QR);           // wrong enum
var code128 = new BarCodeBuilder("data", Symbology.Code128);  // wrong
var dm = new BarCodeBuilder("data", Symbology.DataMatrix);    // wrong
```

```csharp
// WITH MCP — correct EncodeTypes static fields
var qr = new BarcodeGenerator(EncodeTypes.QR, "https://example.com");
var code128 = new BarcodeGenerator(EncodeTypes.Code128, "ABC-12345");
var dataMatrix = new BarcodeGenerator(EncodeTypes.DataMatrix, "DMX-DATA-001");
var pdf417 = new BarcodeGenerator(EncodeTypes.Pdf417, "Long data payload...");
```

Barcode types are `EncodeTypes.QR`, `EncodeTypes.Code128`, etc. — not `Symbology.QR`.

---

### Hallucination #4: Barcode Recognition

The recognition API had the same overhaul:

```csharp
// WITHOUT MCP — removed API
BarCodeReader reader = new BarCodeReader("image.png");
while (reader.Read())                              // Read() was removed
{
    Console.WriteLine(reader.GetCodeText());        // wrong method
    Console.WriteLine(reader.GetBarCodeType());     // wrong property name
}
```

```csharp
// WITH MCP — correct current API
BarCodeReader reader = new BarCodeReader(
    "image.png",
    DecodeType.AllSupportedTypes
);
reader.QualitySettings = QualitySettings.HighQuality;

foreach (BarCodeResult result in reader.ReadBarCodes())
{
    Console.WriteLine($"Type: {result.CodeType}");     // correct property
    Console.WriteLine($"Text: {result.CodeText}");     // correct property
    Console.WriteLine($"Region: {result.Region}");
}
```

`Read()` was replaced with `ReadBarCodes()` which returns `BarCodeResult[]`. Result properties are `CodeType` and `CodeText` (not `GetBarCodeType()` and `GetCodeText()`).

---

### Hallucination #5: Save Format

```csharp
// WITHOUT MCP — wrong save pattern
builder.Save("barcode.png");                     // no format specified
builder.Save("barcode.svg", ImageFormat.Svg);    // wrong enum
```

```csharp
// WITH MCP — correct BarCodeImageFormat enum
gen.Save("barcode.png", BarCodeImageFormat.Png);
gen.Save("barcode.svg", BarCodeImageFormat.Svg);
gen.Save("barcode.emf", BarCodeImageFormat.Emf);
```

Save requires `BarCodeImageFormat`, not `ImageFormat`.

---

## Scorecard

| Dimension | Without MCP | With MCP | Delta |
|:--|--:|--:|--:|
| API Correctness | 1/10 | 9/10 | **+8** |
| Compilability | 0/10 | 10/10 | **+10** |
| Hallucinations | 9 | 0 | **-9** |
| Code Quality | 7/10 | 8/10 | +1 |
| **Overall** | **2.5/10** | **8.9/10** | **+6.4** |

## Why This Product Is the Worst Case Without MCP

Aspose.BarCode is the **hardest product for AI assistants** because:

1. **Complete API rewrite** — `BarCodeBuilder` was fully removed, not just deprecated
2. **Nested parameter model** — the `Parameters.Barcode.XDimension.Pixels` hierarchy is unique
3. **Training data poisoning** — most online examples and tutorials still show the old API
4. **Two sides** — both generation (`BarcodeGenerator`) and recognition (`BarCodeReader.ReadBarCodes()`) were rewritten

With ADCS MCP, the model queried `list_breaking_changes` and immediately learned about the `BarCodeBuilder` removal, then used `get_symbol_doc("BarcodeGenerator")` to get the correct current API.
