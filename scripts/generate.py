#!/usr/bin/env python3
"""Write the generated half of the library from the Compliwa API's OpenAPI contract.

    src/compliwa/_generated/meta.py        every API-key operation: its SDK name, HTTP method, path,
                                           and what it takes (ids, a body, filters, pages, idempotency)
    src/compliwa/_generated/types.py       TypedDicts for every request and answer
    src/compliwa/_generated/resources.py   the resources and methods, sync and async, typed and documented

The names come from the contract itself (`x-sdk`, written by the API — compliwaAPI
src/openapi/sdkNames.js) and are turned into Python names (travelRule.transfers.confirm →
travel_rule.transfers.confirm), so this library, the Node.js one and the API reference cannot disagree.
Never edited by hand: change the API, then

    python scripts/generate.py                                  # ../compliwaAPI/openapi/dist/openapi.json
    python scripts/generate.py --spec http://localhost:5010/v1/openapi.json
    python scripts/generate.py --check                          # CI: fail if out of date

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import keyword
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "compliwa" / "_generated"
VERBS = ("get", "post", "put", "patch", "delete")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def snake(name: str) -> str:
    out = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).replace("-", "_").lower()
    return "delete" if out == "del" else out


def pascal(name: str) -> str:
    parts = re.split(r"[_\-\s.]+", re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name))
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def doc_text(text: str, indent: str) -> str:
    """A docstring body, safe and indented."""
    text = (text or "").strip().replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    if text.endswith('"'):
        text += " "  # a closing \"\"\" right after a quote would end the string early
    lines = text.split("\n")
    return "\n".join((indent + line) if line.strip() else "" for line in lines)


def load_spec(source: str) -> Dict[str, Any]:
    if re.match(r"^https?://", source):
        with urllib.request.urlopen(source) as res:  # noqa: S310 — the user's own API
            return json.load(res)
    return json.loads(Path(source).read_text(encoding="utf-8"))


class Generator:
    def __init__(self, doc: Dict[str, Any]) -> None:
        self.doc = doc
        self.schemas: Dict[str, Any] = doc.get("components", {}).get("schemas", {})
        self.used: Dict[str, str] = {}  # component → input | output | both
        self.blocks: List[str] = []  # emitted TypedDicts / aliases, in order
        self.emitted: set = set()
        self.inline_names: set = set()
        self.ops: List[Dict[str, Any]] = []

    # ---------------------------------------------------------------- operations
    def deref_param(self, p: Dict[str, Any]) -> Dict[str, Any]:
        if "$ref" in p:
            return self.doc["components"]["parameters"][ref_name(p["$ref"])]
        return p

    def collect_operations(self) -> None:
        for path, item in self.doc["paths"].items():
            for verb in VERBS:
                op = item.get(verb)
                sdk = (op or {}).get("x-sdk")
                if not sdk:
                    continue
                params = [self.deref_param(p) for p in item.get("parameters", []) + op.get("parameters", [])]
                ok = [r for status, r in op.get("responses", {}).items() if str(status).startswith("2")]
                self.ops.append(
                    {
                        "name": ".".join(sdk["resource"] + [sdk["method"]]),
                        "python": ".".join([snake(r) for r in sdk["resource"]] + [snake(sdk["method"])]),
                        "resource": [snake(r) for r in sdk["resource"]],
                        "method_py": snake(sdk["method"]),
                        "http": verb.upper(),
                        "path": path,
                        "path_params": sdk["path_params"],
                        "body": bool(sdk["body"]),
                        "body_required": bool(op.get("requestBody", {}).get("required")),
                        "query": bool(sdk["query"]),
                        "paginated": bool(sdk.get("paginated")),
                        "idempotent": bool(sdk.get("idempotent")),
                        "list": bool(sdk.get("list")),
                        "operation_id": op.get("operationId") or "",
                        "summary": op.get("summary", ""),
                        "description": op.get("description", ""),
                        "deprecated": bool(op.get("deprecated")),
                        "parameters": params,
                        "request_schema": op.get("requestBody", {})
                        .get("content", {})
                        .get("application/json", {})
                        .get("schema"),
                        "response_schemas": [
                            r.get("content", {}).get("application/json", {}).get("schema")
                            for r in ok
                            if r.get("content", {}).get("application/json", {}).get("schema")
                        ],
                    }
                )
        self.ops.sort(key=lambda o: o["python"])
        if not self.ops:
            sys.exit("The contract has no x-sdk names — is the API at step 12.4 or later?")

    # ---------------------------------------------------------------- types
    def component(self, name: str, mode: str) -> str:
        before = self.used.get(name)
        if before in (mode, "both"):
            return name
        self.used[name] = "both" if before else mode
        if name not in self.emitted:
            self.emitted.add(name)
            self.emit_named(name, self.schemas.get(name, {}), mode)
        return name

    def emit_named(self, name: str, schema: Dict[str, Any], mode: str) -> None:
        if self.is_object(schema) and schema.get("properties"):
            self.blocks.append(self.typed_dict(name, schema, mode))
        else:
            expr = self.py_type(schema, mode, name)
            doc = (
                f'\n"""{doc_text(schema.get("description", ""), "")}"""' if schema.get("description") else ""
            )
            self.blocks.append(f"{name}: TypeAlias = {json.dumps(expr)}{doc}")

    @staticmethod
    def is_object(schema: Dict[str, Any]) -> bool:
        t = schema.get("type")
        return (
            t == "object" or (isinstance(t, list) and "object" in t) or ("properties" in schema and t is None)
        )

    def inline_name(self, base: str) -> str:
        name, n = base, 2
        while name in self.inline_names or name in self.schemas:
            name, n = f"{base}{n}", n + 1
        self.inline_names.add(name)
        return name

    def py_type(self, schema: Any, mode: str, hint: str) -> str:
        if schema is True or schema is None or schema == {}:
            return "Any"
        if schema is False:
            return "NoReturn"
        if "$ref" in schema:
            return self.component(ref_name(schema["$ref"]), mode)
        if "const" in schema:
            return f"Literal[{self.literal(schema['const'])}]" if schema["const"] is not None else "None"
        if isinstance(schema.get("enum"), list):
            values = [v for v in schema["enum"] if v is not None]
            lit = f"Literal[{', '.join(self.literal(v) for v in values)}]" if values else "None"
            return f"Optional[{lit}]" if None in schema["enum"] else lit
        for key in ("anyOf", "oneOf"):
            if key in schema:
                return self.union([self.py_type(s, mode, hint) for s in schema[key]])
        if "allOf" in schema:
            return (
                self.py_type(schema["allOf"][0], mode, hint)
                if len(schema["allOf"]) == 1
                else "Dict[str, Any]"
            )
        t = schema.get("type")
        if isinstance(t, list):
            return self.union([self.py_type({**schema, "type": one}, mode, hint) for one in t])
        if t == "string":
            return "str"
        if t == "integer":
            return "int"
        if t == "number":
            return "float"
        if t == "boolean":
            return "bool"
        if t == "null":
            return "None"
        if t == "array":
            return f"List[{self.py_type(schema.get('items'), mode, hint + 'Item')}]"
        if self.is_object(schema):
            if schema.get("properties"):
                name = self.inline_name(hint)
                self.blocks.append(self.typed_dict(name, schema, mode))
                return name
            extra = schema.get("additionalProperties")
            if isinstance(extra, dict):
                return f"Dict[str, {self.py_type(extra, mode, hint + 'Value')}]"
            return "Dict[str, Any]"
        return "Any"

    @staticmethod
    def literal(value: Any) -> str:
        if isinstance(value, bool):
            return "True" if value else "False"
        return json.dumps(value) if isinstance(value, str) else repr(value)

    @staticmethod
    def union(types: List[str]) -> str:
        seen: List[str] = []
        for t in types:
            if t not in seen:
                seen.append(t)
        nullable = "None" in seen
        rest = [t for t in seen if t != "None"]
        core = rest[0] if len(rest) == 1 else (f"Union[{', '.join(rest)}]" if rest else "None")
        return f"Optional[{core}]" if nullable and rest else core

    def typed_dict(self, name: str, schema: Dict[str, Any], mode: str) -> str:
        required = set(schema.get("required", []))
        fields: List[Tuple[str, str, str]] = []
        for key, prop in schema.get("properties", {}).items():
            prop = prop if isinstance(prop, dict) else {}
            t = self.py_type(prop, mode, name + pascal(key))
            optional = key not in required or (mode == "input" and "default" in prop)
            if optional:
                t = f"NotRequired[{t}]"
            note = prop.get("description", "")
            if "default" in prop:
                note = (note + "\n\n" if note else "") + f"Default: {json.dumps(prop['default'])}"
            fields.append((key, t, note))
        desc = schema.get("description", "")
        if all(IDENT.match(k) and not keyword.iskeyword(k) for k, _, _ in fields):
            lines = [f"class {name}(TypedDict):"]
            if desc:
                lines.append(f'    """{doc_text(desc, "    ").lstrip()}"""')
                lines.append("")
            for key, t, note in fields:
                lines.append(f"    {key}: {t}")
                if note:
                    lines.append(f'    """{doc_text(note, "    ").lstrip()}"""')
            if not fields:
                lines.append("    pass")
            return "\n".join(lines)
        # A field named like a Python keyword (from, in …): the functional form, values quoted.
        body = ",\n".join(f"        {json.dumps(k)}: {json.dumps(t)}" for k, t, _ in fields)
        comment = f"# {desc.splitlines()[0]}\n" if desc else ""
        return f'{comment}{name} = TypedDict(\n    "{name}",\n    {{\n{body},\n    }},\n)'

    # ---------------------------------------------------------------- per-operation signatures
    def build_signatures(self) -> None:
        for op in self.ops:
            base = pascal(op["operation_id"] or op["python"].replace(".", "_"))
            params_type: Optional[str] = None
            params_required = False
            if op["body"]:
                rs = op["request_schema"]
                params_type = self.py_type(rs, "input", base + "Params") if rs else "Dict[str, Any]"
                params_required = op["body_required"]
            elif op["query"]:
                q = [p for p in op["parameters"] if p.get("in") == "query"]
                schema = {
                    "type": "object",
                    "properties": {
                        p["name"]: {**p.get("schema", {}), "description": p.get("description", "")} for p in q
                    },
                    "required": [p["name"] for p in q if p.get("required")],
                    "description": f"Filters for {op['python']}()",
                }
                params_type = self.inline_name(base + "Params")
                self.blocks.append(self.typed_dict(params_type, schema, "input"))
                params_required = bool(schema["required"])
            answer = (
                self.union([self.py_type(s, "output", base + "Response") for s in op["response_schemas"]])
                or "Dict[str, Any]"
            )
            item = "Any"
            if op["paginated"] and op["response_schemas"]:
                page = op["response_schemas"][0]
                page_schema = self.schemas.get(ref_name(page["$ref"]), {}) if "$ref" in page else page
                items = page_schema.get("properties", {}).get("data", {}).get("items")
                item = self.py_type(items, "output", base + "Item") if items else "Any"
            op.update(params_type=params_type, params_required=params_required, answer=answer, item=item)

    def docstring(self, op: Dict[str, Any], indent: str) -> str:
        first = op["description"].split("\n\n")[0].strip()
        scope = re.search(r"Needs `([a-z_.]+)`", op["description"])
        facts = f"{op['http']} {op['path']}" + (f" · scope {scope.group(1)}" if scope else "")
        if op["idempotent"]:
            facts += " · idempotent (retried safely)"
        text = "\n\n".join(t for t in (op["summary"], first, facts) if t)
        if op["deprecated"]:
            text += "\n\nDeprecated."
        return f'{indent}"""{doc_text(text, indent).lstrip()}\n{indent}"""'

    # ---------------------------------------------------------------- resources
    def tree(self) -> Dict[str, Any]:
        root: Dict[str, Any] = {}
        for op in self.ops:
            node = root
            for part in op["resource"]:
                if isinstance(node.get(part), dict) and "__op__" in node[part]:
                    raise SystemExit(f"{op['python']}: {part} is both a method and a resource")
                node = node.setdefault(part, {})
            if op["method_py"] in node:
                raise SystemExit(f"{op['python']}: the name is used twice")
            node[op["method_py"]] = {"__op__": op}
        return root

    def method(self, op: Dict[str, Any], is_async: bool) -> str:
        ids = [f"{snake(p)}: str" for p in op["path_params"]]
        args = ["self", *ids]
        if op["params_type"]:
            args.append(
                f"params: {op['params_type']}"
                if op["params_required"]
                else f"params: Optional[{op['params_type']}] = None"
            )
        args.append("**options: Unpack[RequestOptions]")
        ids_tuple = (
            "("
            + ", ".join(snake(p) for p in op["path_params"])
            + ("," if len(op["path_params"]) == 1 else "")
            + ")"
        )
        params_arg = "params" if op["params_type"] else "None"
        call = f'self._client._call("{op["name"]}", {ids_tuple}, {params_arg}, options)'
        doc = self.docstring(op, "        ")
        signature = ",\n        ".join(args)
        if op["paginated"]:
            page = f"AsyncPaginator[{op['item']}]" if is_async else f"SyncPage[{op['item']}]"
            return f"    def {op['method_py']}(\n        {signature},\n    ) -> {page}:\n{doc}\n        return {call}  # type: ignore[no-any-return]"
        if is_async:
            return f"    async def {op['method_py']}(\n        {signature},\n    ) -> {op['answer']}:\n{doc}\n        return await {call}  # type: ignore[no-any-return]"
        return f"    def {op['method_py']}(\n        {signature},\n    ) -> {op['answer']}:\n{doc}\n        return {call}  # type: ignore[no-any-return]"

    def resource_classes(self, node: Dict[str, Any], trail: List[str], is_async: bool, out: List[str]) -> str:
        prefix = "Async" if is_async else ""
        class_name = prefix + ("".join(pascal(p) for p in trail) + "Resource" if trail else "Resources")
        children = [(k, v) for k, v in node.items() if "__op__" not in v]
        methods = [v["__op__"] for k, v in node.items() if "__op__" in v]
        child_classes = [(k, self.resource_classes(v, trail + [k], is_async, out)) for k, v in children]
        client_type = "AsyncCompliwa" if is_async else "Compliwa"
        lines = [f"class {class_name}:"]
        lines.append(
            f'    """{"Every resource of the Compliwa API" if not trail else "client." + ".".join(trail)}"""'
        )
        lines.append("")
        for key, cls in child_classes:
            lines.append(f"    {key}: {cls}")
        if child_classes:
            lines.append("")
        lines.append(f'    def __init__(self, client: "{client_type}") -> None:')
        lines.append("        self._client = client")
        for key, cls in child_classes:
            lines.append(f"        self.{key} = {cls}(client)")
        for op in methods:
            lines.append("")
            lines.append(self.method(op, is_async))
        out.append("\n".join(lines))
        return class_name

    # ---------------------------------------------------------------- files
    def render(self) -> Dict[str, str]:
        self.collect_operations()
        self.build_signatures()
        version = self.doc["info"]["version"]
        head = f"# GENERATED by scripts/generate.py from the Compliwa API contract {version} — do not edit.\n"

        ops_rows = []
        for op in self.ops:
            row = {
                "name": op["name"],
                "python": op["python"],
                "method": op["http"],
                "path": op["path"],
                "path_params": op["path_params"],
            }
            for flag in ("body", "query", "paginated", "idempotent"):
                if op[flag]:
                    row[flag] = True
            ops_rows.append("    " + repr(row) + ",")
        meta = (
            head
            + '"""Which contract this library was generated from, and every operation an API key can call."""\n\n'
            + "from typing import Any, Dict, List\n\n"
            + f'API_VERSION = "{version}"\n\n'
            + "OPERATIONS: List[Dict[str, Any]] = [\n"
            + "\n".join(ops_rows)
            + "\n]\n"
        )

        types = (
            head
            + '"""Types for every request and answer: TypedDicts — the results are plain dicts, read with ["key"]."""\n\n'
            + "from __future__ import annotations\n\n"
            + "from typing import Any, Dict, List, NoReturn, Optional, Union\n\n"
            + "from typing_extensions import Literal, NotRequired, TypeAlias, TypedDict\n\n"
            + "__all__: List[str] = []\n\n\n"
            + "\n\n\n".join(self.blocks)
            + "\n"
        )

        sync_out: List[str] = []
        async_out: List[str] = []
        root = self.tree()
        self.resource_classes(root, [], False, sync_out)
        self.resource_classes(root, [], True, async_out)
        sync_out[-1] = sync_out[-1].replace("class Resources:", "class SyncResources:", 1)
        resources = (
            head
            + '"""Every resource and method, sync (Compliwa) and async (AsyncCompliwa)."""\n\n'
            + "from __future__ import annotations\n\n"
            + "from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union\n\n"
            + "from typing_extensions import Unpack\n\n"
            + "from .._options import RequestOptions\n"
            + "from .._pagination import AsyncPaginator, SyncPage\n"
            + "from .types import *  # noqa: F403\n\n"
            + "if TYPE_CHECKING:\n"
            + "    from .._client import AsyncCompliwa, Compliwa\n\n\n"
            + "\n\n\n".join(sync_out + async_out)
            + "\n"
        )
        # Every type name the methods use must be importable from types.py.
        names = sorted(
            {
                m.group(1)
                for m in re.finditer(
                    r"^(?:class )?([A-Z][A-Za-z0-9_]*)(?:\(TypedDict\)|: TypeAlias| = TypedDict)", types, re.M
                )
            }
        )
        types = types.replace(
            "__all__: List[str] = []", "__all__ = [\n" + "".join(f'    "{n}",\n' for n in names) + "]", 1
        )
        return {"meta.py": meta, "types.py": types, "resources.py": resources, "__init__.py": head}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--spec", help="the contract: a file or a URL")
    parser.add_argument("--check", action="store_true", help="fail if the generated files are out of date")
    args = parser.parse_args()
    candidates = [ROOT.parent / "compliwaAPI" / "openapi" / "dist" / "openapi.json", ROOT / "openapi.json"]
    source = args.spec or next((str(p) for p in candidates if p.exists()), None)
    if not source:
        sys.exit(
            "No contract found. Build it in the API folder (npm run openapi:build), or pass --spec <file or URL>."
        )
    gen = Generator(load_spec(source))
    files = gen.render()
    stale = False
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = OUT / name
        before = target.read_text(encoding="utf-8") if target.exists() else None
        if before == content:
            continue
        if args.check:
            print(f"✖ src/compliwa/_generated/{name} is out of date — run python scripts/generate.py")
            stale = True
            continue
        target.write_text(content, encoding="utf-8", newline="\n")
        print(f"  wrote src/compliwa/_generated/{name}")
    if stale:
        sys.exit(1)
    digest = hashlib.sha256("".join(files.values()).encode()).hexdigest()[:12]
    print(
        f"✔ API {gen.doc['info']['version']} · {len(gen.ops)} operations · {len(gen.used)} types · {digest}"
        + (" · up to date" if args.check else "")
    )


if __name__ == "__main__":
    main()
