import json
import time
import timeit

DATA = {
    "tokens": 95.5,
    "last_update": time.time(),
    "bucket_size": 100,
    "refill_rate": 10.0,
    "metadata": {"user_id": 12345, "ip": "127.0.0.1"},
}


def benchmark_json():
    serialized = json.dumps(DATA)
    deserialized = json.loads(serialized)
    return deserialized


if __name__ == "__main__":
    print("Benchmarking JSON serialization...")
    timer = timeit.Timer(benchmark_json)
    number = 100000
    total_time = timer.timeit(number=number)
    print(f"JSON: {total_time:.4f}s for {number} iterations")
    print(f"Time per op: {total_time/number*1000:.4f} ms")
