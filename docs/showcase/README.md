# ADCS Showcase: How MCP Eliminates API Hallucinations

Real-world examples comparing AI-generated code **with** and **without** ADCS MCP documentation access across 5 Aspose products.

## Articles

| # | Product | Key Hallucination Pattern | Hallucinations Fixed |
|:--|:--------|:--------------------------|:----:|
| [01](01-ocr-recognition.md) | **Aspose.OCR** | Fabricated `RecognitionAreas` object graph, wrong enums | 8 |
| [02](02-cells-spreadsheets.md) | **Aspose.Cells** | `cell.Value` instead of `PutValue()`, wrong styling pattern | 6 |
| [03](03-pdf-documents.md) | **Aspose.PDF** | `PdfDocument`/`TextExtractor` classes don't exist, wrong merge API | 7 |
| [04](04-words-documents.md) | **Aspose.Words** | `DocBuilder` class, `ExecuteWithTable()`, direct header access | 6 |
| [05](05-barcode-generation.md) | **Aspose.BarCode** | Entire removed API (`BarCodeBuilder`), wrong parameter model | 9 |

## The Pattern

Every article follows the same structure:
1. **The Problem** — why AI assistants fail on this product
2. **Side-by-side code** — real WITHOUT MCP vs WITH MCP examples
3. **Explanation** — what the model hallucinated and why
4. **Scorecard** — quantified impact (API correctness, compilability, hallucination count)
5. **MCP tool calls** — which ADCS tools provided the correct information

## Aggregate Impact

Across all 5 products:

| Metric | Without MCP | With MCP |
|:-------|:------------|:---------|
| Average API Correctness | 2.2/10 | 9.0/10 |
| Average Compilability | 1.2/10 | 9.8/10 |
| Total Hallucinations | 36 | 0 |
| Average Overall Score | 3.3/10 | 8.8/10 |

**Key finding:** Code quality (structure, error handling, naming) is similar in both cases. The *only* difference is API accuracy — and that difference determines whether the code compiles or not.
