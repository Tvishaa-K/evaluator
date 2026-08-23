import os
import time

from app.pipeline import run_pipeline
from app.repository import save_result, get_result

CALLS_DIR = "calls"


def main():
    files = sorted(f for f in os.listdir(CALLS_DIR) if f.endswith(".mp3"))
    print(f"Found {len(files)} calls")

    for f in files:
        call_id = f.replace(".mp3", "")
        if get_result(call_id) is not None:
            print(f"skip {call_id} (already done)")
            continue

        print(f"processing {call_id}...")
        start = time.time()
        try:
            with open(os.path.join(CALLS_DIR, f), "rb") as fh:
                contents = fh.read()
            result = run_pipeline(contents, f)
            result["call_id"] = call_id
            result["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_result(result)
            print(f"done {call_id} in {time.time() - start:.0f}s")
        except Exception as e:
            print(f"FAILED {call_id}: {e}")

    print("batch complete")


if __name__ == "__main__":
    main()
