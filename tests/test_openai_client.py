from clients.openai_client import OpenAIIngredientClassifier, parse_classification_content


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeChoice:
    def __init__(self, content: str):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content: str):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCompletion(self.content)


class FakeChat:
    def __init__(self, completions: FakeCompletions):
        self.completions = completions


class FakeClient:
    def __init__(self, content: str):
        self.completions = FakeCompletions(content)
        self.chat = FakeChat(self.completions)


def test_parse_classification_content_normalizes_openai_json():
    result = parse_classification_content(
        """
        {
          "items": [
            {"item": "초당옥수수", "is_valid": true, "normalized_name": "옥수수"},
            {"item": "노트북", "is_valid": false, "reason": "식재료가 아님"}
          ]
        }
        """
    )

    assert result == [
        {
            "item": "초당옥수수",
            "is_valid": True,
            "normalized_name": "옥수수",
            "reason": "식재료로 판단됨",
        },
        {
            "item": "노트북",
            "is_valid": False,
            "normalized_name": None,
            "reason": "식재료가 아님",
        },
    ]


def test_openai_ingredient_classifier_calls_chat_completions_with_json_mode():
    fake_client = FakeClient(
        '{"items":[{"item":"루꼴라","is_valid":true,"normalized_name":"루꼴라"}]}'
    )
    classifier = OpenAIIngredientClassifier(client=fake_client, model="gpt-4o-mini")

    result = classifier.classify_unknown_items(["루꼴라"])

    call = fake_client.completions.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["response_format"] == {"type": "json_object"}
    assert call["messages"][1]["content"] == '{"items": ["루꼴라"]}'
    assert result == [
        {
            "item": "루꼴라",
            "is_valid": True,
            "normalized_name": "루꼴라",
            "reason": "식재료로 판단됨",
        }
    ]
