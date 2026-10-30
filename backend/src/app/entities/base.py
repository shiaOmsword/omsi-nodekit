from typing import Annotated

from pydantic import Field

from framework.entities import Entity

StrictModel = Entity
Port = Annotated[int, Field(ge=1, le=65535)]
Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
Host = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}$")]
User = Annotated[str, Field(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")]
