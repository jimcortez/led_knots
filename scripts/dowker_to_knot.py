"""Inspect the knot a Dowker-Thistlethwaite code describes.

The conversion itself lives in led_knots.core.pyknot_utils; this is just a CLI
around it.

Usage:
    python scripts/dowker_to_knot.py                 # uses the default DT code
    python scripts/dowker_to_knot.py 4 6 2           # trefoil
    python scripts/dowker_to_knot.py 10_1            # by Rolfsen/Knot Atlas name
"""

import sys

import numpy as np

from led_knots.core.pyknot_utils import (
    dowker_to_knot,
    dowker_to_representation,
    dt_code_for,
)

DEFAULT_DT_CODE = [8, 12, 16, 14, 18, 4, 2, 6, 10]


def main(argv):
    args = argv[1:]
    if len(args) == 1 and not args[0].lstrip('-').isdigit():
        dt_code = dt_code_for(args[0])
    else:
        dt_code = [int(arg) for arg in args] or DEFAULT_DT_CODE

    knot = dowker_to_knot(dt_code)
    spans = knot.points.max(axis=0) - knot.points.min(axis=0)

    print('DT code:        {}'.format(dt_code))
    print('Representation: {}'.format(dowker_to_representation(dt_code)))
    print('Object type:    {}.{}'.format(
        type(knot).__module__, type(knot).__name__))
    print('Points:         {}'.format(knot.points.shape))
    print('Spans (x,y,z):  {}'.format(np.round(spans, 1)))
    print('Determinant:    {}'.format(knot.determinant()))
    print('Identification: {}'.format(knot.identify()))

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
