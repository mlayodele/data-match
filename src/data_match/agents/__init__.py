"""Pipeline stages — registered in execution order."""
from __future__ import annotations


from .stage_1 import stage_1

from .stage_2 import stage_2

from .stage_3 import stage_3


STAGES = [

    stage_1,

    stage_2,

    stage_3,

]
