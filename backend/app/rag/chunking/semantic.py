"""Token-budgeted chunks with exact source spans and deterministic identities."""
import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from backend.app.rag.chunking.identity import build_logical_chunk_key
from backend.app.rag.parsing.contracts import NodeType, ParseError


def stable_id(prefix, *parts):
    return prefix + hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


def embedding_input(file_name, heading_path, content, table_header=""):
    prefix = "Document: {0}\nSection: {1}\n".format(file_name, " / ".join(heading_path))
    if table_header:
        prefix += "Table header: " + table_header + "\n"
    return prefix + "Content: " + content


@dataclass(frozen=True)
class ChunkBudget:
    child_target: int = 480
    child_max: int = 512
    child_overlap: int = 64
    parent_target: int = 1200
    parent_max: int = 1400
    code_target: int = 120
    code_max: int = 160
    code_overlap: int = 16
    table_max: int = 512
    minimum_child: int = 64

    def __post_init__(self):
        if not (0 < self.child_target <= self.child_max and 0 <= self.child_overlap < self.child_target
                and 0 < self.parent_target <= self.parent_max and 0 < self.code_target <= self.code_max
                and 0 <= self.code_overlap < self.code_target and self.table_max > 0):
            raise ValueError("Invalid semantic chunk budgets")


@dataclass(frozen=True)
class ParentChunkDraft:
    parent_id: str
    content: str
    token_count: int
    heading_path: Tuple[str, ...]
    page_start: Optional[int]
    page_end: Optional[int]
    logical_key: str
    source_locator: dict


@dataclass(frozen=True)
class ChildChunkDraft:
    child_id: str
    parent_chunk_id: str
    child_order: int
    content: str
    token_count: int
    parent_start_offset: int
    parent_end_offset: int
    overlap_before_tokens: int
    node_type: str
    page_no: Optional[int]
    unsafe_split: bool
    logical_key: str
    heading_path: Tuple[str, ...]
    source_locator: dict


@dataclass(frozen=True)
class ChunkingResult:
    parents: List[ParentChunkDraft]
    children: List[ChildChunkDraft]


def boundaries(text, *, code=False, table=False):
    """Return exact offsets; periods inside identifiers/URLs never end units."""
    if code or table:
        return sorted({match.end() for match in re.finditer(r"\n", text)} | {len(text)})
    return sorted({match.end() for match in re.finditer(r"\n\s*\n|[。！？；](?:[”’）])?\s*|[.!?;](?:[\"')])?(?:\s+|$)", text)} | {len(text)})


def table_context(text, start, content):
    """Repeat the table header and the row label for a continued row in embeddings."""
    header = text.splitlines()[0]
    context = [] if content.startswith(header) else [header]
    row_start = text.rfind("\n", 0, start) + 1
    if start > row_start:
        row_end = text.find("\n", row_start)
        row = text[row_start:row_end if row_end >= 0 else len(text)]
        cells = row.split("|")
        label = cells[1].strip() if len(cells) > 2 else ""
        if label:
            context.append("Table row: " + label)
    return "\n".join(context)


class SemanticChunker:
    def __init__(self, *, tokenize, budget=None):
        self.tokenize = tokenize
        self.budget = budget or ChunkBudget()
        self.cache = {}

    def counts(self, texts):
        missing = list(dict.fromkeys(text for text in texts if text not in self.cache))
        if missing:
            counts = self.tokenize(missing)
            if len(counts) != len(missing) or any(type(n) is not int or n < 0 for n in counts):
                raise ParseError("TOKENIZER_RESPONSE_INVALID")
            self.cache.update(zip(missing, counts))
        return [self.cache[text] for text in texts]

    def count(self, text):
        return self.counts([text])[0]

    def windows(self, text, *, maximum, target, overlap=0, prefix=lambda text: text,
                prefix_at=None, code=False, table=False):
        primary = boundaries(text, code=code, table=table)
        safe = sorted({match.end() for match in re.finditer(r"\s+|[，。！？；,!?;]", text)} | set(primary))
        start, previous_end = 0, 0
        while start < len(text):
            render = (lambda value: prefix_at(value, start)) if prefix_at else prefix
            candidates = [end for end in primary if end > max(start, previous_end)]
            counts = self.counts([render(text[start:end]) for end in candidates])
            fits = [(end, count) for end, count in zip(candidates, counts) if count <= maximum]
            unsafe = False
            if not fits:
                # Prefer whole rows, but long cells must still fit the model budget.
                # Continued rows carry their header/label through prefix_at.
                candidates = [end for end in safe if end > max(start, previous_end)]
                counts = self.counts([render(text[start:end]) for end in candidates])
                fits = [(end, count) for end, count in zip(candidates, counts) if count <= maximum]
            if not fits and start < previous_end:
                start = previous_end
                continue
            if fits:
                target_fits = [item for item in fits if item[1] <= target]
                end = (target_fits or fits)[-1][0]
                if fits[-1][0] == len(text):
                    end = len(text)
            else:
                # A single unbroken token exceeds the budget. Never pretend it was a safe split.
                low, high, end = start + 1, min(safe or [len(text)]), start
                high = next((point for point in safe if point > start), len(text))
                while low <= high:
                    middle = (low + high) // 2
                    if self.count(render(text[start:middle])) <= maximum:
                        end, low = middle, middle + 1
                    else:
                        high = middle - 1
                if end <= start:
                    raise ParseError("CHUNK_QUALITY_FAILED", "Metadata prefix exceeds token budget.",
                                     details={"maximum_tokens": maximum, "start_offset": start})
                unsafe = True
            yield start, end, unsafe, self.count(text[start:previous_end]) if start < previous_end else 0
            if end == len(text):
                break
            previous_end = end
            choices = [point for point in primary if start < point < end]
            start = end
            for point in reversed(choices):
                if overlap and self.count(text[point:end]) <= overlap:
                    start = point
                else:
                    break

    def chunk(self, nodes, *, document_version_id, source_path, tokenizer_model="BAAI/bge-m3", chunking_version="2"):
        groups, group = [], []
        for node in nodes:
            if node.node_type in {NodeType.HEADING, NodeType.PAGE_BREAK}:
                if group:
                    groups.append(group)
                    group = []
                continue
            if not node.text.strip():
                continue
            special = node.node_type in {NodeType.CODE, NodeType.TABLE}
            if group and (group[-1].heading_path != node.heading_path or special
                          or group[-1].node_type in {NodeType.CODE, NodeType.TABLE}
                          or self.count("\n\n".join(item.text for item in group + [node])) > self.budget.parent_max):
                groups.append(group)
                group = []
            group.append(node)
        if group:
            groups.append(group)
        parents, children = [], []
        section_occurrences = {}
        for group in groups:
            text = "\n\n".join(node.text for node in group)
            heading = group[0].heading_path
            section_key = build_logical_chunk_key(source_path, heading)
            section_occurrences[section_key] = section_occurrences.get(section_key, 0) + 1
            kind = group[0].node_type
            code, table = kind == NodeType.CODE, kind == NodeType.TABLE
            positions, cursor = [], 0
            for node in group:
                positions.append((cursor, cursor + len(node.text), node))
                cursor += len(node.text) + 2
            parent_windows = list(self.windows(text, maximum=self.budget.parent_max, target=self.budget.parent_target, code=code, table=table))
            for parent_order, (pstart, pend, punsafe, _) in enumerate(parent_windows, 1):
                body = text[pstart:pend]
                key = "{0}#group-{1}#parent-{2}".format(section_key, section_occurrences[section_key], parent_order)
                parent_id = stable_id("par_", document_version_id, chunking_version, key, body)
                included = [node for start, end, node in positions if end > pstart and start < pend]
                pages = [node.page_no for node in included if node.page_no]
                locator = dict(included[0].source_locator)
                parents.append(ParentChunkDraft(parent_id, body, self.count(body), heading,
                    min(pages) if pages else None, max(pages) if pages else None, key, locator))
                def prefix(value, start):
                    context = table_context(text, pstart + start, value) if table else ""
                    return embedding_input(source_path, heading, value, context)
                maximum = self.budget.code_max if code else self.budget.table_max if table else self.budget.child_max
                target = self.budget.code_target if code else maximum if table else self.budget.child_target
                overlap = self.budget.code_overlap if code else 0 if table else self.budget.child_overlap
                try:
                    windows = list(self.windows(body, maximum=maximum, target=target,
                        overlap=overlap, prefix_at=prefix, code=code, table=table))
                except ParseError as error:
                    error.details.update({"page_no": included[0].page_no,
                                          "node_type": kind.value, "node_id": included[0].node_id})
                    raise
                if len(windows) > 1 and self.count(body[windows[-1][0]:]) < self.budget.minimum_child:
                    previous = windows[-2]
                    if self.count(prefix(body[previous[0]:], previous[0])) <= maximum:
                        windows[-2:] = [(previous[0], len(body), previous[2] or windows[-1][2], previous[3])]
                for order, (start, end, unsafe, overlap_tokens) in enumerate(windows, 1):
                    content = body[start:end]
                    child_key = key + "#child-" + str(order)
                    original = next((node for a, b, node in positions if b > pstart + start), included[0])
                    child_locator = dict(original.source_locator)
                    if table:
                        context = table_context(text, pstart + start, content)
                        if context:
                            child_locator["table_header"] = context
                        absolute_start, absolute_end = pstart + start, pstart + end
                        child_locator["table_row_split"] = (
                            (absolute_start > 0 and text[absolute_start - 1] != "\n")
                            or (absolute_end < len(text) and text[absolute_end - 1] != "\n")
                        )
                    children.append(ChildChunkDraft(
                        stable_id("chd_", document_version_id, chunking_version, child_key, content), parent_id, order,
                        content, self.count(prefix(content, start)), start, end, overlap_tokens, kind.value,
                        original.page_no, unsafe or punsafe, child_key, heading, child_locator,
                    ))
        if not children:
            raise ParseError("CHUNK_QUALITY_FAILED", "Document contains no retrieval content.")
        return ChunkingResult(parents, children)
