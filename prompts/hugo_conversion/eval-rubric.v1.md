# Conversion Evaluation Rubric v1

## Critical checks (must pass)
1. Valid JSON.
2. `schema == adcs.normalized_document.v1`.
3. Required document metadata is complete.
4. Each chunk has valid citation metadata.
5. Source path and revision are preserved.

## Quality checks
1. API signatures preserved for API pages.
2. Parameter tables preserved for API pages.
3. Code blocks preserved without semantic corruption.
4. Chunk overlap with source text is acceptable.
5. No obvious hallucinated entities.

## Scoring guidance
- 90-100: production candidate.
- 75-89: acceptable with targeted fixes.
- <75: reject and revise prompt/converter logic.
