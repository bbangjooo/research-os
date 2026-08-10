"""Data-only interpreters used by the frozen M1-C manifest observer.

The interpreters deliberately never receive a manifest or matrix case ID.  IDs
are pytest display labels only; behavior is selected by declared operations,
drivers, transforms, and patch data.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
Operation = Callable[[Mapping[str, Any]], dict[str, object]]
DeriveHandler = Callable[[Mapping[str, Any]], object]
RecomputeHandler = Callable[[object, str], object]
ControlHandler = Callable[[object], Mapping[str, object]]


class DuplicateKeyError(ValueError):
    """Raised when supposedly canonical JSON contains a duplicate object key."""


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def strict_load_json(path: Path) -> object:
    """Load canonical JSON while rejecting duplicate keys and non-finite values."""

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_constant,
    )


def strict_load_json_lines(path: Path) -> list[object]:
    """Load a JSONL corpus with the same duplicate-free canonical policy."""

    values: list[object] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line:
            raise ValueError(f"blank JSONL line {line_number} in {path}")
        values.append(
            json.loads(
                line,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
            )
        )
    return values


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sorted_compact_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256_bytes(encoded)


def _json_canonical_equal(left: object, right: object) -> bool:
    """Compare values in the public canonical-JSON equality domain."""

    from research_os.contracts import canonical_json_bytes

    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _pointer_tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"invalid RFC-6901 pointer: {pointer!r}")
    tokens: list[str] = []
    for encoded in pointer[1:].split("/"):
        decoded: list[str] = []
        index = 0
        while index < len(encoded):
            char = encoded[index]
            if char != "~":
                decoded.append(char)
                index += 1
                continue
            if index + 1 >= len(encoded) or encoded[index + 1] not in {"0", "1"}:
                raise ValueError(f"invalid RFC-6901 escape in {pointer!r}")
            decoded.append("~" if encoded[index + 1] == "0" else "/")
            index += 2
        tokens.append("".join(decoded))
    return tokens


def pointer_get(document: object, pointer: str) -> object:
    current = document
    for token in _pointer_tokens(pointer):
        if isinstance(current, list):
            if token == "-":
                raise KeyError("'-' is not readable")
            current = current[int(token)]
        elif isinstance(current, Mapping):
            current = current[token]
        else:
            raise KeyError(f"pointer traverses non-container at {token!r}")
    return current


def _pointer_parent(document: object, pointer: str) -> tuple[object, str]:
    tokens = _pointer_tokens(pointer)
    if not tokens:
        raise ValueError("root pointer has no parent")
    current = document
    for token in tokens[:-1]:
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, Mapping):
            current = current[token]
        else:
            raise KeyError(f"pointer traverses non-container at {token!r}")
    return current, tokens[-1]


def apply_patch(document: object, patch: Mapping[str, object]) -> object:
    """Apply one generic RFC-6901 add/remove/replace mutation."""

    operation = patch.get("op")
    pointer = patch.get("path")
    if operation not in {"add", "remove", "replace"}:
        raise ValueError(f"unsupported patch operation: {operation!r}")
    if not isinstance(pointer, str):
        raise TypeError("patch path must be text")
    if pointer == "":
        if operation == "remove":
            raise ValueError("cannot remove the document root")
        if "value" not in patch:
            raise KeyError("root patch requires value")
        return copy.deepcopy(patch["value"])

    parent, token = _pointer_parent(document, pointer)
    if isinstance(parent, list):
        if operation == "add":
            value = copy.deepcopy(patch["value"])
            if token == "-":
                parent.append(value)
            else:
                parent.insert(int(token), value)
        elif operation == "remove":
            parent.pop(int(token))
        else:
            parent[int(token)] = copy.deepcopy(patch["value"])
        return document
    if not isinstance(parent, dict):
        raise KeyError(f"patch parent is not a container: {pointer!r}")
    if operation == "add":
        parent[token] = copy.deepcopy(patch["value"])
    elif operation == "remove":
        del parent[token]
    else:
        if token not in parent:
            raise KeyError(f"replace target is absent: {pointer!r}")
        parent[token] = copy.deepcopy(patch["value"])
    return document


def _merge(parent: object, child: object, *, path: tuple[str, ...] = ()) -> object:
    if isinstance(parent, Mapping) and isinstance(child, Mapping):
        result = copy.deepcopy(dict(parent))
        for key, value in child.items():
            result[key] = (
                _merge(result[key], value, path=(*path, key))
                if key in result
                else copy.deepcopy(value)
            )
        return result
    if isinstance(parent, list) and isinstance(child, list):
        if path and path[-1] == "steps":
            return [*copy.deepcopy(parent), *copy.deepcopy(child)]
        return copy.deepcopy(child)
    return copy.deepcopy(child)


def _assert_subset(observed: object, expected: object, *, path: str = "$") -> None:
    if isinstance(expected, Mapping):
        if not isinstance(observed, Mapping):
            raise AssertionError(f"{path} is not an object")
        for key, value in expected.items():
            if key not in observed:
                raise AssertionError(f"{path}.{key} is absent")
            _assert_subset(observed[key], value, path=f"{path}.{key}")
        return
    if not _json_canonical_equal(observed, expected):
        raise AssertionError(f"{path}: expected {expected!r}, observed {observed!r}")


class OperationRegistry:
    """Dispatch manifest bindings solely on their declared operation."""

    def __init__(self) -> None:
        self._operations: dict[str, Operation] = {}

    def register(self, name: str, operation: Operation) -> None:
        if not name or name in self._operations:
            raise ValueError(f"duplicate or empty observer operation: {name!r}")
        self._operations[name] = operation

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._operations)

    def observe(self, case: Mapping[str, object]) -> dict[str, object]:
        operation = case.get("operation")
        inputs = case.get("input")
        if not isinstance(operation, str) or not isinstance(inputs, Mapping):
            raise TypeError("manifest case requires operation text and input object")
        try:
            observer = self._operations[operation]
        except KeyError as exc:
            raise AssertionError(f"unbound manifest operation: {operation}") from exc
        return observer(inputs)


class ProposalNegativeInterpreter:
    """Interpret Proposal negatives using transform data, never matrix case IDs."""

    def __init__(self, matrix: Mapping[str, Any], fixture_root: Path) -> None:
        self.matrix = matrix
        self.fixture_root = fixture_root

    @staticmethod
    def _generate(specification: Mapping[str, object]) -> str:
        kind = specification.get("kind")
        if kind == "repeat_text":
            text = specification.get("text")
            count = specification.get("count")
            if not isinstance(text, str) or any(0xD800 <= ord(char) <= 0xDFFF for char in text):
                raise ValueError("repeat_text requires Unicode scalar text")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("repeat_text count must be a non-negative integer")
            return text * count
        if kind == "unicode_code_point":
            value = specification.get("value")
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0x10FFFF:
                raise ValueError("unicode_code_point value is out of range")
            return chr(value)
        raise ValueError(f"unsupported generator kind: {kind!r}")

    def _transform(self, document: object, name: str) -> object:
        transforms = self.matrix.get("transforms")
        if not isinstance(transforms, Mapping) or name not in transforms:
            raise KeyError(f"unknown Proposal transform: {name!r}")
        transform = transforms[name]
        if not isinstance(transform, Mapping):
            raise TypeError("Proposal transform must be an object")
        operation = transform.get("operation")
        if operation == "replace_root":
            return copy.deepcopy(transform["value"])
        if operation != "replace_generated":
            raise ValueError(f"unsupported Proposal transform operation: {operation!r}")
        generator = transform.get("generator")
        pointer = transform.get("pointer")
        if not isinstance(generator, Mapping) or not isinstance(pointer, str):
            raise TypeError("replace_generated requires generator and pointer")
        generated = self._generate(generator)
        if "assert_code_points" in transform:
            assert len(generated) == transform["assert_code_points"]
        if "assert_utf8_bytes" in transform:
            assert len(generated.encode("utf-8")) == transform["assert_utf8_bytes"]
        return apply_patch(document, {"op": "replace", "path": pointer, "value": generated})

    def generate(self, specification: Mapping[str, object]) -> str:
        """Expose the same generic generator for positive manifest inputs."""

        return self._generate(specification)

    def materialize(self, case: Mapping[str, object]) -> object:
        base_fixture = self.matrix.get("base_fixture")
        if not isinstance(base_fixture, str):
            raise TypeError("Proposal matrix base_fixture must be text")
        document = copy.deepcopy(strict_load_json(self.fixture_root / base_fixture))
        transform = case.get("transform")
        if transform is not None:
            if not isinstance(transform, str):
                raise TypeError("Proposal transform name must be text")
            document = self._transform(document, transform)
        for pointer in case.get("remove", []):  # type: ignore[union-attr]
            document = apply_patch(document, {"op": "remove", "path": pointer})
        for operation in ("add", "replace"):
            changes = case.get(operation, {})
            if not isinstance(changes, Mapping):
                raise TypeError(f"Proposal {operation} changes must be an object")
            for pointer in sorted(changes):
                document = apply_patch(
                    document,
                    {"op": operation, "path": pointer, "value": changes[pointer]},
                )
        return document


class DocumentResolver:
    """Resolve transition profiles, scenarios, documents, refs, and patches."""

    def __init__(
        self,
        matrix: Mapping[str, Any],
        fixture_root: Path,
        *,
        derive_handlers: Mapping[str, DeriveHandler] | None = None,
        recompute_handlers: Mapping[str, RecomputeHandler] | None = None,
        control_handlers: Mapping[str, ControlHandler] | None = None,
    ) -> None:
        self.matrix = matrix
        self.fixture_root = fixture_root
        self.derive_handlers = dict(derive_handlers or {})
        self.recompute_handlers = dict(recompute_handlers or {})
        self.control_handlers = dict(control_handlers or {})
        self.control_observer_calls: dict[str, int] = {}

    def _named_parent(
        self,
        table_name: str,
        name: str,
        *,
        stack: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        table = self.matrix.get(table_name)
        if not isinstance(table, Mapping) or name not in table:
            raise KeyError(f"unknown {table_name} entry: {name!r}")
        if name in stack:
            raise ValueError(f"cyclic {table_name} inheritance: {(*stack, name)!r}")
        value = table[name]
        if not isinstance(value, Mapping):
            raise TypeError(f"{table_name}.{name} must be an object")
        parent_name = value.get("extends")
        local = {key: copy.deepcopy(item) for key, item in value.items() if key != "extends"}
        if parent_name is None:
            resolved = local
        else:
            if not isinstance(parent_name, str):
                raise TypeError(f"{table_name}.{name}.extends must be text")
            resolved = _merge(
                self._named_parent(table_name, parent_name, stack=(*stack, name)),
                local,
            )
            assert isinstance(resolved, dict)
        if table_name == "project_profiles":
            removals = resolved.pop("remove_capabilities", [])
            if removals:
                capabilities = resolved.get("adapter_capabilities")
                if not isinstance(capabilities, list) or not isinstance(removals, list):
                    raise TypeError("profile capability removal requires arrays")
                resolved["adapter_capabilities"] = [
                    item for item in capabilities if item not in removals
                ]
        return resolved

    def profile(self, name: str) -> dict[str, Any]:
        return self._named_parent("project_profiles", name)

    def scenario(self, name: str) -> dict[str, Any]:
        return self._named_parent("scenarios", name)

    def _document_spec(
        self,
        name: str,
        local_documents: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        if local_documents is not None and name in local_documents:
            value = local_documents[name]
        else:
            documents = self.matrix.get("documents")
            if not isinstance(documents, Mapping) or name not in documents:
                raise KeyError(f"unknown document: {name!r}")
            value = documents[name]
        if not isinstance(value, Mapping):
            raise TypeError(f"document {name!r} must be an object")
        return value

    def document(
        self,
        name: str,
        *,
        local_documents: Mapping[str, object] | None = None,
        captures: Mapping[str, object] | None = None,
        stack: tuple[str, ...] = (),
    ) -> object:
        if name in stack:
            raise ValueError(f"cyclic document reference: {(*stack, name)!r}")
        specification = self._document_spec(name, local_documents)
        sources = [key for key in ("fixture", "literal", "ref", "derive") if key in specification]
        if len(sources) != 1:
            raise ValueError(f"document {name!r} requires exactly one source")
        source = sources[0]
        if source == "fixture":
            fixture = specification[source]
            if not isinstance(fixture, str):
                raise TypeError("document fixture must be text")
            document = strict_load_json(self.fixture_root / fixture)
        elif source == "literal":
            document = copy.deepcopy(specification[source])
        elif source == "ref":
            reference = specification[source]
            if not isinstance(reference, str):
                raise TypeError("document ref must be text")
            document = self.document(
                reference,
                local_documents=local_documents,
                captures=captures,
                stack=(*stack, name),
            )
        else:
            derive = specification[source]
            if not isinstance(derive, Mapping):
                raise TypeError("document derive must be an object")
            operation = derive.get("operation")
            arguments = derive.get("arguments", {})
            if not isinstance(operation, str) or not isinstance(arguments, Mapping):
                raise TypeError("document derive requires operation and arguments")
            try:
                handler = self.derive_handlers[operation]
            except KeyError as exc:
                raise KeyError(f"unbound derive operation: {operation}") from exc
            document = handler(arguments)
            select = derive.get("select")
            if select is not None:
                if not isinstance(select, str):
                    raise TypeError("derive select must be a pointer")
                document = pointer_get(document, select)
            expected = specification.get("assert_derived")
            if expected is not None:
                _assert_subset(document, expected)

        source_document = copy.deepcopy(document)
        control = specification.get("control_assertions")
        if control is not None:
            if not isinstance(control, Mapping):
                raise TypeError("document control_assertions must be an object")
            observer = control.get("observer")
            if not isinstance(observer, str) or not observer:
                raise TypeError("document control_assertions requires observer text")
            try:
                handler = self.control_handlers[observer]
            except KeyError as exc:
                raise KeyError(f"unbound document control observer: {observer}") from exc
            expected_control = {
                key: copy.deepcopy(value) for key, value in control.items() if key != "observer"
            }
            observed_control = handler(copy.deepcopy(source_document))
            if not isinstance(observed_control, Mapping):
                raise TypeError("document control observer must return an object")
            _assert_subset(observed_control, expected_control)
            self.control_observer_calls[observer] = self.control_observer_calls.get(observer, 0) + 1
        patches = specification.get("patches", [])
        if not isinstance(patches, Sequence) or isinstance(patches, (str, bytes)):
            raise TypeError("document patches must be an array")
        for patch in patches:
            if not isinstance(patch, Mapping):
                raise TypeError("document patch must be an object")
            resolved_patch = self.resolve_value(
                patch,
                local_documents=local_documents,
                captures=captures,
            )
            assert isinstance(resolved_patch, Mapping)
            document = apply_patch(document, resolved_patch)
        recompute = specification.get("recompute", [])
        if not isinstance(recompute, Sequence) or isinstance(recompute, (str, bytes)):
            raise TypeError("document recompute must be an array")
        for field in recompute:
            if not isinstance(field, str) or field not in self.recompute_handlers:
                raise KeyError(f"unbound recompute field: {field!r}")
            document = self.recompute_handlers[field](document, field)
        absent = specification.get("assert_absent_json_pointers", [])
        for pointer in absent:
            try:
                pointer_get(document, pointer)
            except (KeyError, IndexError):
                pass
            else:
                raise AssertionError(f"derived document pointer must be absent: {pointer}")
        changed = specification.get("assert_only_changed_json_pointers")
        if changed is not None:
            observed = _changed_pointers(source_document, document)
            if observed != tuple(changed):
                raise AssertionError(f"derived document changed {observed}, expected {changed}")
        return copy.deepcopy(document)

    def resolve_value(
        self,
        value: object,
        *,
        local_documents: Mapping[str, object] | None = None,
        captures: Mapping[str, object] | None = None,
    ) -> object:
        if isinstance(value, Mapping):
            if "$doc" in value:
                name = value["$doc"]
                if not isinstance(name, str):
                    raise TypeError("$doc name must be text")
                document = self.document(
                    name,
                    local_documents=local_documents,
                    captures=captures,
                )
                for patch in value.get("patches", []):
                    assert isinstance(patch, Mapping)
                    resolved_patch = self.resolve_value(
                        patch,
                        local_documents=local_documents,
                        captures=captures,
                    )
                    assert isinstance(resolved_patch, Mapping)
                    document = apply_patch(document, resolved_patch)
                return document
            if "$ref" in value:
                reference = value["$ref"]
                if not isinstance(reference, str):
                    raise TypeError("$ref must be text")
                current: object = self.matrix
                for token in reference.split("."):
                    if not isinstance(current, Mapping):
                        raise KeyError(reference)
                    current = current[token]
                return copy.deepcopy(current)
            if "$capture" in value:
                reference = value["$capture"]
                if not isinstance(reference, str) or captures is None:
                    raise KeyError(f"unavailable capture: {reference!r}")
                current: object = captures
                for token in reference.split("."):
                    if not isinstance(current, Mapping):
                        raise KeyError(reference)
                    current = current[token]
                return copy.deepcopy(current)
            return {
                key: self.resolve_value(
                    item,
                    local_documents=local_documents,
                    captures=captures,
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self.resolve_value(
                    item,
                    local_documents=local_documents,
                    captures=captures,
                )
                for item in value
            ]
        return copy.deepcopy(value)


def _changed_pointers(left: object, right: object, pointer: str = "") -> tuple[str, ...]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        changed: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{pointer}/{key.replace('~', '~0').replace('/', '~1')}"
            if key not in left or key not in right:
                changed.append(child)
            else:
                changed.extend(_changed_pointers(left[key], right[key], child))
        return tuple(changed)
    if isinstance(left, list) and isinstance(right, list):
        return () if _json_canonical_equal(left, right) else (pointer,)
    return () if _json_canonical_equal(left, right) else (pointer,)
