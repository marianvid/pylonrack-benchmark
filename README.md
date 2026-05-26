# pylonrack-benchmark

PylonRack slot application for benchmarking **llama.cpp** models — measures inference throughput (tok/s) with configurable parallel requests and parameters, persists results per model.

---

## What it does

- **Model dropdown** — scans your HuggingFace cache and lists all `.gguf` files
- **Parallel dropdown** — select number of simultaneous requests `[1, 2, 4, 8, 16, 24]`
- **Run button** — starts a benchmark: launches a dedicated llama-server instance, fires N parallel chat requests, measures throughput, shuts down the server
- **Status label** — shows last result (tok/s) or current state
- **Log panel** — full benchmark output including llama-server startup and request results
- **Persistence** — results saved per model in `~/.pylonrack/benchmark_results.json`, up to 10 runs per model

---

## Requirements

- Python 3.11+
- A working [llama.cpp](https://github.com/ggerganov/llama.cpp) build (`llama-server` binary)
- HuggingFace cache with `.gguf` model files
- [PylonRack](https://github.com/marianvid/pylonrack) installed

---

## Installation

### 1. Clone

```
git clone https://github.com/marianvid/pylonrack-benchmark
cd pylonrack-benchmark
```

### 2. Install dependencies

```
conda activate pylonrack
pip install -r requirements.txt
```

Or with any Python 3.11+:

```
pip install -r requirements.txt
```

Dependencies: `websockets`, `aiohttp`, `psutil`, `requests`

### 3. Configure

Copy and edit `settings.json`:

```json
{
  "llama_bin":    "/path/to/llama.cpp/build/bin/llama-server",
  "hf_cache":     "/path/to/HuggingFace/hub",
  "bench_port":   1235,
  "prompt":       "Explain the importance of 400GB/s memory bandwidth for LLM inference on Apple Silicon in 150 words.",
  "results_file": "~/.pylonrack/benchmark_results.json",
  "params": {
    "ctx_size":          32768,
    "parallel":          16,
    "batch_size":        2048,
    "ubatch_size":       256,
    "threads":           8,
    "n_gpu_layers":      99,
    "cache_reuse":       200,
    "flash_attn":        true,
    "cont_batching":     true,
    "spec_type":         null,
    "spec_ngram_size_n": null,
    "draft":             null,
    "reasoning_budget":  null,
    "enable_thinking":   null
  }
}
```

| Key | Description |
|-----|-------------|
| `llama_bin` | Absolute path to compiled `llama-server` binary |
| `hf_cache` | Absolute path to HuggingFace hub cache |
| `bench_port` | Port for the temporary benchmark llama-server (separate from your main instance) |
| `prompt` | The prompt sent to the model during benchmarking |
| `results_file` | Where benchmark results are stored |
| `params.ctx_size` | Context size for the benchmark server |
| `params.parallel` | Server slots (should be ≥ your max parallel requests) |
| `params.n_gpu_layers` | GPU layers offloaded to Metal |
| `params.flash_attn` | Enable Flash Attention |
| `params.cont_batching` | Enable continuous batching |
| `params.reasoning_budget` | Token budget for reasoning models (`null` = no limit) |
| `params.enable_thinking` | Force thinking on/off for models that support it (`null` = model default) |

`settings.json` is gitignored.

### 4. Update `rack.json` start command

```json
{
  "start": "/path/to/your/python3 server.py"
}
```

For conda:
```json
{
  "start": "conda run -n pylonrack python3 server.py"
}
```

---

## Adding to PylonRack

1. Open PylonRack (menu bar icon)
2. Click `+` in the slot list
3. Click **Browse…** and select this folder
4. Click **Add**
5. Press **▶** to activate

---

## Controls

| Control | Type | Description |
|---------|------|-------------|
| Model | Dropdown | Select from all `.gguf` files in HF cache |
| Parallel | Dropdown | Number of simultaneous requests: 1, 2, 4, 8, 16, 24 |
| Run | Button | Execute benchmark |
| Status | Label | Last result (tok/s) or current state |

---

## How a benchmark run works

1. Any stale process on `bench_port` is terminated
2. `llama-server` is launched on `bench_port` with the configured params
3. Waits up to 90 seconds for the server to become ready
4. Fires N parallel `POST /v1/chat/completions` requests simultaneously
5. Measures wall-clock time and total tokens generated
6. Computes throughput: `total_tokens / wall_time`
7. Stops `llama-server`
8. Result is shown in the status label and saved to `results_file`

The benchmark server runs on a **separate port** (`bench_port`) from your main llama-server — you can run a benchmark while your main instance stays running.

---

## Results storage

Results are stored in `~/.pylonrack/benchmark_results.json`:

```json
{
  "models": {
    "/path/to/model.gguf": {
      "params": { ... },
      "runs": [
        {
          "date": "2026-05-26 10:00",
          "tok_s": 244.5,
          "tokens": 1200,
          "elapsed": 4.91,
          "parallel": 16,
          "params": { ... }
        }
      ]
    }
  }
}
```

Up to 10 runs are kept per model (oldest are dropped).

---

## File structure

```
pylonrack-benchmark/
├── rack.json              ← PylonRack slot manifest
├── settings.json          ← local configuration (gitignored)
├── server.py              ← WebSocket server (PylonRack protocol)
├── config.py              ← configuration loader with defaults
├── model_scanner.py       ← HF cache scanner
├── benchmark_runner.py    ← llama-server lifecycle + async requests
├── results_store.py       ← JSON persistence
└── requirements.txt
```

---

## License

MIT — use freely, no warranty.
