# Document Parsing, Semantic Chunking and Vectorization

Date: 2026-10-21
Status: Implementation in progress; development clean-rebuild baseline

## Goal

Replace the current character-based Markdown splitting pipeline with a type-aware
document parser, a shared structured document representation, token-aware semantic
chunking, and Parent-Child retrieval context.

The pipeline must preserve headings, reading order, page locations, paragraphs,
lists, code blocks and textual tables. It must never split an English word or code
identifier by character count when a sentence or word boundary exists.

## Non-Goals

- Scanned PDF OCR is not implemented in this phase.
- Mixed text/image PDF parsing is not implemented in this phase.
- Image, chart and multimodal embedding are not implemented in this phase.
- Embedding-based semantic boundary detection is deferred.
- Late Chunking and LLM-based contextual chunking are deferred.
- Existing active generations are not migrated in place.

## Decisions

1. Native electronic PDFs use a local PyMuPDF parser. PyMuPDF is a new backend
   dependency.
2. Scanned and mixed PDFs are classified and rejected with stable error codes. Their
   document records retain the classification so future OCR or Docling adapters can
   process them.
3. Semantic chunking is structure-first: heading, paragraph, sentence, word, then
   character fallback.
4. Chunk budgets use the BGE-M3 tokenizer, not character counts.
5. Parent-Child Chunk is implemented in this phase. Child chunks are indexed and
   retrieved; parent chunks provide generation context.
6. Embedding and rerank remain separate local services. The embedding service gains
   a `/tokenize` endpoint backed by the same BGE-M3 tokenizer.
7. Document ingestion fails closed when the tokenizer or embedding service is
   unavailable. It must not silently write hash embeddings.
8. The new parser and chunker versions require a new generation rebuild.

## Pipeline

```text
Upload
  -> file extension, MIME type and size validation
  -> ParserRouter
  -> DocumentNode tree
  -> normalization and structure cleanup
  -> semantic boundary segmentation
  -> Parent Chunk construction
  -> Child Chunk construction
  -> BGE-M3 tokenizer budget validation
  -> Embedding for child chunks only
  -> PostgreSQL chunk persistence
  -> Elasticsearch and Qdrant writes
  -> parse, chunk and vector quality validation
  -> generation validation and activation
```

## Parser Router

`parse_document(path, metadata) -> ParsedDocument` selects a parser by validated
file type and PDF kind. It does not infer parser behavior from the filename alone.

Supported parser adapters:

- `MarkdownParser`: `.md`, `.txt`
- `DocxParser`: `.docx`
- `NativePdfParser`: `.pdf` with `pdf_kind=native`
- `ScannedPdfParser`: reserved; returns `PDF_SCANNED_UNSUPPORTED`
- `MixedPdfParser`: reserved; returns `PDF_MIXED_UNSUPPORTED`

Parser interface:

```python
class DocumentParser(Protocol):
    def supports(self, descriptor: DocumentDescriptor) -> bool: ...
    def parse(self, source: Path, descriptor: DocumentDescriptor) -> ParsedDocument: ...
```

Parsed result:

```python
@dataclass(frozen=True)
class ParsedDocument:
    nodes: List[DocumentNode]
    parser_name: str
    parser_version: str
    pdf_kind: Optional[str]
    warnings: List[str]
    quality: ParseQuality
```

## PDF Classification

PDF classification runs before full parsing.

Per page, calculate:

- extracted text character count
- text block area ratio
- image block area ratio
- page area

Classification:

- `scanned`: negligible text on most pages and significant image coverage
- `mixed`: meaningful text on most pages but significant image coverage
- `native`: meaningful text without significant image coverage

Initial configurable heuristics:

- negligible text: fewer than 50 non-whitespace characters per page
- significant image coverage: image blocks cover at least 30% of page area
- classify by majority page kind, while recording per-page kinds

The classification, page counts and heuristic values are stored in parse metadata.
If classification is uncertain, prefer `mixed` and reject ingestion rather than
silently dropping visual content.

## DocumentNode

All parsers produce the same structured node model:

```python
@dataclass(frozen=True)
class DocumentNode:
    node_id: str
    node_type: str
    text: str
    heading_path: Tuple[str, ...]
    page_no: Optional[int]
    bbox: Optional[Tuple[float, float, float, float]]
    reading_order: int
    metadata: Dict[str, Any]
    source_locator: Dict[str, Any]
```

Allowed `node_type` values:

- `heading`
- `paragraph`
- `list`
- `table`
- `code`
- `page_break`

Heading nodes are retained in the tree for structure and can be included in parent
context. They are not emitted as independent retrieval chunks.

## Native PDF Parsing

PyMuPDF is responsible for:

- text blocks, coordinates, font size and bold state
- page numbers and bounding boxes
- column-aware reading order
- repeated header/footer detection
- heading inference
- basic textual table extraction

Reading order:

1. Group text blocks into page-level column bands using x-coordinate clustering.
2. Sort columns from left to right.
3. Sort blocks inside each column by y-coordinate, then x-coordinate.
4. Preserve explicit page breaks.

Header/footer cleanup:

- compare text in the top and bottom 8% of pages
- remove repeated short lines that appear on at least 30% of pages
- never remove a line solely because it matches a page-number pattern if it also
  contains document content

Heading inference:

- relative font size compared with the page body median
- bold or heavier font weight
- short line length
- not identified as a repeated header/footer
- heading level inferred from font-size buckets

Table extraction:

- use PyMuPDF table detection where available
- preserve header row and row order
- store table rows as structured metadata and Markdown text
- if table detection fails, emit a paragraph node with
  `table_parse_degraded=true`, never silently discard the text

## DOCX Parsing

The DOCX parser must preserve original block order:

- paragraphs and tables are emitted in document order
- Word styles `Title` and `Heading 1..6` create heading nodes
- font size and bold styling are used as fallback heading signals
- tables become table nodes instead of being appended after all paragraphs
- empty paragraphs are ignored

## Markdown and TXT Parsing

Markdown parsing continues to support ATX headings from `#` to `######`.

- headings inside fenced code blocks are not headings
- paragraphs, lists, tables and fenced code blocks become typed nodes
- TXT uses paragraph nodes and has no heading structure

## Normalization

Normalization preserves semantic content and removes only transport noise:

- unify CRLF and CR to LF
- trim trailing whitespace
- collapse three or more blank lines to two
- remove parsed page headers and footers
- preserve indentation inside code fences
- preserve table cell contents
- never concatenate two paragraphs without a separator

## Semantic Chunking

The chunker receives a `ParsedDocument`, not raw source text.

### Boundaries

Hard boundaries:

- document start/end
- heading change
- page break for PDF parent grouping metadata
- code fence boundaries
- table boundaries

Preferred boundaries:

1. paragraph
2. list item
3. sentence
4. whitespace
5. punctuation
6. character fallback

Character fallback is allowed only when no safe boundary exists. A chunk produced by
character fallback is marked with `unsafe_split=true`.

### Sentence Splitting

Sentence splitting must:

- support Chinese punctuation `。！？；` and English `.`, `!`, `?`, `;`
- avoid splitting decimal numbers, versions, URLs, file names and error codes
- avoid splitting abbreviations where a safe heuristic is available
- never split inside a fenced code block
- never split an English word or identifier unless the token itself exceeds the
  maximum chunk budget and no safe boundary exists

### Token Budgets

Token counts come from the BGE-M3 tokenizer service.

Default budgets:

- prose child target: 480 tokens
- prose child maximum: 512 tokens
- prose child overlap: 64 tokens
- prose parent target: 1200 tokens
- prose parent maximum: 1400 tokens
- code child target: 120 tokens
- code child maximum: 160 tokens
- code child overlap: 16 tokens
- minimum child target: 64 tokens before merging with adjacent nodes
- table child maximum: 512 tokens

The embedding metadata prefix counts toward the child budget.

### Small Chunk Merging

Adjacent nodes under the same heading are merged while the result remains under the
target budget. A trailing child smaller than 64 tokens is merged into the previous
child when safe. A heading-only child is never emitted.

### Overlap

Overlap is applied only between adjacent child chunks inside the same parent:

- prefer whole trailing sentences for overlap
- do not duplicate code unless the overlap exists inside the same function or block
- do not duplicate table headers in child content; table row splits repeat headers
  structurally instead
- prefer intact table rows; when one row exceeds the token budget, split at safe
  whitespace or punctuation boundaries, preserving exact parent offsets and all
  cell text. Repeat the header and the continued row's first-cell label in the
  embedding context, and mark `source_locator.table_row_split` explicitly. The
  repeated context counts toward the same token limit; no limit bypass is allowed.
- cap overlap at 64 prose tokens and 16 code tokens

## Parent-Child Construction

A parent chunk is a coherent section or paragraph group, targeting 1200 tokens. A
parent is split only when the section exceeds 1400 tokens.

Each child records:

- `parent_chunk_id`
- `child_order`
- `parent_start_offset`
- `parent_end_offset`

Each parent records:

- ordered child IDs
- heading path
- page range
- content type

Parent chunks are stored in PostgreSQL but are not written to Elasticsearch or
Qdrant. Child chunks are written to both retrieval indexes.

At retrieval:

1. Match child chunks.
2. Resolve child IDs to parents.
3. Deduplicate parents.
4. Use parent content for rerank and LLM context.
5. Preserve child evidence and source locations in Trace.

If multiple children from one parent are matched, inject that parent only once.

Manual chunk overrides remain child-level. Parent context is assembled from the
stored parent text and active child overrides using the child's parent character
offsets. Overrides are applied from the end of the parent toward the beginning so
earlier offsets remain stable. If child ranges overlap incorrectly or an override
cannot be applied safely, the parent is marked context-invalid and generation is
blocked until the document is rebuilt.

## Tokenizer Service

The local embedding service gains:

```http
POST /tokenize
```

Request:

```json
{"texts": ["...", "..."]}
```

Response:

```json
{
  "counts": [128, 64],
  "model": "BAAI/bge-m3",
  "max_length": 8192
}
```

The endpoint uses the tokenizer already loaded by the BGE-M3 model. It does not
generate vectors.

Tokenizer batch size is limited by configuration. Ingestion retries transient HTTP
failures at most twice. A persistent failure marks the ingestion run failed.

## Embedding

Only enabled child chunks are embedded.

Embedding input:

```text
Document: <file name>
Section: <heading path>
Content: <child content>
```

The prefix is included in the token budget and stored separately in parse metadata.

Constraints:

- batch size is configurable
- vector count must equal child count
- dimensions must equal the configured dimension
- model name must match the expected embedding model
- embedding failures are terminal for document ingestion
- hash embedding is disabled for document ingestion when a real embedding service is
  configured
- tests may explicitly enable hash embeddings through test-only settings

The ingestion run stores embedding model, tokenizer model and dimensions.

## Persistence

### Document

Store the validated source MIME type as `documents.mime_type`. Parser routing uses
the combination of validated extension, MIME type and detected PDF kind. The MIME
type is also copied into parse metadata for reproducibility.

### ChunkRecord

Add:

- `parent_chunk_id: Optional[str]`
- `chunk_level: str` (`parent` or `child`)
- `child_order: int`
- `node_type: str`
- `token_count: int`
- `page_no: Optional[int]`
- `parse_version: str`
- `chunking_version: str`
- `embedding_model: str`
- `tokenizer_model: str`
- `parent_start_offset: int`
- `parent_end_offset: int`

Parent chunks have no vectors. Child vectors are stored in retrieval indexes; PostgreSQL stores their metadata and source content.

### Parse Metadata

Add `parse_metadata` and `chunking_metadata` JSON text fields to
`DocumentVersion`. Add `quality_metrics` and `failure_details` JSON text fields to
`IngestionRun`.

`DocumentVersion.parse_metadata` stores:

- parser name and version
- PDF kind and per-page kinds
- parse warnings
- parse quality metrics

`DocumentVersion.chunking_metadata` stores:

- chunking version
- tokenizer model
- embedding model
- chunk count and token distribution

`IngestionRun.quality_metrics` stores per-run parse, chunk and embedding metrics.
`IngestionRun.failure_details` stores structured error details and retry decisions.

### ES/Qdrant Payload

Add:

- `parent_chunk_id`
- `chunk_level`
- `node_type`
- `token_count`
- `page_no`
- `parse_version`
- `chunking_version`
- `embedding_model`
- `tokenizer_model`

Every retrieval engine filters to `chunk_level=child`.

## Quality Validation

### Parse Validation

- empty extracted text
- garbled character rate
- page text coverage
- PDF type classification
- number of unsupported pages
- number of degraded tables
- heading count for structured documents

### Chunk Validation

- empty chunk count
- minimum, maximum, average and P95 token counts
- child-to-parent coverage
- parent without children
- orphan child
- unsafe split count
- split-inside-word detection
- duplicate child order
- table row/header integrity

### Embedding Validation

- child and vector count equality
- dimension equality
- finite numeric values
- non-zero vector ratio
- model and tokenizer version equality

Quality failures prevent generation activation.

## Error Codes

New stable ingestion errors:

- `PDF_SCANNED_UNSUPPORTED`
- `PDF_MIXED_UNSUPPORTED`
- `PDF_LAYOUT_PARSE_FAILED`
- `TOKENIZER_UNAVAILABLE`
- `TOKENIZER_RESPONSE_INVALID`
- `CHUNK_QUALITY_FAILED`
- `EMBEDDING_UNAVAILABLE`
- `EMBEDDING_DIMENSION_MISMATCH`
- `EMBEDDING_FALLBACK_FORBIDDEN`
- `PARENT_CHILD_INTEGRITY_FAILED`

Each error exposes a retryable flag. Parser incompatibility and unsupported PDF kind
are not retryable without a new file or parser version.

## Development Baseline and Publication

Historical development data may be discarded. This change requires a fresh database
and fresh ES/Qdrant indexes; it does not backfill old rows or support old index
payloads. Cleanup is an explicit operator action, never an application startup side
effect. After deployment, every new generation must remain internally consistent.

- Build complete team generations without deleting the currently published index.
- Record independent generation membership and chunk metadata snapshots. Switching
  the active generation must not move the only copy of an old generation's rows.
- Validate every ES bulk item, index counts, parent/child integrity and vectors
  before changing the database routing pointer.
- Serialize ingestion and index rebuild publication per team using database leases.
- Completed or cancelled ingestion runs must not execute again on duplicate delivery.
- Keep logical override keys independent of content hashes and document version IDs.
- Carry exact source spans through chunk construction. Never infer offsets by
  searching for normalized child text inside a differently normalized parent.
- Reject conflicting overlapping edits; disabled child ranges must not reappear in
  generated parent context.
- Store child evidence IDs separately from the hydrated parent ID used in generation.

## Testing

Parser tests:

- native PDF headings, multiple columns, page order, headers/footers
- basic PDF table extraction and degraded-table fallback
- scanned and mixed PDF classification and rejection
- DOCX paragraph/table order and heading styles
- Markdown fenced code and heading preservation

Tokenizer tests:

- tokenizer endpoint request/response validation
- tokenizer model mismatch
- transient and terminal failures

Chunking tests:

- no English word split when a safe boundary exists
- no sentence split for versions, URLs, file names and error codes
- Chinese sentence boundaries
- 480/512 token limits and 64-token overlap
- code block budgets and boundaries
- table row splitting with repeated headers
- small chunk merging and orphan prevention
- deterministic parent and child IDs

Retrieval tests:

- parent resolution and deduplication
- child evidence remains visible in Trace
- generation uses parent context
- ES/Qdrant filters exclude parent rows
- active child overrides are applied to parent context using parent offsets
- invalid or overlapping override ranges block generation with an integrity error

Quality tests:

- parse and chunk quality reports
- embedding count/dimension/model failures
- no hash embedding fallback during configured real ingestion
- generation activation blocked on validation failure

End-to-end tests:

- upload Markdown, DOCX and native PDF fixtures
- parse, chunk, tokenize, embed and index
- verify child retrieval returns parent context
- verify citations locate the original page and section
- verify scanned/mixed PDFs fail with visible error codes

## Risks

- PyMuPDF heading and table heuristics require fixture-based tuning.
- Parent context increases database storage.
- Parent-child resolution adds retrieval latency.
- Exact BGE-M3 tokenization introduces a runtime dependency on the embedding service.
- Stricter fail-closed embedding behavior may make local ingestion fail more visibly
  than the current hash fallback.
- Native PDF reading order remains heuristic; complex layouts may need Docling later.
