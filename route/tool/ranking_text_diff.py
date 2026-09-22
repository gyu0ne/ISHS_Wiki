"""Unicode edit alignment without a per-comparison timeout."""

from typing import assert_never

from rapidfuzz.distance import Indel


class ContributionDiffer:
    def diff_main(self, old: str, new: str) -> list[tuple[int, str]]:
        parts: list[tuple[int, str]] = []
        for operation in Indel.opcodes(old, new):
            match operation.tag:
                case 'equal':
                    parts.append((0, old[operation.src_start:operation.src_end]))
                case 'delete' | 'insert' | 'replace':
                    if operation.src_end > operation.src_start:
                        parts.append((-1, old[operation.src_start:operation.src_end]))
                    if operation.dest_end > operation.dest_start:
                        parts.append((1, new[operation.dest_start:operation.dest_end]))
                case unreachable:
                    assert_never(unreachable)
        return parts
