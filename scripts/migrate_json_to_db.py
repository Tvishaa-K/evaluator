import glob
import json

from app.repository import save_result

RESULTS_DIR = "results"


def main():
    paths = sorted(glob.glob(f"{RESULTS_DIR}/*.json"))
    print(f"Found {len(paths)} result files")

    for path in paths:
        with open(path) as f:
            result = json.load(f)
        save_result(result)
        print(f"migrated {result['call_id']}")

    print("migration complete")


if __name__ == "__main__":
    main()
