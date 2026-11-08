# How ADCS Eliminates API Hallucinations: Aspose.PDF

> PDF manipulation requires exact API knowledge — merge, watermark, extract. The wrong class name means the code doesn't even compile.

## The Problem

Aspose.PDF has a large API surface with specific class names and patterns. AI assistants frequently hallucinate class names from other PDF libraries (like iText or PdfSharp) or invent plausible-sounding classes that don't exist.

## Real Example: PDF Merge, Watermark & Text Extraction

We asked an AI assistant to build a .NET console app that merges PDFs, adds watermarks, extracts text, and applies security settings.

---

### Hallucination #1: Wrong Class Names

This is the most common PDF hallucination — using class names from other libraries:

```csharp
// WITHOUT MCP — classes don't exist in Aspose.PDF
using Aspose.Pdf;

PdfDocument doc = new PdfDocument("input.pdf");   // wrong class name
PdfReader reader = new PdfReader("input.pdf");     // from iText, not Aspose
```

```csharp
// WITH MCP — correct class name
using Aspose.Pdf;

Document doc = new Document("input.pdf");           // just "Document"
```

The main class is simply `Document`, not `PdfDocument`. There is no `PdfReader`. ADCS returned this from `resolve_product` + `query_docs`.

---

### Hallucination #2: Text Extraction

AI models often fabricate a `TextExtractor` class that doesn't exist:

```csharp
// WITHOUT MCP — fabricated class
var extractor = new TextExtractor(doc);
string text = extractor.ExtractAll();

// or sometimes
string text = page.GetText();
```

```csharp
// WITH MCP — correct absorber pattern
TextAbsorber absorber = new TextAbsorber();
page.Accept(absorber);
string text = absorber.Text;

// For search:
TextFragmentAbsorber tfa = new TextFragmentAbsorber("search term");
page.Accept(tfa);
foreach (TextFragment fragment in tfa.TextFragments)
{
    Console.WriteLine($"Found: '{fragment.Text}' at ({fragment.Position.XIndent}, {fragment.Position.YIndent})");
}
```

Aspose.PDF uses the **Absorber pattern** — you create an absorber, pass it to `page.Accept()`, then read the results. This is unique to Aspose and no amount of guessing will produce it.

---

### Hallucination #3: PDF Merging

```csharp
// WITHOUT MCP — wrong merge class
using Aspose.Pdf.Facades;

PdfMerger merger = new PdfMerger();                  // doesn't exist
merger.AddDocument("file1.pdf");
merger.AddDocument("file2.pdf");
merger.Save("merged.pdf");
```

```csharp
// WITH MCP — two correct approaches

// Approach 1: Document.Pages.Add()
Document doc1 = new Document("file1.pdf");
Document doc2 = new Document("file2.pdf");
doc1.Pages.Add(doc2.Pages);
doc1.Save("merged.pdf");

// Approach 2: Facades
PdfFileEditor editor = new PdfFileEditor();          // correct class name
editor.Concatenate("file1.pdf", "file2.pdf", "merged.pdf");
```

The class is `PdfFileEditor`, not `PdfMerger`. The simplest approach is `document.Pages.Add(otherDoc.Pages)`.

---

### Hallucination #4: Watermarks

```csharp
// WITHOUT MCP — fabricated watermark API
var watermark = new Watermark("CONFIDENTIAL");
watermark.Rotation = 45;
watermark.Opacity = 0.3;
doc.AddWatermark(watermark);
```

```csharp
// WITH MCP — correct TextStamp approach
foreach (Page page in doc.Pages)
{
    TextStamp stamp = new TextStamp("CONFIDENTIAL");
    stamp.RotateAngle = 45;
    stamp.Opacity = 0.3;
    stamp.TextState.FontSize = 72;
    stamp.TextState.ForegroundColor = Aspose.Pdf.Color.FromRgb(System.Drawing.Color.Gray);
    stamp.HorizontalAlignment = HorizontalAlignment.Center;
    stamp.VerticalAlignment = VerticalAlignment.Center;
    page.AddStamp(stamp);
}
```

There is no `Watermark` class or `AddWatermark` method. Watermarks are `TextStamp` or `ImageStamp` objects added via `page.AddStamp()`.

---

### Hallucination #5: Encryption

```csharp
// WITHOUT MCP — wrong method signature
doc.Encrypt("user", "owner", PdfPermissions.PrintDocument, EncryptionAlgorithm.AES256);
```

```csharp
// WITH MCP — correct method and enum names
doc.Encrypt("userPassword", "ownerPassword",
    DocumentPrivilege.AllowAll,
    CryptoAlgorithm.AESx256);
```

The enum is `CryptoAlgorithm.AESx256` (not `EncryptionAlgorithm.AES256`), and privileges use `DocumentPrivilege`.

---

## Scorecard

| Dimension | Without MCP | With MCP | Delta |
|:--|--:|--:|--:|
| API Correctness | 2/10 | 9/10 | **+7** |
| Compilability | 1/10 | 10/10 | **+9** |
| Hallucinations | 7 | 0 | **-7** |
| Code Quality | 7/10 | 8/10 | +1 |
| **Overall** | **3.2/10** | **8.9/10** | **+5.7** |

## How ADCS MCP Helped

Key tool calls:
1. **`resolve_product("aspose.pdf")`** — confirmed namespace `Aspose.Pdf` and main class `Document`
2. **`query_docs("text extraction PDF")`** — returned the `TextAbsorber` pattern
3. **`get_symbol_doc("TextStamp")`** — showed watermark properties (`RotateAngle`, `Opacity`, `TextState`)
4. **`get_symbol_doc("Document.Encrypt")`** — returned exact parameter types: `DocumentPrivilege`, `CryptoAlgorithm`

The absorber pattern, stamp-based watermarking, and `PdfFileEditor` for merging are all Aspose-specific patterns impossible to guess from general PDF knowledge.
