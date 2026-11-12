# Ollama Windows QA model benchmark — 2026-11-12

## Protocol

All models received the same 24 synthetic Windows QA cases in one batch. The
cases cover process, UI Automation, artifact/correlation, GitHub return,
package/manifest/identity, JSON/import/type, and subprocess failures. Scoring
requires a bare JSON array, exact allowed classification and owner values, and
an evidence excerpt copied exactly from the corresponding log.

The full cases, expected results, raw model responses, scorer output, and run
metrics are under `benchmarks/`. These fixtures contain no product secrets or
personal data. Models were run sequentially with `keep_alive: 0`.

## Results

| Model | Strict JSON | Classification | Owner routing | Critical misses | Hallucinated excerpts | Batch time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `windows-qa-analyst` v2 | 100% | 100% | 100% | 0 | 0 | 50.81 s |
| `windows-qa-analyst` v1 | 100% | 100% | 54.17% | 0 | 0 | 31.98 s |
| `qwen3:14b` | 100% | 100% | 54.17% | 0 | 0 | 38.36 s |
| `deepseek-coder-v2:16b-lite-instruct-q4_K_M` | 0% | 0% scored | 0% scored | 13 | 0 scored | 41.05 s |
| `library-coder:latest` | 0% | 0% scored | 0% scored | 13 | 0 scored | 25.70 s |
| `qwen3.5:9b-q4_K_M` | no response | not scored | not scored | not scored | not scored | empty twice |

DeepSeek and `library-coder` wrapped otherwise JSON-like output in Markdown
fences, which correctly fails the production bare-JSON contract. The local
`library-coder` also has a workspace-specific system prompt and is not a clean
QA default. `qwen3.5:9b` returned an empty `response` on both identical attempts
through the required wrapper, so retry stopped and the candidate remains
installed but is not selected.

The v2 owner-routing improvement was a bounded system-prompt change: evidence
transport/correlation failures route to Windows-E2E, host/runtime availability
failures route to infrastructure, and other product failures route to the
supplied APP/GAME/GAME_3D owner. Raw v1 output was retained for comparison.

## Resource observations

The host has an RTX 5070 Ti with 16,303 MiB VRAM. `qwen3:14b` is a 9.3 GB
Q4_K_M model and was observed fully GPU-loaded; the dedicated model reuses
those weights and adds only small configuration layers. The DeepSeek and
library candidates are approximately 10 GB each. `qwen3.5:9b-q4_K_M` occupies
approximately 6.5 GB across downloaded layers. No models were run concurrently,
and every benchmark request unloaded its model afterward.

Batch latency is recorded for relative comparison, not as an SLA. Real
production analysis sends a single bounded failure rather than 24 cases. A
strict-schema integration call through `qa_ai.analyzer` completed successfully;
the measured call produced a schema-valid, non-authoritative analysis and left
E2E/Store authority false.

## Decision

Default: `windows-qa-analyst` based on `qwen3:14b`.

Keep as candidates: `qwen3.5:9b-q4_K_M`, DeepSeek, and `library-coder`, but do
not use them as the default under the current protocol. Phase 1 keeps all
installed models. Promotion requires repeated strict-JSON success, zero
critical misses, zero unsupported excerpts, acceptable owner routing, and a
separate operational review of latency and VRAM contention.

This benchmark does not make AI authoritative and does not establish a product
E2E pass or Store readiness.
