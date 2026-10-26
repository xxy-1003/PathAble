"""Export the shared AWS contract without constructing AWS clients or credentials."""
import json
from pathlib import Path

from .app import create_app


def contract():
    schema = create_app().openapi()
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}
    schema["security"] = [{"BearerAuth": []}]
    schema["info"]["description"] = (
        "Fixed-camera reports at B / B-C. See CONTRACT.md for endpoint scopes, "
        "identity allowlists, retry semantics and evidence boundaries. AWS deployment unverified.")
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if path.endswith("/health"):
                scopes = ["pathable/camera", "pathable/reviewer", "pathable/map"]
            elif path.startswith("/api/v2/map"):
                scopes = ["pathable/map", "pathable/reviewer"]
            elif method == "post" and path in ("/api/v2/photos", "/api/v2/reports", "/api/v2/uploads/presign"):
                scopes = ["pathable/camera"]
            elif path == "/api/v2/reports/{report_id}" and method == "get":
                scopes = ["pathable/camera", "pathable/reviewer"]
            else:
                scopes = ["pathable/reviewer"]
            operation["x-required-scopes-any-of"] = scopes
    return schema


if __name__ == "__main__":
    Path(__file__).with_name("openapi.json").write_text(
        json.dumps(contract(), indent=2) + "\n", encoding="utf-8")
