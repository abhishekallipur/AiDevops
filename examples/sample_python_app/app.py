"""A tiny sample repository used to demonstrate the analyzer end to end.

It is intentionally small and self-contained. Analysis never executes any of
this code.
"""

from fastapi import FastAPI

app = FastAPI(title="sample service")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
