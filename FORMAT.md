# Inspected format and preservation strategy

These are observations about the inspected horse YEDs, not an official or complete Rockstar specification. Numeric offsets and sizes below are file-format facts. Semantic names for unknown operations remain provisional.

## Container

The inspected files have a 16-byte little-endian RSC8 header. The word at offset 4 contains a resource identifier in its low byte and `(compression ID - 1)` in bits 8..12. Compression ID 1 is raw DEFLATE in the rebuilt fixtures; the original game export uses ID 2 (Oodle). The virtual and physical size/flag words are at offsets 8 and 12; their low nibbles are preserved separately from the size.

This implementation accepts DEFLATE, no encryption/signature flags, no physical data and a single virtual page in the resource block map. It preserves the incoming resource identifier and flag nibbles. It does not assume that changing an identifier alone converts between format versions.

Virtual pointers in this corpus address payload offsets relative to `0x50000000`. Pointer/count records use a 64-bit pointer followed by 16-bit count and capacity fields, with preserved trailing bytes. The dictionary at payload offset zero includes a string record at `0x38`, a bucket-array record at `0x48`, and total entry count at `0x58`. Bucket entries link to an expression at entry offset 8 and the next entry at offset 16. Cycles/shared entries are rejected.

An inspected expression is 160 bytes. Stream-pointer and track-array records are at `0x30` and `0x40`. Track records occupy four bytes: a 16-bit ID, track byte and type/flag byte. The expression string record is at `0x70`; maximum stream size is at `0x88`, and the inferred register-count field is at `0x8e`. Other expression bytes remain from the base file, including the unknown scalar at `0x80`.

## Instructions

A stream starts with a 16-byte header: 32-bit name hash, 32-bit Data1 byte length, 32-bit Data2 byte length, 16-bit opcode count and 16-bit depth. The three buffers follow in that order. There is one opcode byte per instruction; operand bytes live in Data1 and Data2.

Fixed operand widths are restricted to those observed in the local horse corpus. Opcode `0x50` has a variable operand block: a 32-byte prefix, 56 bytes per term, and eight padding bytes when its term count is odd. Each term contributes three four-float vectors and four 16-bit register indices. Counts and byte lengths must agree.

For the 1,027 `0x2b` and two `0x2c` instructions in the inspected stock dictionary, the Data2 operand is three signed 32-bit relative displacements. For instruction index `i` and third operand `r`:

```text
target index = i + 1 + r
first operand = target Data1 offset - current Data1 offset
second operand = target Data2 offset - current Data2 offset - 12
```

All 1,036 occurrences of `0x70` in the same decoded stock corpus also matched this exact displacement relationship. The new tool therefore treats their destinations as labels too. This additional structural observation does not establish the opcode's complete runtime semantics.

The XML builder computes buffer positions first, then resolves labels using these origins. The reader validates that stored byte displacements agree with the destination instruction. It rejects unknown opcodes rather than assuming they have no operands.

## What is preserved

The XML embeds a hashed base file, keeping opaque resource structures available without reimplementing them. Unchanged builds return that exact file. Modified builds keep all existing allocations, overwrite blocks that still fit, append growing blocks, and change the relevant pointers/counts. The virtual size grows with 64 KiB padding for larger resources. The result is DEFLATE-compressed again.

The builder deliberately does not infer new property maps, dictionary hash buckets, spring records, variable tables or skeleton data. It supports editing existing expressions, not arbitrary dictionary construction. Its relocation output still needs a game test.
