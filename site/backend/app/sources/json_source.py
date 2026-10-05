import json
from pathlib import Path

from pydantic import ValidationError

from app.models import AboutContent, ContactInfo, Project, WritingContent


class ContentError(Exception):
    """Raised when a content file is missing or invalid."""


class JsonFileSource:
    def __init__(self, content_dir: Path):
        self.content_dir = content_dir

    def _raw(self, name: str):
        path = self.content_dir / f"{name}.json"
        if not path.is_file():
            raise ContentError(f"missing content file: {path}")
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise ContentError(f"invalid content file {path}: {e}") from e

    def _load(self, name: str, model):
        path = self.content_dir / f"{name}.json"
        try:
            return model.model_validate(self._raw(name))
        except ValidationError as e:
            # JSON that parses but fails the model contract is a content error,
            # not a 500-with-no-traceback: include filename + validation detail.
            raise ContentError(f"invalid content file {path}: {e}") from e

    def get_about(self) -> AboutContent:
        return self._load("about", AboutContent)

    def get_projects(self) -> list[Project]:
        raw = self._raw("projects")
        try:
            return [Project.model_validate(p) for p in raw]
        except ValidationError as e:
            raise ContentError(f"invalid content file {self.content_dir / 'projects.json'}: {e}") from e

    def get_writing(self) -> WritingContent:
        return self._load("writing", WritingContent)

    def get_contact(self) -> ContactInfo:
        return self._load("contact", ContactInfo)
