from typing import Annotated
from fastapi import Path

# AIC is an OID with 10 dot-separated arcs:
#   1.2.156.3088.<base36>.<base36>.<base36>.<base36>.<base36>.<base36>
AIC_PATTERN = r"^1\.2\.156\.3088(?:\.[0-9A-Za-z]+){6}$"
TOKEN_PATTERN = r"^[A-Za-z0-9_\-]+$"

AgentAIC = Annotated[
    str,
    Path(
        ...,
        pattern=AIC_PATTERN,
        description="Agent 身份代码 (oid， 点分十段)",
        example="1.2.156.3088.0001.00001.5T4KJN.3HBAR6.1.1D6C",
    ),
]

ChallengeToken = Annotated[
    str,
    Path(
        ...,
        pattern=TOKEN_PATTERN,
        description="Challenge Token (URL safe characters)",
        example="LoqXcYV8q5ONbJQxbmR7SCTNo3tiAXDfowyjxAjEuX0",
    ),
]
