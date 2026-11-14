"""Verify the pinned model and warm it up in the local GPU Compose stack."""

from bench.e2e_v32_20261114.runtime import (
    MODELS,
    ModelUnavailableError,
    api,
    require_gpu,
    require_pinned_model,
)


def main() -> None:
    try:
        require_pinned_model(api("/api/tags", timeout=10))
        api(
            "/api/generate",
            {
                "model": MODELS["4b"],
                "stream": False,
                "keep_alive": "10m",
                "options": {"num_ctx": 8192},
            },
            timeout=120,
        )
        require_gpu()
    except ModelUnavailableError as error:
        raise SystemExit(f"v3.2 model readiness check failed: {error}") from error
    print("Pinned v3.2 model is loaded on the NVIDIA GPU.")


if __name__ == "__main__":
    main()
