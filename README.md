# RDR2 horse YED converter

An **independent, experimental** converter for editing the inspected RDR2 horse expression dictionary. Written in Python using only its standard library. It does not install, import, invoke or bundle CodeX, Oodle DLLs, game files or any other third-party conversion engine.

**Current scope:** DEFLATE-compressed RSC8 horse YED files with the layout/opcodes exercised by our 39-expression horse dictionary. Native **Oodle-compressed game exports are not supported**. This is not a universal YED converter or an archive extractor.

It exports its own editable `HorseYed` XML, then rebuilds a YED while preserving opaque metadata. It does **not** import CodeX's `RDR2ExpressionDictionary` XML. A Python runtime is required; no `pip install` or separate packages are needed.

## Use

Python 3.10 or newer; tested with Python 3.14 on Windows. Download `yed.py`, then:

```console
python yed.py self-check
python yed.py inspect horse.yed
python yed.py export horse.yed horse.xml
python yed.py build horse.xml horse-edited.yed
```

Choose fresh output paths: existing files are never overwritten. The tool only reads the specified input and writes the specified output. It does not find game installations, extract archives, deploy to a server or edit your Blender template.

Use a DEFLATE RSC8 copy you already possess. Earlier working custom YEDs from our horse experiments use this compression. Having such a file does not require CodeX to be installed or available when this tool runs. If your only input is an untouched Oodle-compressed game file, this version cannot open it; an independent Oodle decoding solution is future work, not a hidden dependency.

## Editing

Export first and keep the `<Base>` element intact. It holds the original file plus a hash, allowing the builder to preserve dictionary identity, unknown fields, properties, springs, variables and unrelated allocation bytes. Consequently, **generated XML contains the input asset**; it is not just a small instruction patch. No generated XML or game binaries are included in this repository.

The editable portion exposes existing expressions, their register count, track table, stream depth and instructions:

- `Op` identifiers are labels. Branches point to labels, so operand displacements are recalculated when instructions or operand lengths change.
- Opcode `0x05` exposes one float; `0x0b` exposes a four-float vector.
- Opcode `0x52` exposes a register slot. Its interpretation as register storage is inferred.
- Opcode `0x50` exposes a four-float bias and coefficient terms. Each `Term` has twelve floats (three four-float vectors) and four register indices. Its interpretation as affine blending is inferred.
- Other supported instructions preserve exact operand bytes in hexadecimal `a` and `b` attributes. Editing those requires knowledge of their binary fields.
- Track records expose `bone`, `track` and `flags`. Expression-input IDs can occupy the `bone` field; they are not necessarily skeleton bone IDs.

New instructions require unique labels. Adding an input track and register is possible, but the tool does not design the expression graph, allocate registers for you or establish a visually safe slider range. Keep the final End opcode. Do not assume an arbitrary ID or coefficient is valid just because it packs into the file.

Expression/stream creation, removal and renaming, new variables/springs/properties, physical pages, multiple virtual pages and unknown opcodes are outside this version's scope. Existing opaque structures are retained. This is a preservation-oriented editor, not a compiler that creates a complete dictionary from an empty XML document.

When a stream or track array grows, the writer appends it and updates its pointer. It does not compact the entire resource. Repeated growth increases file size; inputs/decoded payloads are limited to 32 MiB.

## Verification and limits

Locally checked on 24 September 2026:

- Four DEFLATE fixtures: corrected stock, curl, curl plus stance, and curl/stance/width/hook. Every unchanged export/build returned the exact original bytes.
- Rebuilt the four-control candidate from the stock base by transferring editable track/instruction records. The resulting tracks, streams and exposed metadata matched the existing candidate.
- An external reader independently reopened that rebuilt output and matched all 39 expressions' streams, tracks and compared scalar metadata. This was a development cross-check; that reader is not a runtime dependency or part of this repository.
- Rejected unsupported Oodle input, truncated compression, unknown opcodes, missing branch targets, register-count overflow, modified base hashes and XML DTDs.
- The built-in `self-check` exercises the relative branch origin and missing-target rejection without game assets.

The earlier CodeX-assisted corrected stock/curl/stance assets were confirmed in game. **Edited files produced by this independent writer have not yet been tested in game.** Byte-exact unchanged round trips inherit the input bytes; the cross-reader check of relocated output is structural evidence, not runtime proof. Width/hook behavior is also awaiting in-game confirmation.

The supported operand sizes were measured in this horse corpus. An unfamiliar YED may be rejected; even a file which parses is not guaranteed to work in game. See [FORMAT.md](FORMAT.md) for scope and the branch-origin findings, and [Custom_Horse](https://github.com/shauna-lynn/Custom_Horse) for horse research.

## Ownership and dependencies

The Python implementation was written for this project. Format understanding came from local binary/XML comparisons and inspection of the existing reader/writer behavior, including CodeX. This is not a claim of a clean-room research process. No CodeX implementation, patch, source, assemblies or strings database is distributed here. No compression DLLs or game assets are distributed here.

This replaces an earlier private PowerShell wrapper which **did** depend on CodeX; the wrapper is not this project.

Copyright 2026 shauna-lynn. All rights reserved. No reuse licence has been granted for this project's code at this time. No licence over third-party software or game assets is offered or implied.
