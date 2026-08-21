import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import taskmgr


class TaskManagerCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_file = Path(self.temp_dir.name) / "taskdata.json"
        self.file_patch = patch.object(taskmgr, "task_list_file", str(self.state_file))
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)

        # TaskMgr uses class-level mutable defaults in production. Constructing it
        # directly and shadowing those attributes keeps every test independent.
        self.manager = taskmgr.TaskMgr()
        self.manager.task_data = {}
        self.manager.noti_callback = None
        self.notifications = []
        self.manager.AddNotiCallback(lambda *event: self.notifications.append(event))

    def read_state(self):
        with self.state_file.open(encoding="utf-8") as state:
            return json.load(state)

    def test_load_missing_file_leaves_empty_state(self):
        self.manager.LoadFile()

        self.assertEqual(self.manager.task_data, {})

    def test_load_corrupt_file_leaves_empty_state(self):
        self.state_file.write_text("not valid json", encoding="utf-8")

        self.manager.LoadFile()

        self.assertEqual(self.manager.task_data, {})

    def test_load_restores_saved_state(self):
        expected = {"task-1": ["Ubuntu", 1024, "user", "downloading"]}
        self.state_file.write_text(json.dumps(expected), encoding="utf-8")

        self.manager.LoadFile()

        self.assertEqual(self.manager.task_data, expected)

    def test_load_does_not_replace_current_nonempty_state(self):
        self.manager.task_data = {"current": ["Current", 1, "u", "waiting"]}
        self.state_file.write_text(
            json.dumps({"disk": ["Disk", 2, "u", "finished"]}),
            encoding="utf-8",
        )

        self.manager.LoadFile()

        self.assertEqual(
            self.manager.task_data,
            {"current": ["Current", 1, "u", "waiting"]},
        )

    def test_save_and_reload_round_trip(self):
        expected = {
            "b": ["한글", 2048, "user-b", "finished"],
            "a": ["Alpha", 1024, "user-a", "downloading"],
        }
        self.manager.task_data = expected
        self.manager.SaveTask()

        restored = taskmgr.TaskMgr()
        restored.task_data = {}
        restored.noti_callback = None
        restored.LoadFile()

        self.assertEqual(restored.task_data, expected)

    def test_new_task_notifies_and_persists(self):
        self.manager.InsertOrUpdateTask(
            "task-1", "Ubuntu", 4096, "abdullah", "downloading"
        )

        self.assertEqual(
            self.notifications,
            [("task-1", "Ubuntu", 4096, "abdullah", "downloading")],
        )
        self.assertEqual(
            self.read_state(),
            {"task-1": ["Ubuntu", 4096, "abdullah", "downloading"]},
        )

    def test_unchanged_status_suppresses_notification_and_write(self):
        original = ["Original title", 100, "user", "downloading"]
        self.manager.task_data = {"task-1": original.copy()}

        with patch.object(self.manager, "SaveTask") as save:
            self.manager.InsertOrUpdateTask(
                "task-1", "Updated title", 200, "other", "downloading"
            )

        self.assertEqual(self.notifications, [])
        save.assert_not_called()
        self.assertEqual(self.manager.task_data["task-1"], original)

    def test_status_transition_notifies_updates_and_persists(self):
        self.manager.task_data = {
            "task-1": ["Ubuntu", 4096, "abdullah", "downloading"]
        }

        self.manager.InsertOrUpdateTask(
            "task-1", "Ubuntu", 4096, "abdullah", "finished"
        )

        self.assertEqual(
            self.notifications,
            [("task-1", "Ubuntu", 4096, "abdullah", "finished")],
        )
        self.assertEqual(
            self.read_state(),
            {"task-1": ["Ubuntu", 4096, "abdullah", "finished"]},
        )

    def test_missing_active_task_is_reported_as_deleted_then_removed(self):
        self.manager.task_data = {
            "gone": ["Cancelled", 100, "user", "downloading"],
            "present": ["Still here", 200, "user", "waiting"],
        }

        self.manager.CheckRemoveTest(["present"])

        self.assertEqual(
            self.notifications,
            [("gone", "Cancelled", 100, "user", "delete")],
        )
        self.assertEqual(
            self.manager.task_data,
            {"present": ["Still here", 200, "user", "waiting"]},
        )
        self.assertEqual(self.read_state(), self.manager.task_data)

    def test_missing_finished_task_is_removed_without_delete_notification(self):
        self.manager.task_data = {
            "done": ["Complete", 100, "user", "finished"]
        }

        self.manager.CheckRemoveTest([])

        self.assertEqual(self.notifications, [])
        self.assertEqual(self.manager.task_data, {})
        self.assertEqual(self.read_state(), {})

    def test_empty_current_list_removes_all_remembered_tasks(self):
        self.manager.task_data = {
            "one": ["One", 1, "u", "downloading"],
            "two": ["Two", 2, "u", "waiting"],
        }

        self.manager.CheckRemoveTest([])

        self.assertEqual(
            self.notifications,
            [
                ("one", "One", 1, "u", "delete"),
                ("two", "Two", 2, "u", "delete"),
            ],
        )
        self.assertEqual(self.manager.task_data, {})

    def test_current_task_list_preserves_all_known_tasks(self):
        original = {
            "one": ["One", 1, "u", "downloading"],
            "two": ["Two", 2, "u", "finished"],
        }
        self.manager.task_data = {key: value.copy() for key, value in original.items()}

        self.manager.CheckRemoveTest(["one", "two"])

        self.assertEqual(self.notifications, [])
        self.assertEqual(self.manager.task_data, original)
        self.assertEqual(self.read_state(), original)


if __name__ == "__main__":
    unittest.main()
