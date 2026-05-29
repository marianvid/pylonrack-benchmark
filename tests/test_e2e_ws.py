"""test_e2e_ws.py — End-to-end test simulating a UI client over WebSocket.

Starts the slot server in-process, connects as a fake UI, fires get_models,
get_resources, start_suite, then receives all suite events live.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets


WS_URL  = "ws://localhost:8767"


async def main() -> None:
    print("Connecting to slot server…")
    async with websockets.connect(WS_URL) as ws:
        # 1) Manifest
        await ws.send(json.dumps({"type": "manifest"}))
        m = json.loads(await ws.recv())
        print(f"Manifest: {m.get('name')} v{m.get('version')}, ui_url={m.get('ui_url')}")
        # Consume initial controls_update
        await ws.recv()

        # 2) Get models
        await ws.send(json.dumps({"type": "action", "control_id": "get_models"}))
        r = json.loads(await ws.recv())
        models = r["data"]["items"]
        print(f"Found {len(models)} models")
        small = [m for m in models
                 if "1B-Instruct-Q4_K_M" in m["full_path"] and "Q4_0_8_8" not in m["full_path"]]
        if not small:
            print("ERROR: no small model")
            return
        target = small[0]
        print(f"Selected: {target['display_name']} ({target['size_gb']} GB)")

        # 3) Start suite
        await ws.send(json.dumps({
            "type": "action",
            "control_id": "start_suite",
            "payload": {
                "selected_models": [{"full_path": target["full_path"], "size_gb": target["size_gb"]}],
                "profiles":        ["single"],
                "budget":          "quick",
                "mode":            "auto",
            },
        }))

        # 4) Receive everything until suite_complete
        suite_id = None
        run_count = 0
        winners_received = None

        while True:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=300))
            except asyncio.TimeoutError:
                print("TIMEOUT")
                break

            mtype = msg.get("type")
            if mtype == "controls_update":
                continue   # header updates, ignore
            if mtype == "pong":
                continue

            if mtype == "action_result":
                action = msg.get("action")
                data   = msg.get("data", {})

                if action == "start_suite":
                    if not data.get("ok"):
                        print(f"FAILED to start: {data}")
                        return
                    suite_id = data["suite_id"]
                    print(f"Suite started: {suite_id}, "
                          f"{data['total_runs']} runs, ETA {data['eta_seconds']}s")

                elif action == "suite_event":
                    t = data.get("type")
                    d = data.get("data", {})

                    if t == "suite_started":
                        print(f"  [event] suite_started: total={d.get('total_runs')}")

                    elif t == "suite_progress":
                        idx = d.get("run_index", 0)
                        tot = d.get("total_runs", 0)
                        cur = d.get("current", {})
                        print(f"  [event] suite_progress: {idx+1}/{tot} {cur.get('label')}")

                    elif t == "run_complete":
                        run = d.get("run", {})
                        run_count += 1
                        agg = run.get("aggregate", {})
                        if run.get("profile") == "single":
                            print(f"  [event] run_complete #{run_count}: "
                                  f"decode={agg.get('decode_tok_s')} TTFT={agg.get('ttft_ms')}")
                        else:
                            print(f"  [event] run_complete #{run_count}: "
                                  f"agg={agg.get('aggregate_tok_s')}")

                    elif t == "suite_complete":
                        winners_received = d.get("winners", {})
                        print(f"  [event] suite_complete: {d.get('duration_sec')}s")
                        print(f"          winners: {len(winners_received)} models")
                        break

                    elif t == "suite_aborted":
                        print(f"  [event] suite_aborted: {d}")
                        return

        # 5) Fetch suite details
        if suite_id:
            await ws.send(json.dumps({
                "type": "action",
                "control_id": "get_suite",
                "payload": {"suite_id": suite_id},
            }))
            r = json.loads(await ws.recv())
            suite = r["data"]["suite"]
            print()
            print(f"=== Fetched suite {suite_id} from history ===")
            print(f"  status:   {suite.get('status')}")
            print(f"  duration: {suite.get('duration_sec')}s")
            print(f"  runs:     {len(suite.get('runs', []))}")
            print(f"  winners:  {len(suite.get('winners', {}))}")


if __name__ == "__main__":
    asyncio.run(main())
