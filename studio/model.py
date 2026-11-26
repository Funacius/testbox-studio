"""Ordered workspace tree; independent of Tk and browser execution."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from gradebook.config import ROOT
from automation.schema import is_script, script_data, script_record, validate_records as parse_rows

WORKFLOWS = ("steps", "create", "validation", "cancel", "recover", "duplicate")
GROUPS = {"create": "01 · Create & persistence", "validation": "02 · Validation",
          "cancel": "03 · Cancel", "recover": "04 · Error recovery", "duplicate": "05 · Duplicate ID"}


def folder(name: str) -> dict:
    return {"uid": uuid4().hex, "kind": "folder", "name": name, "children": []}


def testcase(record: dict, steps: list | None = None) -> dict:
    return {"uid": uuid4().hex, "kind": "case", "name": record["title"],
            "record": deepcopy(record), "steps": deepcopy(steps or [])}


def template_record(case_id: str, workflow: str = "create") -> dict:
    if workflow == "steps":
        return script_record(case_id)
    fields = {"itemname": "New grade item", "idnumber": "F003-" + case_id,
              "grademin": "0", "grademax": "100"}
    inputs = {"fields": fields, "grade_type": "Value", "selects": {}, "checks": {}, "dates": {}}
    expected = {"saved": {"fields": deepcopy(fields), "grade_type": "Value",
                           "selects": {}, "checks": {}, "dates": {}}}
    description = "The item is saved with the expected values; cleanup restores the baseline."
    if workflow in {"validation", "recover"}:
        fields.update(grademin="100", grademax="100")
        expected["error"] = {"field": "grademin", "text": "The minimum must be lower than the maximum"}
        description = "Visible inline relation error; no invalid item is saved."
    if workflow == "recover":
        inputs["recovery"] = {"grademin": "0", "grademax": "100"}
        description = "Visible relation error, followed by successful correction and save on the same form."
    if workflow == "duplicate":
        inputs["duplicate_name"] = "Duplicate ID attempt"
        expected["error"] = {"field": "idnumber", "text": "This ID number is already taken"}
        description = "The original item is saved; a second item with the same ID is rejected."
    if workflow == "cancel":
        expected["grade_type_options"] = ["Value", "Scale", "Text"]
        description = "Exactly Value, Scale and Text are offered; cancelling creates no item."
    return {"case_id": case_id, "title": "New test case", "workflow": workflow,
            "item_name": fields["itemname"], "minimum": fields["grademin"], "maximum": fields["grademax"],
            "grade_type": "Value", "inputs_json": json.dumps(inputs, ensure_ascii=False),
            "expected_json": json.dumps(expected, ensure_ascii=False), "expected_result": description,
            "precondition": "Editing teacher, Course 1, Gradebook fixture from Project 2.",
            "notes": "", "known_defect": "", "source_sheet": "", "source_row": ""}


def planned_steps(record: dict) -> list[dict]:
    """Derive the preview from effective CSV data, not a separately editable script."""
    if is_script(record):
        return [dict(action=f"[{s['phase']}] {s['command']} {s['target']} {s['value']}", expected=s["expected"])
                for s in script_data(record)["steps"]]
    from gradebook.data import parse_rows as parse_gradebook
    case = parse_gradebook([record])[0]
    inputs, expected = case.inputs, case.expected
    steps = [dict(action="Log in as teacher and open Gradebook", expected="Gradebook is available"),
             dict(action="Record existing manual-item IDs", expected="Baseline recorded for isolated cleanup"),
             dict(action="Open full New grade item form", expected="Value defaults; Scale disabled"),
             dict(action=f"Enter Item name = {inputs['fields']['itemname']!r}; run-specific ID number", expected="Exact input text, including whitespace"),
             dict(action=f"Select grade type {inputs['grade_type']}", expected="Dependent controls have the correct enabled states")]
    if inputs.get("scale"):
        steps.append(dict(action=f"Select scale: {inputs['scale']}", expected="Named scale selected"))
    for key, value in inputs["fields"].items():
        if key not in {"itemname", "idnumber", "aggregationcoef2"}:
            steps.append(dict(action=f"Enter {key} = {value!r}", expected="Specified input value"))
    for key in ("checks", "selects", "dates"):
        for name, value in inputs[key].items():
            steps.append(dict(action=f"Set {name} = {value}", expected="Configured option/state"))
    if "aggregationcoef2" in inputs["fields"]:
        steps.append(dict(action=f"Enter aggregationcoef2 = {inputs['fields']['aggregationcoef2']!r}", expected="Weight override enabled before entering the weight"))
    if case.workflow == "cancel":
        steps.extend([dict(action="Inspect Grade type options", expected=str(expected["grade_type_options"])),
                      dict(action="Cancel creation", expected="No additional item")])
    elif case.workflow == "validation":
        steps.append(dict(action="Save and inspect inline validation", expected=expected["error"]["text"]))
        steps.append(dict(action="Cancel and return to Gradebook", expected="No additional item; original manual-item IDs unchanged"))
    elif case.workflow == "recover":
        steps.extend([dict(action="Save invalid data", expected=expected["error"]["text"]),
                      dict(action=f"Correct on the same form: {inputs['recovery']}", expected="Corrected data entered"),
                      dict(action="Save, reopen and verify", expected=json.dumps(expected["saved"], ensure_ascii=False))])
    else:
        steps.append(dict(action="Save, reopen and verify", expected=json.dumps(expected["saved"], ensure_ascii=False)))
        if case.workflow == "duplicate":
            steps.extend([dict(action="Create second item with the same runtime ID", expected=expected["error"]["text"]),
                          dict(action="Reopen original item", expected="Original data unchanged")])
    steps.append(dict(action="Clean up any items owned by this case", expected="Original baseline restored"))
    return steps


@dataclass
class Workspace:
    name: str = "Gradebook workspace"
    nodes: list[dict] = field(default_factory=list)
    settings: dict = field(default_factory=dict)

    def walk(self, nodes=None, path=()):
        for node in self.nodes if nodes is None else nodes:
            yield node, path
            if node["kind"] == "folder":
                yield from self.walk(node["children"], path + (node["name"],))

    def find(self, uid: str) -> dict:
        return next(node for node, _ in self.walk() if node["uid"] == uid)

    def container(self, uid: str) -> list[dict]:
        def search(nodes):
            for node in nodes:
                if node["uid"] == uid:
                    return nodes
                if node["kind"] == "folder":
                    result = search(node["children"])
                    if result is not None:
                        return result
            return None
        result = search(self.nodes)
        if result is None:
            raise KeyError(uid)
        return result

    def parent_uid(self, uid: str) -> str | None:
        container = self.container(uid)
        return next((n["uid"] for n, _ in self.walk() if n["kind"] == "folder" and n["children"] is container), None)

    def children(self, parent: str | None) -> list[dict]:
        if parent is None:
            return self.nodes
        node = self.find(parent)
        if node["kind"] != "folder":
            raise ValueError("The destination must be a folder")
        return node["children"]

    def next_case_id(self, reserved=()) -> str:
        used = {n["record"]["case_id"] for n, _ in self.walk() if n["kind"] == "case"} | set(reserved)
        n = 1
        while f"TC-{n:03}" in used:
            n += 1
        return f"TC-{n:03}"

    def add(self, node: dict, parent: str | None = None) -> str:
        self.children(parent).append(node)
        return node["uid"]

    def move(self, uid: str, parent: str | None, index: int | None = None) -> None:
        node = self.find(uid)
        descendants = {n["uid"] for n, _ in self.walk([node])}
        if parent in descendants:
            raise ValueError("A folder cannot be moved inside itself or a descendant")
        source, target = self.container(uid), self.children(parent)
        old_index = source.index(node)
        if source is target and index is not None and old_index < index:
            index -= 1
        source.remove(node)
        target.insert(len(target) if index is None else max(0, min(index, len(target))), node)

    def rows(self, selected: list[str] | None = None) -> list[dict]:
        chosen = set(selected) if selected else None
        included = set()
        if chosen is not None:
            for uid in chosen:
                included.update(n["uid"] for n, _ in self.walk([self.find(uid)]))
        rows = []
        for node, path in self.walk():
            if node["kind"] != "case" or chosen is not None and node["uid"] not in included:
                continue
            row = deepcopy(node["record"])
            row.update(folder_path=" / ".join(path), folder_path_json=json.dumps(path, ensure_ascii=False),
                       order=str(len(rows) + 1), steps_json=json.dumps(node.get("steps", []), ensure_ascii=False))
            rows.append(row)
        return rows

    def import_rows(self, rows: list[dict], parent: str | None) -> tuple[int, int]:
        parse_rows(rows)
        if any(row.get("order") for row in rows):
            try:
                rows = sorted(rows, key=lambda row: int(row.get("order") or "0"))
            except ValueError as exc:
                raise ValueError("The order column must contain whole numbers") from exc
        used = {n["record"]["case_id"] for n, _ in self.walk() if n["kind"] == "case"}
        renamed = 0
        target = self.children(parent)
        for source in rows:
            row = deepcopy(source)
            if row["case_id"] in used:
                row["original_case_id"] = row["case_id"]
                row["case_id"] = self.next_case_id(used)
                renamed += 1
            used.add(row["case_id"])
            parts = json.loads(row["folder_path_json"]) if row.get("folder_path_json") else [p.strip() for p in row.get("folder_path", "").split("/") if p.strip()]
            container = target
            for part in parts:
                match = next((n for n in container if n["kind"] == "folder" and n["name"] == part), None)
                if match is None:
                    match = folder(part)
                    container.append(match)
                container = match["children"]
            steps = json.loads(row.get("steps_json") or "[]")
            for key in ("folder_path", "folder_path_json", "order", "steps_json"):
                row.pop(key, None)
            container.append(testcase(row, steps))
        return len(rows), renamed

    def to_dict(self):
        return {"version": 2, "name": self.name, "nodes": deepcopy(self.nodes), "settings": deepcopy(self.settings)}

    @classmethod
    def from_dict(cls, document: dict):
        if document.get("version") not in {1, 2} or not isinstance(document.get("nodes"), list):
            raise ValueError("Unsupported workspace file")
        workspace = cls(str(document.get("name", "Gradebook workspace")), deepcopy(document["nodes"]))
        if not isinstance(document.get("settings", {}), dict):
            raise ValueError("Project settings must be an object")
        workspace.settings = deepcopy(document.get("settings", {}))
        seen = set()
        records = []
        def validate(nodes, depth=0):
            if depth > 40:
                raise ValueError("Folder nesting exceeds 40 levels")
            for node in nodes:
                if not isinstance(node, dict) or not isinstance(node.get("uid"), str) or node["uid"] in seen:
                    raise ValueError("Invalid or duplicate workspace node ID")
                seen.add(node["uid"])
                if not isinstance(node.get("name"), str) or not node["name"].strip():
                    raise ValueError("Every folder/test case needs a name")
                if node.get("kind") == "folder" and isinstance(node.get("children"), list):
                    validate(node["children"], depth + 1)
                elif node.get("kind") == "case" and isinstance(node.get("record"), dict):
                    if not isinstance(node.get("steps", []), list):
                        raise ValueError("Invalid source steps")
                    records.append(node["record"])
                else:
                    raise ValueError("Invalid workspace node")
        validate(workspace.nodes)
        if records:
            parse_rows(records)
        return workspace

    @classmethod
    def load(cls, path: Path):
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8-sig")))

    def save(self, path: Path) -> None:
        self.from_dict(self.to_dict())
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            previous = path.read_bytes()
            if json.loads(previous.decode("utf-8-sig")).get("version") == 1:
                backup = path.with_name(path.stem + ".v1.backup.json")
                try:
                    with backup.open("xb") as stream:
                        stream.write(previous)
                except FileExistsError:
                    pass
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".json")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(self.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def seed(cls):
        workspace = cls()
        root = folder("Feature 003 · Gradebook")
        workspace.nodes.append(root)
        groups = {key: folder(value) for key, value in GROUPS.items()}
        root["children"] = list(groups.values())
        snapshot_path = ROOT / "data/excel_snapshot.json"
        source = {c["case_id"]: c["steps"] for c in json.loads(snapshot_path.read_text(encoding="utf-8"))} if snapshot_path.exists() else {}
        with (ROOT / "level2/data/gradebook_cases.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        parse_rows(rows)
        for row in rows:
            groups[row["workflow"]]["children"].append(testcase(row, source.get(row["case_id"], [])))
        return workspace
