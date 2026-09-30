from typing import Annotated
from pydantic import Field, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0, strict=True)]
Attempt = Annotated[int, Field(ge=1, strict=True)]
