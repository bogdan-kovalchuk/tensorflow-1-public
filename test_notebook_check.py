import json
from pathlib import Path
import tempfile
import unittest

import notebook_check


def make_notebook(source="", outputs=None, cell_id="cell-1"):
    return {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "id": cell_id,
                "metadata": {},
                "outputs": [] if outputs is None else outputs,
                "source": source.splitlines(keepends=True),
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


class TestNotebookLoading(unittest.TestCase):
    def test_loads_valid_notebook(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "valid.ipynb"
            path.write_text(json.dumps(make_notebook("x = 1\n")), encoding="utf-8")
            loaded = notebook_check.load_notebook(path)
        self.assertEqual(loaded["nbformat"], 4)

    def test_reports_corrupted_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "broken.ipynb"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(notebook_check.NotebookValidationError):
                notebook_check.load_notebook(path)

    def test_rejects_invalid_cell_source(self):
        notebook = make_notebook()
        notebook["cells"][0]["source"] = ["x = 1\n", 2]
        with self.assertRaisesRegex(
            notebook_check.NotebookValidationError, "non-string"
        ):
            notebook_check.validate_notebook_structure(notebook)


class TestAssignmentValidation(unittest.TestCase):
    def _write_notebook(self, root, notebook):
        path = Path(root) / "assignment.ipynb"
        path.write_text(json.dumps(notebook), encoding="utf-8")
        return path

    def test_plural_graded_marker_is_detected(self):
        notebook = make_notebook(
            "# GRADED FUNCTIONS: split_data\n"
            "def split_data(values):\n"
            "    return values[:1], values[1:]\n"
        )
        self.assertEqual(
            notebook_check.extract_graded_functions_from_notebook(notebook),
            ["split_data"],
        )

    def test_placeholder_definition_is_rejected(self):
        notebook = make_notebook(
            "# GRADED FUNCTION: build_model\n"
            "def build_model():\n"
            "    raise NotImplementedError\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_notebook(tmpdir, notebook)
            errors = notebook_check.validate_assignment(path, ["build_model"])
        self.assertTrue(any("incomplete definitions" in error for error in errors))

    def test_missing_definition_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_notebook(tmpdir, make_notebook("value = 1\n"))
            errors = notebook_check.validate_assignment(path, ["build_model"])
        self.assertTrue(any("missing definitions" in error for error in errors))


class TestStaticCellChecks(unittest.TestCase):
    def test_syntax_error_identifies_cell_and_line(self):
        errors, skipped = notebook_check.validate_code_syntax(
            make_notebook("def broken(:\n    pass\n")
        )
        self.assertEqual(skipped, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("cell 0 line 1", errors[0])

    def test_notebook_magic_is_skipped(self):
        errors, skipped = notebook_check.validate_code_syntax(
            make_notebook("%matplotlib inline\n")
        )
        self.assertEqual(errors, [])
        self.assertEqual(skipped, [0])

    def test_saved_error_output_is_rejected(self):
        output = {
            "output_type": "error",
            "ename": "ValueError",
            "evalue": "bad value",
            "traceback": [],
        }
        errors, output_count, _ = notebook_check.validate_output_hygiene(
            make_notebook(outputs=[output])
        )
        self.assertEqual(output_count, 1)
        self.assertTrue(any("ValueError" in error for error in errors))

    def test_duplicate_cell_ids_are_rejected(self):
        notebook = make_notebook()
        notebook["cells"].append(dict(notebook["cells"][0]))
        errors = notebook_check.validate_metadata_hygiene(notebook)
        self.assertTrue(any("duplicate id" in error for error in errors))


class TestCourseIndex(unittest.TestCase):
    def _write_course(self, root, indexed_path="W1/assignment/A.ipynb"):
        course = Path(root) / "C1"
        notebook_path = course / "W1" / "assignment" / "A.ipynb"
        notebook_path.parent.mkdir(parents=True)
        notebook_path.write_text(json.dumps(make_notebook()), encoding="utf-8")
        weeks = []
        for week_number in range(1, 5):
            path = indexed_path if week_number == 1 else "W{}/assignment/A.ipynb".format(week_number)
            if week_number > 1:
                destination = course / path
                destination.parent.mkdir(parents=True)
                destination.write_text(json.dumps(make_notebook()), encoding="utf-8")
            weeks.append(
                {
                    "week": "W{}".format(week_number),
                    "notebooks": {
                        "assignment": {
                            "file": path,
                            "graded_functions": [],
                        }
                    },
                }
            )
        index = {"course": "C1", "title": "Course", "weeks": weeks}
        (course / "_notebook_index.json").write_text(
            json.dumps(index), encoding="utf-8"
        )
        return course

    def test_complete_index_is_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            course = self._write_course(tmpdir)
            errors = notebook_check.validate_course_index(course)
        self.assertEqual(errors, [])

    def test_stale_index_path_is_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            course = self._write_course(tmpdir, "W1/assignment/missing.ipynb")
            errors = notebook_check.validate_course_index(course)
        self.assertTrue(any("missing indexed notebook" in error for error in errors))
        self.assertTrue(any("unindexed notebooks" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
