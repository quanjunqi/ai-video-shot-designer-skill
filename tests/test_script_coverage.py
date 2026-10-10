import tempfile
import unittest
from pathlib import Path

from scripts.shotdesigner.script_coverage import (
    render_unit_manuscript, sha256_file, sha256_text, validate_manuscript_files,
    validate_source_script, validate_unit_coverage,
)


def manifest():
    return {
        "events": [
            {"event_id": "EV001", "beat_id": "B1", "fact": "林夏看向钥匙。"},
            {"event_id": "EV002", "beat_id": "B2", "fact": "周明低头看着钥匙。"},
        ],
        "dialogues": [
            {"dialogue_id": "DLG001", "beat_id": "B1", "speaker_id": "林夏",
             "text": "还给你。", "language": "Chinese"},
        ],
        "locks": [],
        "authorized_changes": [],
        "sequence": ["EV001", "DLG001", "EV002"],
    }


def units():
    return [
        {"unit_id": "U01", "unit_order": 1, "script_refs": ["EV001", "DLG001"],
         "generation_duration_seconds": 6,
         "continuity": {"in": "林夏握着钥匙。", "out": "钥匙已放下。"},
         "previous_unit_id": None, "next_unit_id": "U02"},
        {"unit_id": "U02", "unit_order": 2, "script_refs": ["EV002"],
         "generation_duration_seconds": 4,
         "continuity": {"in": "钥匙在桌面。", "out": "周明仍低头。"},
         "previous_unit_id": "U01", "next_unit_id": None},
    ]


class ScriptCoverageChecks(unittest.TestCase):
    def test_exact_coverage_and_literal_dialogue_rendering(self):
        self.assertFalse(validate_unit_coverage(manifest(), units()))
        text = render_unit_manuscript(manifest(), units()[0])
        self.assertIn("林夏：还给你。", text)
        self.assertIn("[EV001] 林夏看向钥匙。", text)

    def test_dialogue_modality_is_visible_in_user_manuscript(self):
        source = manifest()
        source["dialogues"][0]["modality"] = "OS"
        text = render_unit_manuscript(source, units()[0])
        self.assertIn("林夏（OS）：还给你。", text)

    def test_v31_review_fields_are_visible_in_user_manuscript(self):
        unit = units()[0]
        unit.update({
            "entry_state": {"location": "茶馆", "人物": "林夏握着钥匙"},
            "exit_state": {"道具": "钥匙已放下"},
            "boundary_reason": "动作结果已经落稳。",
            "handoff": {"to_next": "下一单元从桌面上的钥匙开始。"},
        })
        text = render_unit_manuscript(manifest(), unit)
        self.assertIn("地点：茶馆", text)
        self.assertIn("人物：林夏握着钥匙", text)
        self.assertIn("道具：钥匙已放下", text)
        self.assertIn("## 切分理由\n\n动作结果已经落稳。", text)
        self.assertIn("## 详细承接\n\n下一单元从桌面上的钥匙开始。", text)

    def test_omission_duplicate_and_reorder_fail(self):
        omitted = units()
        omitted[1]["script_refs"] = []
        self.assertTrue(any("non-empty" in item or "omits" in item
                            for item in validate_unit_coverage(manifest(), omitted)))
        duplicated = units()
        duplicated[1]["script_refs"] = ["DLG001", "EV002"]
        self.assertTrue(any("duplicates" in item
                            for item in validate_unit_coverage(manifest(), duplicated)))
        reordered = units()
        reordered[0]["script_refs"] = ["DLG001", "EV001"]
        self.assertIn("unit coverage changes the original script order",
                      validate_unit_coverage(manifest(), reordered))

    def test_locked_script_forbids_changes_and_file_replacement(self):
        changed = manifest()
        changed["authorized_changes"] = [{"change_id": "CH1"}]
        self.assertTrue(any("forbids authorized_changes" in item
                            for item in validate_unit_coverage(changed, units())))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "script.md"
            source.write_text("原始剧本", encoding="utf-8")
            binding = {"path": "script.md", "sha256": sha256_file(source)}
            self.assertFalse(validate_source_script(binding, root))
            source.write_text("被覆盖的剧本", encoding="utf-8")
            self.assertTrue(any("new script version" in item
                                for item in validate_source_script(binding, root)))

    def test_manuscript_must_equal_deterministic_projection(self):
        plan_units = units()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "units" / "U01-shooting-manuscript.md"
            path.parent.mkdir()
            text = render_unit_manuscript(manifest(), plan_units[0])
            path.write_text(text, encoding="utf-8")
            plan_units[0]["shooting_manuscript"] = {
                "path": "units/U01-shooting-manuscript.md", "sha256": sha256_text(text)}
            second = root / "units" / "U02-shooting-manuscript.md"
            second_text = render_unit_manuscript(manifest(), plan_units[1])
            second.write_text(second_text, encoding="utf-8")
            plan_units[1]["shooting_manuscript"] = {
                "path": "units/U02-shooting-manuscript.md", "sha256": sha256_text(second_text)}
            self.assertFalse(validate_manuscript_files(manifest(), plan_units, root))
            path.write_text(text.replace("还给你。", "钥匙给你。"), encoding="utf-8")
            errors = validate_manuscript_files(manifest(), plan_units, root)
            self.assertTrue(any("differs from locked script" in item for item in errors))
            self.assertTrue(any("sha256 mismatch" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
