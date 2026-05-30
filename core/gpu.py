"""GPU acceleration module — detect, initialize, benchmark, and show GPU doing work."""

import os
import sys
import threading
import time

_available = False
_device_name = "CPU"
_device_id = -1
_torch = None
_gpu_stats = {"temp": 0, "util": 0, "memory_free": 0, "memory_total": 0}
_gpu_stats_lock = threading.Lock()
_stats_thread = None


def init():
    global _available, _device_name, _device_id, _torch, _stats_thread
    try:
        # Suppress ONNX Runtime warnings about TensorRT
        os.environ['ORT_TENSORRT_UNAVAILABLE'] = '1'
        import warnings
        warnings.filterwarnings('ignore', category=UserWarning, module='onnxruntime')
        
        import torch
        _torch = torch
        if torch.cuda.is_available():
            _available = True
            _device_id = torch.cuda.current_device()
            _device_name = torch.cuda.get_device_name(_device_id)
            os.environ["CUDA_VISIBLE_DEVICES"] = str(_device_id)
            torch.cuda.empty_cache()
            _warmup_gpu()
            _run_benchmark()
            # Initial query so first format_status() shows real values
            _query_nvidia_smi()
            mem = torch.cuda.mem_get_info(_device_id)
            with _gpu_stats_lock:
                _gpu_stats["memory_free"] = round(mem[0] / 1024 / 1024, 0)
                _gpu_stats["memory_total"] = round(mem[1] / 1024 / 1024, 0)
            print(f"[GPU] Initialized: {_device_name} (CUDA {torch.version.cuda})")
            # Start stats collection thread
            _stats_thread = threading.Thread(target=_stats_loop, daemon=True)
            _stats_thread.start()
        else:
            print("[GPU] CUDA not available, using CPU")
    except ImportError:
        print("[GPU] PyTorch not installed, using CPU")
    except Exception as e:
        print(f"[GPU] Init failed: {e}")


def _warmup_gpu():
    """Run a real compute warmup to initialize CUDA context and show GPU is used."""
    if not _available or _torch is None:
        return
    try:
        # Matrix multiply warmup — creates CUDA context and shows real GPU load
        a = _torch.randn(1000, 1000, device="cuda")
        b = _torch.randn(1000, 1000, device="cuda")
        for _ in range(10):
            c = a @ b
        _torch.cuda.synchronize()
        # Verify GPU compute works
        result_sum = c.sum().item()
        print(f"[GPU] Warmup: 1000x1000 matmul 10x = OK (sum={result_sum:.1f})")
    except Exception as e:
        print(f"[GPU] Warmup failed: {e}")


def _run_benchmark():
    """Run a visible GPU benchmark so user knows GPU is working."""
    if not _available or _torch is None:
        return
    try:
        size = 5000
        a = _torch.randn(size, size, device="cuda")
        b = _torch.randn(size, size, device="cuda")
        t0 = time.perf_counter()
        for _ in range(3):
            c = a @ b
        _torch.cuda.synchronize()
        t = time.perf_counter() - t0
        flops = 2 * (size ** 3) * 3 / t
        print(f"[GPU] Benchmark: {size}x{size} matmul 3x in {t*1000:.0f}ms ({flops/1e12:.1f} TFLOPS)")
        # Keep result alive
        _ = c.sum().item()
    except Exception as e:
        print(f"[GPU] Benchmark failed: {e}")


def _stats_loop():
    """Background thread: collect GPU stats every 5 seconds."""
    while True:
        time.sleep(5)
        try:
            if _available and _torch is not None:
                mem = _torch.cuda.mem_get_info(_device_id)
                free_mb = mem[0] / 1024 / 1024
                total_mb = mem[1] / 1024 / 1024
                # PyTorch doesn't expose temp/util directly, but nvidia-smi can
                util = _query_nvidia_smi()
                with _gpu_stats_lock:
                    _gpu_stats["memory_free"] = round(free_mb, 0)
                    _gpu_stats["memory_total"] = round(total_mb, 0)
                    _gpu_stats["util"] = util
                    _gpu_stats["device"] = _device_name
        except Exception:
            pass


def _query_nvidia_smi():
    """Query GPU utilization from nvidia-smi (non-blocking)."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            if len(parts) >= 2:
                util = int(parts[0])
                temp = int(parts[1])
                with _gpu_stats_lock:
                    _gpu_stats["util"] = util
                    _gpu_stats["temp"] = temp
                return util
    except Exception:
        pass
    return -1


def is_available():
    return _available


def device_name():
    return _device_name


def device():
    if _available and _torch is not None:
        return _torch.device("cuda")
    return _torch.device("cpu") if _torch else None


def to_gpu(tensor):
    if _available and _torch is not None and tensor is not None:
        return tensor.cuda()
    return tensor


def empty_cache():
    if _available and _torch is not None:
        _torch.cuda.empty_cache()


def get_stats():
    with _gpu_stats_lock:
        return dict(_gpu_stats)


def format_status() -> str:
    """Return a one-line GPU status string for HUD display."""
    if not _available:
        return "GPU: CPU"
    with _gpu_stats_lock:
        util = _gpu_stats.get("util", -1)
        temp = _gpu_stats.get("temp", 0)
        mem_free = _gpu_stats.get("memory_free", 0)
        mem_total = _gpu_stats.get("memory_total", 0)
    util_str = f"{util}%" if util >= 0 else "?"
    mem_pct = round((1 - mem_free / mem_total) * 100) if mem_total > 0 else 0
    # Extract short device name
    short = _device_name.replace("NVIDIA GeForce ", "").replace("Laptop GPU", "").strip()
    return f"GPU: {short.split()[-1] if short else '?'} | {util_str} | {mem_pct}% VRAM | {temp}°C"
