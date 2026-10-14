import json

from willia.chat import Chat
from willia.client import Reply
from willia.config import Config
from willia.todo import items_from_log, tool


class FakeClient:
    last_usage = {}

    def turn(self, messages, tools, *, on_delta=None):
        return Reply("done", "", [], {}, "stop")

    def summarize(self, request):
        return "summary"


def call(chat, action, **arguments):
    return json.loads(tool(chat, action, **arguments))


def test_add_list_done_drop_order_ids_and_records(tmp_path):
    chat = Chat.open(Config(root=tmp_path), client=FakeClient())
    try:
        first = call(chat, "add", text="first task")
        second = call(chat, "add", text="second task")
        third = call(chat, "add", text="third task")
        assert [first["id"], second["id"], third["id"]] == [0, 1, 2]

        assert call(chat, "done", id=first["id"]) == {"done": first["id"]}
        listed = call(chat, "list")["items"]
        assert [item["id"] for item in listed] == [second["id"], third["id"], first["id"]]
        assert [item["done"] for item in listed] == [False, False, True]

        assert call(chat, "drop", id=second["id"]) == {"drop": second["id"]}
        assert [item["id"] for item in call(chat, "list")["items"]] == [
            third["id"], first["id"]]

        records = chat.log.range(0, chat.log.count() - 1)
        assert [record.kind for record in records] == ["todo"] * 5
        assert [json.loads(record.text)["op"] for record in records] == [
            "add", "add", "add", "done", "drop"]
        assert items_from_log(chat.log)[first["id"]].done is True
        assert items_from_log(chat.log)[second["id"]].dropped is True
    finally:
        chat.close()


def test_list_never_truncates(tmp_path):
    chat = Chat.open(Config(root=tmp_path), client=FakeClient())
    try:
        for index in range(150):
            call(chat, "add", text=f"task {index}")
        listed = call(chat, "list")["items"]
        assert len(listed) == 150
        assert [item["text"] for item in listed] == [f"task {index}" for index in range(150)]
    finally:
        chat.close()


def test_bad_mutations_are_clear_and_do_not_write(tmp_path):
    chat = Chat.open(Config(root=tmp_path), client=FakeClient())
    try:
        assert call(chat, "add", text=" ") == {"error": "text must be a nonempty string"}
        assert call(chat, "done", id=99) == {"error": "unknown todo item: 99"}
        assert chat.log.count() == 0
    finally:
        chat.close()
