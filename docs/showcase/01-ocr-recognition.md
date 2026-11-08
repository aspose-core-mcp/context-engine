# How ADCS Eliminates API Hallucinations: Aspose.OCR

> AI code assistants generate plausible but **wrong** API calls. ADCS MCP provides real-time documentation access that fixes this.

## The Problem

When asked to build an OCR recognition service with Aspose.OCR for .NET, AI assistants confidently generate code using API members that **don't exist** in the current version. The code looks correct, follows good patterns — but won't compile.

## Real Example: OCR Image Recognition

We asked the same AI assistant (Qwen CLI) to implement an OCR service. Once **without** documentation access, once **with** ADCS MCP.

---

### Hallucination #1: Wrong Enum Value

Without documentation, the model guesses `Language.English` — a reasonable name, but the actual enum value is `Language.Eng`.

```csharp
// WITHOUT MCP — does not compile
var settings = new RecognitionSettings
{
    Language = Language.English,           // enum member doesn't exist
    DetectAreasMode = DetectAreasMode.COMBINE,
    SkewCorrect = true                    // property removed in v23+
};
```

```csharp
// WITH MCP — compiles and runs
var settings = new RecognitionSettings
{
    Language = Language.Eng,               // correct enum member
    DetectAreasMode = DetectAreasMode.UNIVERSAL
};
settings.UpscaleSmallFont = true;          // correct preprocessing flag
```

The model looked up `Language` via `get_symbol_doc` and got the exact enum values: `Eng`, `Spa`, `Fra`, `Deu` — not `English`, `Spanish`, etc.

---

### Hallucination #2: Fabricated Object Graph

This is the most dangerous type of hallucination — the model invents an **entire API surface** that doesn't exist:

```csharp
// WITHOUT MCP — fabricated RecognitionAreas API
var recognitionResult = _ocr.Recognize(filePath, settings);

if (recognitionResult != null && recognitionResult.RecognitionAreas != null)
{
    foreach (var area in recognitionResult.RecognitionAreas)
    {
        var areaResult = new OcrAreaResult
        {
            Text = area.Text ?? string.Empty,       // doesn't exist
            Confidence = area.Confidence,            // doesn't exist
            BoundingBox = new OcrBoundingBox
            {
                X = area.Rect.X,                     // doesn't exist
                Y = area.Rect.Y,
                Width = area.Rect.Width,
                Height = area.Rect.Height
            }
        };
        result.Areas.Add(areaResult);
    }
}
```

None of these members exist: `RecognitionAreas`, `area.Text`, `area.Confidence`, `area.Rect`. The model hallucinated a plausible-looking object graph based on what OCR APIs *should* look like.

```csharp
// WITH MCP — uses the real API
var input = new OcrInput(InputType.SingleImage);
input.Add(imagePath);
var output = _ocrEngine.Recognize(input, settings);

foreach (var recognitionResult in output)
{
    var areaResult = new AreaResult
    {
        Text = recognitionResult.RecognitionText,    // real property
        Confidence = ExtractConfidence(recognitionResult)
    };
    result.Areas.Add(areaResult);
}
```

With MCP, the model queried `RecognitionResult` via `get_symbol_doc` and discovered the actual properties: `RecognitionText`, `RecognitionAreasText`, `RecognitionAreasRectangles`.

---

### Hallucination #3: Non-Existent Exception & Disposed Pattern

```csharp
// WITHOUT MCP — two more hallucinations
catch (AsposeOcrException ex)                 // class doesn't exist
{
    result.ErrorMessage = $"OCR engine error: {ex.Message}";
}

protected virtual void Dispose(bool disposing)
{
    if (disposing)
    {
        _ocr?.Dispose();                       // AsposeOcr is not IDisposable
    }
}
```

```csharp
// WITH MCP — correct patterns
catch (Exception ex) when (ex is not InvalidOperationException)
{
    throw new InvalidOperationException($"OCR recognition failed: {ex.Message}", ex);
}

// No Dispose needed — AsposeOcr doesn't implement IDisposable
public class OcrService
{
    private readonly AsposeOcr _ocrEngine = new AsposeOcr();
}
```

---

## Scorecard

| Dimension | Without MCP | With MCP | Delta |
|:--|--:|--:|--:|
| API Correctness | 2/10 | 9/10 | **+7** |
| Compilability | 1/10 | 10/10 | **+9** |
| Hallucinations | 8 | 0 | **-8** |
| Code Quality | 8/10 | 8/10 | 0 |
| **Overall** | **3.5/10** | **8.7/10** | **+5.2** |

Both versions have clean code structure and good separation of concerns. The only difference is **API accuracy** — and that difference is the gap between a non-compilable prototype and a production-ready solution.

---

## How ADCS MCP Helped

The AI assistant made 3 MCP tool calls during code generation:

1. **`resolve_product("aspose.ocr")`** — confirmed the canonical product ID
2. **`query_docs("OCR recognition settings language")`** — found current `RecognitionSettings` documentation
3. **`get_symbol_doc("RecognitionResult")`** — got exact property signatures

Total overhead: ~4 seconds of API calls. Result: code that compiles on the first try.
