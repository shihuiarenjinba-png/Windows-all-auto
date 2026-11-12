# Local Ollama environment audit — 2026-11-12

Read-only inventory was taken before implementation. No existing model was
deleted or replaced.

| Item | Observation | Initial disposition |
| --- | --- | --- |
| Ollama | 0.40.12 | KEEP |
| GPU | NVIDIA GeForce RTX 5070 Ti, 16,303 MiB | shared local resource |
| Free disk before candidate pull | approximately 302 GB on C: | sufficient |
| `qwen3:14b` | 9.3 GB, Q4_K_M, 14.8B, 40,960 model context | baseline / QA base |
| `nomic-embed-text:latest` | 274 MB | baseline embedding |
| `deepseek-coder-v2:16b-lite-instruct-q4_K_M` | 10 GB | comparison candidate |
| `library-coder:latest` | 10 GB, workspace-specific system prompt | keep; biased comparison only |
| `qwen3.5:9b-q4_K_M` | not initially installed; official candidate | pull and benchmark |
| `qwen3.6:35b-a3b-q4_K_M` | 23 GB | keep; excluded from phase-1 latency test |
| `glm-4.7-flash:q4_K_M` | 19 GB | keep; excluded from phase-1 test |
| `llama3.1:8b`, `qwen3:0.6b` | installed | keep |

The dedicated `windows-qa-analyst` model is a lightweight manifest/config
layer over the existing `qwen3:14b` weights. Benchmark results and the final
default/candidate decision are recorded separately after identical-case runs.
