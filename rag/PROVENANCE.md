# RAG provenance and regeneration

## 1. Corpus source

The included corpus has 137 cards and nine facets. Its filename ends in 138
for historical reasons; use `total_cards` and actual record counts.
Card provenance records case-relative filenames, selected file SHA256 values,
case tree/input digests and reviewed semantic sources. All 465 selected file
references matched the audited OFFBEAT source snapshot. The original local snapshot has a GPL license but no Git metadata. A later
upstream checkout at commit 80e84450a115b0c411e1bfa5d166379f6bf6c084
matched all 465 referenced files; installation now pins that upstream commit.
`source-files.json` records portable hashes and the corpus/license hashes.

Historical semantic review refers to MANDiFuel revision
`8140fb38b9ef73eb9762c6e7be5ef3bb53e27edc`, not an OFFBEAT upstream commit.
The optional `rebuild_case_cards.py` curation audit requires that historical
repository and matching OFFBEAT tree. Those historical manual-review inputs
are not bundled. They are not needed to run retrieval or regenerate the
complete index from the included reviewed corpus. This archive does not claim
to reproduce historical manual review without those inputs.

## 2. Offline verification and regeneration

From the project root with Python 3.12:

```bash
python3 rag/build_index.py --check
python3 rag/build_index.py
python3 rag/build_index.py --check
```

The first command verifies corpus/index consistency. The second deterministically
rebuilds taxonomy, vocabulary and manifest while reusing compatible stored
vectors. It requires neither API keys nor the historical repository.

## 3. Generate new vectors

Set `DASHSCOPE_API_KEY` in the process environment or a secret manager; never
commit its value. The following operation calls a paid external service:

```bash
export MANDIFUEL_RAG_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV=DASHSCOPE_API_KEY
python3 rag/build_index.py --refresh-embeddings --embedding-model text-embedding-v3 --embedding-dimension 1024
python3 rag/build_index.py --check
```

`build_index.py` encodes each card's `retrieval_text` through
`OpenAICompatibleClient.embed_texts` in `providers.py`. It validates counts
and dimensions, writes retrieval-text hashes beside vectors and hashes the
corpus and generated outputs in `index/manifest.json`. Online queries must
use exactly the same embedding model and dimension as the stored index.

The index declares text-embedding-v3, consistent with the original provider
code and subsequent configurations. Legacy import checked text and dimensions,
not independently authenticated provider request logs. Hosted models may
change; regenerated numerical vectors need not be bit-identical. Preserve
the resulting manifest for each release. No model weights are required.
The supplied standard-library implementation is sufficient for generation;
the original SDK-based RAG repository is not a runtime dependency.
