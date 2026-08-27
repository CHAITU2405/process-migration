import time
import numpy as np

N = 1_000_000_000

# ---------------- CPU ----------------
print("Running on CPU...")

start = time.perf_counter()

# Count/sum numbers from 1 to N
# NumPy performs the computation efficiently in compiled CPU code.
cpu_result = np.arange(1, N + 1, dtype=np.int64).sum()

cpu_time = time.perf_counter() - start

print(f"CPU result: {cpu_result}")
print(f"CPU time: {cpu_time:.4f} seconds")


# ---------------- GPU ----------------
try:
    import cupy as cp

    print("\nRunning on GPU...")

    # Synchronize before starting the timer
    cp.cuda.Stream.null.synchronize()
    start = time.perf_counter()

    # Perform the same operation on the GPU
    gpu_result = cp.arange(1, N + 1, dtype=cp.int64).sum()

    # Synchronize so timing includes GPU computation
    cp.cuda.Stream.null.synchronize()
    gpu_time = time.perf_counter() - start

    print(f"GPU result: {gpu_result.item()}")
    print(f"GPU time: {gpu_time:.4f} seconds")

    print(f"\nGPU speedup: {cpu_time / gpu_time:.2f}x")

except ImportError:
    print("\nCuPy is not installed. GPU benchmark skipped.")
except Exception as e:
    print(f"\nGPU benchmark failed: {e}")