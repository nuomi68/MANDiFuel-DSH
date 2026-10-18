# Third-party notices

## 1. OFFBEAT case descriptions

The corpus `rag/data/offbeat_case_cards_compact_138.json` contains 137 cards
curated from OFFBEAT examples, with original engineering labels, descriptions,
exclusions and evidence hashes. Attribution: foam-for-nuclear project /
OFFBEAT contributors. The historical filename does not indicate current count.

- Upstream: https://gitlab.com/foam-for-nuclear/offbeat
- License: GPL-3.0-or-later; the complete GPL v3 text is in `LICENSE`.
- Upstream notice: https://gitlab.com/foam-for-nuclear/offbeat/-/blob/develop/LICENSE

The corpus and original curation are provided under GPL-3.0-or-later to the
extent copyright applies, preserving upstream rights. The examples contain engineering requests and a launcher. Runnable reference
cases are selected through RAG from a separately installed OFFBEAT source tree.
The package includes no OFFBEAT executable, library or source-case input trees. Install the
solver and cases separately; preserve their own copyright and license notices,
including notices of any components bundled by upstream. The original source snapshot was identified by content; a later check matched
all 465 referenced files to upstream commit
80e84450a115b0c411e1bfa5d166379f6bf6c084, now used for installation.
See `rag/PROVENANCE.md` and `rag/source-files.json`.

## 2. Description embeddings and hosted services

The checked-in index declares Alibaba Cloud Model Studio (DashScope)
`text-embedding-v3`, 1024 dimensions, 137 vectors generated from card retrieval
texts. Original provider code, later configuration and current index agree
on this identifier; original request logs are not included. This does not
identify a particular open-weight Qwen model. A QWEN_API_KEY environment
variable alias in a related development configuration is not a model version.

Numerical vectors are supplied with project data to the extent contributors
hold rights in them. This does not relicense a hosted service, model weights
or underlying third-party rights. No model weights, provider SDK, API keys
or service entitlement are included. New requests require the user's account
and compliance with the applicable provider agreement. No special provider
authorization is claimed. The project's GPL does not replace service terms.

- API: https://www.alibabacloud.com/help/en/model-studio/embedding
- China agreement: https://terms.alicdn.com/legal-agreement/terms/common_platform_service/20230728213935489/20230728213935489.html
- Service notes: https://help.aliyun.com/zh/model-studio/bailian-service-notes

RAG uses Python's standard library and configurable compatible endpoints.
Changing the model requires regenerating all stored vectors and using the
same model for online queries. Generation is documented in `rag/PROVENANCE.md`.

## 3. Separately installed prerequisites

DeepSeek DSH, Node.js, Python, OpenFOAM and OFFBEAT are installed separately
and are not redistributed in this package. Optional study methods may use
SciPy, Optuna or Nevergrad. Tools in `requirements-examples.txt` are also installed
separately. Their own licenses govern their distributions. Product names
identify compatibility and data sources; no endorsement is implied.
